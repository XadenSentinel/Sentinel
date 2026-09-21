"""Cerveau de Sentinel : relie écoute, compréhension, actions et voix."""
from __future__ import annotations

import datetime
import logging
import queue
import re
import threading
import time
from difflib import SequenceMatcher

from .actions import web
from .actions.apps import AppIndex
from .actions.discord import DiscordController
from .actions.keyboard import press_media
from .actions.music import MusicPlayer
from .actions.interact import Interactor
from .actions.pc import PcControl
from .actions.scan import FileFinder, PathOpener
from .actions.system_audio import SystemAudio
from .actions.timers import Timers, TimerItem
from .actions.weather import Weather, WeatherError
from .brain import Brain, BrainError, INFO_INTENTS, TRUTH_INTENTS
from .learning import LearnedMemory, describe
from .updater import UpdateError, Updater
from .nlu import Intent, _MUSIC_WORDS, clean, normalize, parse_command
from .replies import FAIL_KEYS, R, all_variants, fr_date, fr_time, join, reset_keys, used_keys
from .voice import Listener, Speaker

log = logging.getLogger("sentinel.assistant")

WEATHER_REFRESH_SECONDS = 20 * 60
SHORTCUT_MATCH = 0.86          # similarité minimale pour reconnaître une macro vocale
# En mode « toujours IA », ces commandes simples restent traitées instantanément par les règles
QUICK_INTENTS = {"media", "volume_set", "volume_rel", "volume_mute", "time", "date", "timer_get", "timer_cancel",
                 "quit", "window_switch", "desktop", "screenshot", "lock"}


class Assistant:
    def __init__(self, cfg, ui_queue: "queue.Queue") -> None:
        self.cfg = cfg
        self.ui = ui_queue
        self.speaker = Speaker(cfg, self._on_speaker_state)
        self.listener = Listener(cfg, self.speaker, self.emit, self._on_wake, self._on_command)
        self.listener.hints = lambda: self._app_names()[:40]      # aide Whisper à bien écrire tes programmes
        self.audio = SystemAudio(cfg)
        self.music = MusicPlayer(cfg)
        self.discord = DiscordController(cfg)
        self.apps = AppIndex(cfg, on_indexed=lambda n: self.emit("apps_indexed", n))
        self.pc = PcControl(cfg)
        self.files = FileFinder(cfg, on_indexed=lambda n: self.emit("files_indexed", n))
        self.paths = PathOpener(cfg, self.files)
        self.timers = Timers(cfg, self._on_timer_done)
        self.weather = Weather(cfg)
        self.interact = Interactor(cfg)
        self.brain = Brain(cfg, self._app_names)
        self.brain.context = self.interact.foreground_summary
        self.updater = Updater(cfg)                                # mises à jour depuis GitHub
        self.memory = LearnedMemory()                              # ce que Sentinel a appris de tes corrections
        self.brain.learned = self.memory.prompt_block
        self._trace: list[Intent] = []                             # actions exécutées pour la commande en cours
        self._last: dict | None = None                             # dernière commande (boutons ✓ / ✗ de l'interface)
        self._last_brain: tuple | None = None
        self._halt = threading.Event()
        self._weather_wake = threading.Event()
        self._follow_up = False

    # ------------------------------------------------------------ cycle de vie
    def start(self) -> None:
        self.speaker.start()
        self.apps.refresh_async()
        self.files.refresh_async()
        self.listener.start()
        threading.Thread(target=self._weather_loop, daemon=True, name="sentinel-weather").start()
        threading.Thread(target=self._startup_checks, daemon=True, name="sentinel-startup").start()

    def shutdown(self) -> None:
        self._halt.set()
        self._weather_wake.set()
        self.timers.shutdown()
        self.listener.stop()
        self.speaker.shutdown()

    @property
    def level(self) -> float:
        return self.listener.level

    def set_listening(self, on: bool) -> None:
        (self.listener.enabled.set if on else self.listener.enabled.clear)()
        self.listener.active_until = 0.0
        self.emit("state", "idle" if on else "off")

    # ------------------------------------------------------------------ événements
    def emit(self, kind: str, *payload) -> None:
        self.ui.put((kind, *payload))

    def _rest_state(self) -> str:
        if not self.listener.enabled.is_set():
            return "off"
        return "listening" if self.listener.active_until > time.time() else "idle"

    def _on_speaker_state(self, state: str) -> None:
        if state == "rest" and self._follow_up:                  # conversation : on écoute la suite sans mot déclencheur
            self._follow_up = False
            if self.cfg["follow_up"] and self.listener.enabled.is_set():
                self.listener.trigger()
                return
        self.emit("state", "speaking" if state == "speaking" else self._rest_state())

    def _startup_checks(self) -> None:
        """Préchauffe la voix (phrases habituelles) et vérifie le cerveau IA, sans gêner le démarrage."""
        try:
            self.speaker.prewarm(all_variants(self.cfg, "ack") + all_variants(self.cfg, "done") + all_variants(self.cfg, "thinking"))
        except Exception:
            log.debug("préchauffage vocal impossible", exc_info=True)
        self.emit("brain", self.brain.status(force=True) if self.brain.enabled else
                  {"ok": False, "model": "", "models": [], "message": "Cerveau IA désactivé."})
        if self.cfg["update_check"] and self.updater.enabled and time.time() - self.cfg["update_last_check"] > 22 * 3600:
            try:
                rel = self.updater.check()
                if rel:
                    self.emit("update", "available", rel)
            except UpdateError as exc:
                log.info("recherche de mise à jour : %s", exc)

    def _app_names(self) -> list[str]:
        """Noms d'applications donnés à l'IA pour qu'elle comprenne « mon jeu de course »."""
        names = list(self.cfg["app_aliases"].keys())
        names += [e[0] for e in self.apps.entries if e[1] in ("uri", "startapp", "file")]
        return list(dict.fromkeys(names))

    def _on_wake(self) -> None:
        self.speaker.say(R(self.cfg, "ack"))

    def _on_command(self, text: str) -> None:
        threading.Thread(target=self._process, args=(text,), daemon=True, name="sentinel-cmd").start()

    # ------------------------------------------------------------------ météo (HUD)
    def refresh_weather(self) -> None:
        self._weather_wake.set()

    def _weather_loop(self) -> None:
        while not self._halt.is_set():
            city = (self.cfg["weather_city"] or "").strip()
            data, reason = None, ""
            if not city:
                reason = "no_city"
            else:
                try:
                    data = self.weather.fetch(city, force=True)
                except WeatherError as exc:
                    reason = exc.kind
                except Exception:
                    log.exception("météo : erreur inattendue")
                    reason = "network"
            self.emit("weather", data, reason)
            self._weather_wake.wait(WEATHER_REFRESH_SECONDS)
            self._weather_wake.clear()

    # ------------------------------------------------------------------ minuteurs
    def _on_timer_done(self, item: TimerItem) -> None:
        text = self.timers.say_done(item)
        self.emit("log", "reply", text)
        threading.Thread(target=self._ring, args=(text,), daemon=True, name="sentinel-alarm").start()

    def _ring(self, text: str) -> None:
        try:
            import winsound
            for _ in range(3):
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                time.sleep(0.45)
        except Exception:
            pass                                  # pas Windows : on parle seulement
        self.speaker.say(text)

    # ------------------------------------------------------------------ traitement
    def _process(self, text: str) -> None:
        self.emit("state", "thinking")
        self.emit("log", "cmd", text)
        self._trace, self._last_brain = [], None
        try:
            reply = self.run_text(text)
        except Exception:
            log.exception("erreur pendant l'exécution de « %s »", text)
            reply = R(self.cfg, "error")
        used_brain = self._last_brain is not None
        understood = " ; ".join(describe(i) for i in self._trace if i.name not in ("empty", "wait")) or ("Discussion (IA)" if used_brain else "—")
        self._last = {"heard": text, "understood": understood, "reply": reply, "brain": used_brain}
        self.emit("interaction", dict(self._last))
        if reply:
            self.emit("log", "reply", reply)
            self.speaker.say(reply)
        if not self.speaker.busy.is_set():
            self.emit("state", self._rest_state())

    def run_text(self, text: str, learned: bool = True) -> str:
        """Texte d'une commande -> exécution -> phrase de réponse.
        Ordre : corrections apprises -> macros vocales -> règles rapides -> cerveau IA (si dispo) pour tout le reste."""
        if learned:
            meant = self.memory.lookup(text)
            if meant and clean(meant) != clean(text):
                self.emit("log", "info", f"Appris : « {text} » → « {meant} »")
                return self.run_text(meant, learned=False)
        raw_it = self._parse_raw(text)
        if raw_it is not None:
            return self._execute(raw_it)
        n = self._apply_corrections(text)
        commands = self._expand_shortcut(n)
        if len(commands) > 1:
            for cmd in commands:
                try:
                    self._execute(parse_command(cmd))
                except Exception:
                    log.exception("étape de macro en échec : %s", cmd)
            return R(self.cfg, "done")

        parts = self._split_multi(commands[0])
        if parts:                                                 # « baisse le son et donne-moi la météo »
            return join(*(self._execute(parse_command(p)) for p in parts))

        intent = self._arbitrate(parse_command(commands[0]), commands[0])
        if self.brain.enabled and self._wants_brain(intent, commands[0]):
            answer = self._think(text, commands[0])
            if answer is not None:
                return answer
        return self._execute(intent)

    _RAW_TYPE = re.compile(r"^\s*(?:tape|tapes|saisis|dicte|ecris|écris|écrire)\s*:?\s+(.+?)\s*$", re.I | re.S)
    _RAW_URL = re.compile(r"^\s*(?:va|vas|aller|ouvre|ouvrir|navigue)\s+(?:sur|vers|à|a)?\s*((?:https?://)?[\w-]+(?:\.[\w-]+)+(?:/\S*)?)\s*[.!?]?\s*$", re.I)

    @classmethod
    def _parse_raw(cls, text: str) -> Intent | None:
        """Règles qui ont besoin du texte ORIGINAL (accents, majuscules, points) : dictée et adresses de sites."""
        m = cls._RAW_URL.match(text)
        if m:
            return Intent("open_url", {"url": m.group(1)})
        m = cls._RAW_TYPE.match(text)
        if m and not re.match(r"^(?:un|une|moi|à|a|pour|le|la|les|mon|ma)\b", m.group(1), re.I) or (
                m and re.match(r"^\s*(?:tape|tapes|saisis|dicte)\b", text, re.I)):
            return Intent("type_text", {"text": m.group(1).strip().strip("«»\"")})
        return None

    def _arbitrate(self, it: Intent, cmd: str) -> Intent:
        """« mets Chrome » / « joue Minecraft » : si le nom correspond nettement à un programme installé
        (et que la phrase ne parle pas de musique), c'est une application, pas un morceau."""
        if it.name == "music":
            q = (it.args.get("query") or "").strip()
            if (q and not it.args.get("playlist") and not it.args.get("provider") and not it.args.get("radio")
                    and not re.search(_MUSIC_WORDS, cmd) and self.apps.find(q, min_score=0.9)):
                log.info("arbitrage : « %s » est une application, pas de la musique", q)
                return Intent("open_app", {"name": q})
        return it

    @staticmethod
    def _split_multi(cmd: str) -> list[str] | None:
        """Coupe « A et B » en deux commandes SI chaque morceau est une commande valable à lui seul."""
        pieces = [p.strip() for p in re.split(r"\b(?:et puis|et ensuite|et apres|puis|ensuite|apres ca|et aussi|et)\b", clean(cmd)) if p.strip()]
        if not 2 <= len(pieces) <= 3:
            return None
        if any(parse_command(p).name in ("unknown", "empty") for p in pieces):
            return None
        return pieces

    # « dans Chrome, écris météo Lille » contient le mot « météo » mais c'est une saisie : c'est à l'IA d'en décider
    _INTERACT_HINT = re.compile(r"\b(?:ecris|ecrire|tape|tapes|saisis|dicte|clique|cliquer|appuie|onglet|"
                                r"dans (?:chrome|firefox|edge|opera|discord|word|excel|le navigateur|la fenetre|cette fenetre|l application))\b")

    def _wants_brain(self, it: Intent, cmd: str = "") -> bool:
        if it.name == "empty":
            return False
        if (cmd and self._INTERACT_HINT.search(cmd)
                and it.name not in ("press_keys", "scroll", "type_text", "open_url", "focus_window", "ui_click")):
            return True
        if it.name == "unknown":
            return True
        if it.name == "open_app" and self.apps.find(it.args.get("name", "")) is None:
            return True                                           # « lance une blague » : ce n'est pas un programme
        if it.name == "music" and self._vague_music(it.args.get("query", "")):
            return True                                           # « mets un truc calme pour bosser » : l'IA choisit
        return self.cfg["brain_mode"] == "always" and it.name not in QUICK_INTENTS

    @staticmethod
    def _vague_music(query: str) -> bool:
        q = normalize(query)
        return bool(q) and (len(q.split()) >= 6 or bool(re.search(
            r"^(un truc|quelque chose|une chanson|un son|une musique|de la musique|du son|de quoi)\b|"
            r"\b(calme|triste|joyeu\w*|energique|relax\w*|ambiance|humeur|pour (bosser|dormir|courir|travailler|me|le sport|reviser)|"
            r"dernier|nouveaute|nouveau son|au hasard|surprends)\b", q)))

    def _think(self, text: str, normalized: str) -> str | None:
        """Passe la phrase au cerveau IA. None = IA indisponible (on retombe sur les règles)."""
        if not self.brain.available():
            return None
        self._follow_up = False
        filler = threading.Timer(3.5, lambda: self.speaker.say(R(self.cfg, "thinking")))
        filler.daemon = True
        filler.start()
        try:
            result = self.brain.ask(text)
            self._last_brain = (text, result)
        except BrainError as exc:
            log.warning("cerveau IA en échec : %s", exc)
            self.emit("log", "error", f"Cerveau IA : {exc}")
            return None
        finally:
            filler.cancel()
        replies, truth, failures = [], [], []
        for it in result.actions:
            reset_keys()
            rep = self._execute(it)
            replies.append(rep)
            if any(k in FAIL_KEYS for k in used_keys()):
                failures.append(rep)
                break                                             # un plan qui échoue s'arrête : on ne tape pas dans la mauvaise fenêtre
            if it.name in TRUTH_INTENTS:
                truth.append(rep)
        if result.actions:
            answer = join(*failures) if failures else join(*truth) if truth else (result.say or join(*replies))
        elif result.refused:
            answer = R(self.cfg, "brain_refuse")
        else:
            answer = result.say or R(self.cfg, "unknown", heard=normalized)
            self._follow_up = bool(result.say)                    # discussion : on laisse la parole à l'utilisateur
        return answer

    # ------------------------------------------------------------------ apprentissage
    def teach(self, heard: str, meant: str, rerun: bool = True) -> None:
        """L'utilisateur corrige : « j'ai dit X mais je voulais Y »."""
        self.memory.add_fix(heard, meant)
        self.emit("log", "info", f"Appris : « {heard} » → « {meant} »")
        self.emit("learned")
        if rerun:
            self._on_command(meant)

    def confirm(self) -> bool:
        """« Bien compris » : garde comme exemple ce que l'IA a fait (seulement si c'est elle qui a décidé)."""
        if not (self._last and self._last.get("brain") and self._last_brain and self._last_brain[1].actions):
            return False
        text, result = self._last_brain
        self.memory.add_example(text, [{"intent": a.name, "args": a.args} for a in result.actions], result.say)
        self.emit("learned")
        return True

    def explain(self, text: str) -> str:
        """Pour la page Commandes : ce que Sentinel comprendrait, SANS rien exécuter."""
        meant = self.memory.lookup(text)
        if meant and clean(meant) != clean(text):
            return f"appris → « {meant} »  →  " + self.explain(meant)
        raw_it = self._parse_raw(text)
        if raw_it is not None:
            return f"{raw_it.name} {raw_it.args}"
        n = self._apply_corrections(text)
        commands = self._expand_shortcut(n)
        out = []
        for cmd in commands:
            it = self._arbitrate(parse_command(cmd), cmd)
            if it.name == "unknown":
                out.append("pas de règle -> transmis au cerveau IA" if self.brain.enabled else "non compris")
            else:
                out.append(f"{it.name} {it.args}" if it.args else it.name)
        prefix = "macro → " if commands != [n] else ""
        return prefix + "  +  ".join(out)

    def _apply_corrections(self, text: str) -> str:
        n = normalize(text)
        for wrong, right in self.cfg["corrections"].items():
            w = normalize(wrong)
            if w:
                n = re.sub(rf"\b{re.escape(w)}\b", normalize(right), n)
        return n

    def _expand_shortcut(self, n: str) -> list[str]:
        """Macros vocales : « mode jeu » -> « coupe le son ; lance fortnite »."""
        cleaned = clean(n)
        best, best_score = None, 0.0
        for phrase, command in self.cfg["shortcuts"].items():
            p = clean(phrase)
            if not p:
                continue
            score = 1.0 if p == cleaned else SequenceMatcher(None, p, cleaned).ratio()
            if score > best_score:
                best, best_score = command, score
        if best and best_score >= SHORTCUT_MATCH:
            steps = [s.strip() for s in str(best).split(";") if s.strip()]
            if steps:
                return steps
        return [n]

    def _execute(self, it: Intent) -> str:
        self._trace.append(it)
        a, c = it.args, self.cfg
        match it.name:
            case "empty":
                return ""
            case "smalltalk":
                return R(c, a["kind"])
            case "quit":
                self.emit("quit")
                return R(c, "quit")
            case "time":
                return R(c, "time", heure=fr_time(datetime.datetime.now()))
            case "date":
                return R(c, "date", date=fr_date(datetime.date.today()))
            case "volume_set":
                return self.audio.set_percent(a["value"])
            case "volume_rel":
                return self.audio.change(a["direction"], a["amount"])
            case "volume_get":
                return self.audio.describe()
            case "volume_mute":
                return self.audio.mute(a["mute"])
            case "discord_mute":
                return self.discord.set_mute(a["mute"])
            case "discord_toggle":
                return self.discord.toggle_mute()
            case "discord_deafen":
                return self.discord.set_deafen(a["on"])
            case "discord_leave":
                return self.discord.leave_voice()
            case "media":
                press_media(a["action"])
                return R(c, f"media_{a['action']}")
            case "music":
                return self.music.play(a["query"], a["playlist"], a["radio"], a.get("provider"))
            case "open_path":
                return self.paths.open(a.get("kind"), a["query"])
            case "focus_window":
                return self.interact.focus(a["title"])
            case "press_keys":
                return self.interact.press(a["keys"])
            case "type_text":
                return self.interact.type_text(a["text"])
            case "ui_click":
                return self.interact.ui_click(a["label"])
            case "open_url":
                return self.interact.open_url(a["url"])
            case "scroll":
                return self.interact.scroll(a["direction"])
            case "wait":
                time.sleep(min(5, int(a["seconds"])))
                return ""
            case "web":
                return web.search(c, a["query"], a["engine"])
            case "open_app":
                return self.apps.open(a["name"])
            case "close_app":
                return self.pc.close_app(a["name"], a["force"])
            case "window_close":
                return self.pc.close_window()
            case "tab_close":
                return self.pc.close_tab()
            case "window_switch":
                return self.pc.window_switch()
            case "desktop":
                return self.pc.desktop()
            case "sleep":
                return self.pc.sleep()
            case "lock":
                return self.pc.lock()
            case "screenshot":
                return self.pc.screenshot()
            case "brightness_set":
                return self.pc.brightness_set(a["value"])
            case "brightness_rel":
                return self.pc.brightness_change(a["direction"], a["amount"])
            case "brightness_get":
                return self.pc.brightness_describe()
            case "timer_set":
                return self.timers.say_set(a["seconds"], a["label"])
            case "timer_get":
                return self.timers.say_left()
            case "timer_cancel":
                return self.timers.say_cancel()
            case "weather":
                return self.weather.answer(a["city"], a["when"])
            case _:
                return R(c, "unknown", heard=a.get("text", ""))
