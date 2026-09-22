"""Chef d'orchestre de l'interface web : relie l'assistant (Python) aux pages HTML."""
from __future__ import annotations

import collections
import logging
import queue
import threading
import time

from .. import __version__
from ..config import PROFILE_KEYS, apply_profile, bundle_dir, data_dir, export_profile  # noqa: F401
from ..replies import CATALOG, default_text, editable, preview
from ..system import cpu_percent, ram_percent, restart_app, set_autostart
from ..tts import EDGE_VOICES
from ..ui import theme as T
from ..ui.command_docs import COMMAND_DOCS
from ..updater import UpdateError
from ..voice import list_mics, list_voices
from . import schema
from .events import EventBus, translate
from .server import WebServer
from .window import find_browser, launch_app_window

log = logging.getLogger("sentinel.webctl")
STATIC = bundle_dir() / "sentinel" / "webui" / "static"
DISCORD_ACTIONS = ("toggle_mute", "toggle_deafen", "leave_voice")


class WebController:
    def __init__(self, cfg, assistant, ui_queue: "queue.Queue", tk_queue: "queue.Queue") -> None:
        self.cfg, self.assistant = cfg, assistant
        self.ui_queue, self.tk_queue = ui_queue, tk_queue
        self.bus = EventBus()
        self.server = WebServer(self, STATIC)
        self.logs: collections.deque = collections.deque(maxlen=500)
        self._halt = threading.Event()
        self._state = "loading"
        self._release = None

    # ------------------------------------------------------------------ cycle de vie
    def start(self) -> None:
        self.server.start()
        threading.Thread(target=self._hub, daemon=True, name="sentinel-web-hub").start()
        threading.Thread(target=self._ticker, daemon=True, name="sentinel-web-ticker").start()

    def stop(self) -> None:
        self._halt.set()
        self.server.stop()

    def brand(self) -> str:
        return (self.cfg["assistant_name"] or self.cfg["wake_word"] or "Sentinel").strip().capitalize()

    def open_window(self) -> None:
        """Ouvre (ou ramène au premier plan) la fenêtre de l'interface."""
        try:
            if self.assistant.interact.focus_exact(self.brand()):
                return
        except Exception:
            log.debug("recherche de la fenêtre impossible", exc_info=True)
        exe = find_browser()
        if not exe:
            log.warning("aucun navigateur Edge / Chrome trouvé : ouverture de l'interface classique")
            self.tk_queue.put(("show_classic", ""))
            return
        launch_app_window(exe, self.server.url(), data_dir() / "webview")

    # ------------------------------------------------------------------ événements de l'assistant -> pages web
    def _hub(self) -> None:
        while not self._halt.is_set():
            try:
                ev = self.ui_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if ev[0] == "state":
                self._state = ev[1]
            elif ev[0] == "log" and len(ev) > 2:
                self.logs.append({"ts": time.strftime("%H:%M:%S"), "kind": str(ev[1]), "text": str(ev[2])})
            elif ev[0] == "update" and len(ev) > 2 and ev[1] == "available":
                self._release = ev[2]
            try:
                self.bus.publish(translate(ev))
            except Exception:
                log.debug("événement non transmis", exc_info=True)
            self.tk_queue.put(ev)                          # la fenêtre classique (réglages avancés) les reçoit aussi

    def _ticker(self) -> None:
        last, n = -1.0, 0
        while not self._halt.wait(0.066):
            level = round(float(self.assistant.level), 3)
            if abs(level - last) > 0.004:
                last = level
                self.bus.publish({"t": "level", "a": [level]})
            n += 1
            if n % 15 == 0:                                # environ une fois par seconde
                items = [{"label": t.label or "", "left": round(t.left), "total": t.seconds} for t in self.assistant.timers.snapshot()[:6]]
                self.bus.publish({"t": "timers", "a": [items]})
                self.bus.publish({"t": "telemetry", "a": [round(cpu_percent()), round(ram_percent())]})

    # ------------------------------------------------------------------ thème
    def palette(self) -> dict:
        c = self.cfg
        if T.is_hex(c["custom_bg"]) and T.luminance(c["custom_bg"]) <= 0.25:
            return T.derive(c["custom_bg"])
        return T.THEMES.get(c["theme"], T.THEMES[T.DEFAULT_THEME])

    def snapshot(self) -> dict:
        c = self.cfg
        voice = "Windows" if c["tts_engine"] == "sapi" else EDGE_VOICES.get(c["tts_edge_voice"], c["tts_edge_voice"]).split(" — ")[0]
        accent = c["custom_accent"] if T.is_hex(c["custom_accent"]) else T.ACCENTS.get(c["accent"], T.ACCENTS["Cyan"])
        wake = (c["wake_word"] or "sentinel").capitalize()
        return {"brand": self.brand(), "version": __version__, "user": c["user_name"], "wake": wake, "accent": accent,
                "accent_name": c["accent"], "custom_accent": c["custom_accent"], "density": c["sphere_density"],
                "fx": c["hud_fx"], "skip_intro": c["skip_intro"], "voice": voice, "state": self._state,
                "listening": self.assistant.listener.enabled.is_set(), "accents": T.ACCENTS, "brain": bool(c["brain_enabled"]),
                "palette": self.palette(), "first_run": not c["first_run_done"]}

    # ------------------------------------------------------------------ listes dynamiques
    def options(self, name: str) -> list:
        if name == "mics":
            return [["", "Micro par défaut"]] + [[m.split(":")[0], m] for m in list_mics()]
        if name == "voices":
            return [["", "Automatique (français)"]] + [[v, v] for v in list_voices()]
        if name == "models":
            models = list(self.assistant.brain.status().get("models") or [])
            cur = self.cfg["brain_model"]
            if cur and cur not in models:
                models.append(cur)
            return [["", "Automatique"]] + [[m, m] for m in models]
        return []

    def schema_for(self, page: str) -> dict:
        spec = schema.PAGES.get(page)
        if spec is None:
            return {"ok": False, "error": "page inconnue"}
        sections = []
        for sec in spec["sections"]:
            fields = []
            for f in sec["fields"]:
                f = dict(f)
                if f.get("options_from"):
                    f["options"] = self.options(f.pop("options_from"))
                f["value"] = schema.public_value(self.cfg, f)
                fields.append(f)
            sections.append({**sec, "fields": fields})
        return {"ok": True, "title": spec["title"], "sections": sections}

    # ------------------------------------------------------------------ données des pages spéciales
    def data(self, name: str) -> dict:
        c, a = self.cfg, self.assistant
        if name == "commands":
            return {"docs": [{"category": cat, "icon": icon, "entries": [{"title": t, "examples": ex, "note": n} for t, ex, n in entries]}
                             for cat, icon, entries in COMMAND_DOCS], "wake": self.snapshot()["wake"]}
        if name == "learned":
            return {"items": [{"heard": i["heard"], "meant": i.get("meant", ""), "kind": i["kind"], "ts": i.get("ts", 0)} for i in reversed(a.memory.items[-60:])]}
        if name == "facts":
            return {"items": list(reversed(a.facts.items[-100:]))}
        if name == "replies":
            items = [{"key": k, "label": lab, "args": list(args), "default": default_text(c, k), "custom": c["custom_replies"].get(k, "")}
                     for k, lab, args in editable()]
            return {"items": items}
        if name == "log":
            return {"items": list(self.logs)}
        if name == "spotify":
            return {"connected": a.music.spotify.connected(), "client_id_set": bool(c["spotify_client_id"].strip())}
        if name == "brain":
            st = a.brain.status()
            return {"status": st, "enabled": bool(c["brain_enabled"]), "backend": c["brain_backend"],
                    "can_launch": c["brain_backend"] == "ollama" and not st["ok"] and bool(a.brain.find_ollama())}
        if name == "update":
            return {"version": __version__, "enabled": a.updater.enabled, "repo": a.updater.repo, "previous": a.updater.previous_version(),
                    "available": self._release.version if self._release else ""}
        if name == "system":
            return {"apps": len(a.apps.entries), "files": len(a.files.items)}
        return {"ok": False, "error": "inconnu"}

    # ------------------------------------------------------------------ réglages
    def set_setting(self, key: str, value) -> dict:
        field = schema.FIELDS.get(key)
        if field is None:
            return {"ok": False, "error": "réglage inconnu"}
        try:
            allowed = self.options(field["options_from"]) if field.get("options_from") else None
            if field["key"] == "mic_device":
                value = "" if value in (None, "") else str(value)
            new = schema.coerce(field, value, allowed)
            if key == "mic_device":
                new = int(new) if new != "" else None
            if field["type"] == "secret" and new == "":
                return {"ok": True, "snapshot": self.snapshot()}      # champ vide : on garde la clé enregistrée
        except (ValueError, TypeError) as exc:
            return {"ok": False, "error": str(exc)}
        old = schema.get_value(self.cfg, key)
        if "." in key:
            base, sub = key.split(".", 1)
            d = dict(self.cfg[base])
            d[sub] = new.lower() if base == "discord_keys" else new
            self.cfg[base] = d
        else:
            self.cfg[key] = new.lower() if key == "wake_word" else new
            if key == "wake_word" and not self.cfg[key]:
                self.cfg[key] = "sentinel"
        self.cfg.save()
        self._after_change(key, old, new)
        return {"ok": True, "snapshot": self.snapshot()}

    def _after_change(self, key: str, old, new) -> None:
        a = self.assistant
        try:
            if key == "mic_device":
                a.listener.restart_stream()
            elif key in ("asr_whisper", "whisper_model"):
                a.listener.asr.reset()
            elif key == "weather_city":
                a.refresh_weather()
            elif key == "start_with_windows":
                set_autostart(bool(new))
            elif key in ("tts_engine", "tts_edge_voice"):
                a.speaker._edge_down_until = 0.0
            elif key.startswith("brain_"):
                threading.Thread(target=lambda: a.emit("brain", a.brain.status(force=True)), daemon=True).start()
        except Exception:
            log.exception("effet du réglage %s impossible", key)
            if key == "start_with_windows":
                self.cfg[key] = bool(old)
                self.cfg.save()

    # ------------------------------------------------------------------ actions
    def handle_action(self, name: str, data: dict) -> dict:
        fn = getattr(self, "act_" + name, None) if name.replace("_", "").isalnum() else None
        if fn is None:
            return {"ok": False, "error": "action inconnue"}
        try:
            return fn(data if isinstance(data, dict) else {}) or {"ok": True}
        except UpdateError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            log.exception("action %s en échec", name)
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def _thread(self, fn, *args) -> None:
        threading.Thread(target=fn, args=args, daemon=True, name="sentinel-web-action").start()

    def act_command(self, d):
        text = str(d.get("text", "")).strip()[:500]
        if text:
            self.assistant._on_command(text)
        return {"ok": bool(text)}

    def act_explain(self, d):
        return {"ok": True, "text": self.assistant.explain(str(d.get("text", ""))[:300])}

    def act_trigger(self, d):
        self.assistant.listener.trigger()

    def act_listen(self, d):
        self.tk_queue.put(("set_listen", bool(d.get("on"))))

    def act_start(self, d):
        return {"ok": True}

    def act_open_classic(self, d):
        self.tk_queue.put(("show_classic", str(d.get("page") or "")[:20]))

    def act_quit(self, d):
        self.tk_queue.put(("quit",))

    def act_restart(self, d):
        restart_app()
        self.tk_queue.put(("quit",))

    def act_secret_clear(self, d):
        key = str(d.get("key", ""))
        if key not in schema.SECRETS:
            return {"ok": False, "error": "réglage inconnu"}
        self.cfg[key] = ""
        self.cfg.save()
        self._after_change(key, "x", "")

    # -- apprentissage
    def act_teach(self, d):
        heard, meant = str(d.get("heard", "")).strip()[:300], str(d.get("meant", "")).strip()[:300]
        if not heard or not meant:
            return {"ok": False, "error": "phrases manquantes"}
        self.assistant.teach(heard, meant, bool(d.get("rerun", True)))

    def act_confirm(self, d):
        return {"ok": True, "kept": bool(self.assistant.confirm())}

    def act_learned_remove(self, d):
        self.assistant.memory.remove(int(d.get("ts", 0)))
        self.assistant.emit("learned")

    def act_learned_clear(self, d):
        self.assistant.memory.clear()
        self.assistant.emit("learned")

    def act_fact_remove(self, d):
        self.assistant.facts.remove(int(d.get("ts", 0)))

    def act_fact_clear(self, d):
        self.assistant.facts.clear()

    # -- applis
    def act_apps_rescan(self, d):
        self.assistant.apps.refresh_async(True)
        self.assistant.files.refresh_async(0.5)

    # -- spotify
    def act_spotify_connect(self, d):
        if not self.cfg["spotify_client_id"].strip():
            return {"ok": False, "error": "Colle d'abord ton Client ID Spotify."}
        sp = self.assistant.music.spotify
        self._thread(lambda: self.assistant.emit("spotify_status", sp.connect_blocking()))
        return {"ok": True, "started": True}

    def act_spotify_disconnect(self, d):
        self.assistant.music.spotify.disconnect()
        self.assistant.emit("spotify_status", "Déconnecté.")

    # -- discord
    def act_discord_test(self, d):
        action = str(d.get("action", ""))
        if action not in DISCORD_ACTIONS:
            return {"ok": False, "error": "action inconnue"}
        return {"ok": True, "text": self.assistant.discord.test(action)}

    def act_discord_reset(self, d):
        self.assistant.discord.reset_state()

    # -- cerveau IA / voix
    def act_brain_check(self, d):
        a = self.assistant
        self._thread(lambda: a.emit("brain", a.brain.status(force=True, verify=True)))

    def act_ollama_launch(self, d):
        a = self.assistant
        if not a.brain.launch_local():
            return {"ok": False, "error": "Ollama est introuvable. Installe-le depuis ollama.com/download."}

        def work():
            time.sleep(2.5)
            a.emit("brain", a.brain.status(force=True))

        self._thread(work)
        return {"ok": True, "started": True}

    def act_brain_forget(self, d):
        self.assistant.brain.forget()

    def act_voice_test(self, d):
        self.assistant.speaker.say(str(d.get("text") or "Systèmes opérationnels. Sentinel est à votre écoute.")[:200])

    # -- réponses
    def act_reply_set(self, d):
        key, text = str(d.get("key", "")), str(d.get("text", "")).strip()[:400]
        if key not in CATALOG:
            return {"ok": False, "error": "phrase inconnue"}
        custom = dict(self.cfg["custom_replies"])
        if text:
            custom[key] = text
        else:
            custom.pop(key, None)
        self.cfg["custom_replies"] = custom
        self.cfg.save()

    def act_reply_preview(self, d):
        key = str(d.get("key", ""))
        if key not in CATALOG:
            return {"ok": False, "error": "phrase inconnue"}
        text = preview(self.cfg, key, str(d.get("text", ""))[:400])
        self.assistant.speaker.say(text)
        return {"ok": True, "text": text}

    def act_reply_reset(self, d):
        self.cfg["custom_replies"] = {}
        self.cfg.save()

    # -- mises à jour
    def act_update_check(self, d):
        a = self.assistant
        if not a.updater.enabled:
            a.emit("update", "error", "Les mises à jour ne sont pas configurées (dépôt GitHub manquant).")
            return

        def work():
            try:
                rel = a.updater.check()
                a.emit("update", "available", rel) if rel else a.emit("update", "uptodate", None)
            except UpdateError as exc:
                a.emit("update", "error", str(exc))

        self._thread(work)

    def act_update_install(self, d):
        a, rel = self.assistant, self._release
        if rel is None:
            return {"ok": False, "error": "Cherche d'abord une mise à jour."}

        def work():
            try:
                a.updater.install(rel, lambda done, total: a.emit("update", "progress", (done, total)))
                a.emit("update", "installed", None)
            except UpdateError as exc:
                a.emit("update", "error", str(exc))
            except Exception as exc:
                log.exception("mise à jour en échec")
                a.emit("update", "error", f"Erreur inattendue : {exc}")

        self._thread(work)

    def act_update_rollback(self, d):
        self.assistant.updater.rollback()
        self.assistant.emit("update", "installed", None)

    # -- profil et bienvenue
    def act_profile_export(self, d):
        return {"ok": True, "profile": {"sentinel_profile": 1, "settings": {k: self.cfg[k] for k in PROFILE_KEYS}}}

    def act_profile_import(self, d):
        count = apply_profile(self.cfg, {"settings": d.get("settings") or {}})
        return {"ok": True, "count": count, "snapshot": self.snapshot()}

    def act_wizard(self, d):
        c = self.cfg
        c["user_name"] = str(d.get("user_name", "")).strip()[:60]
        c["wake_word"] = (str(d.get("wake_word", "")).strip().lower()[:30] or "sentinel")
        c["weather_city"] = str(d.get("weather_city", "")).strip()[:80]
        male = d.get("voice") != "female"
        c["tts_edge_voice"] = "fr-FR-HenriNeural" if male else "fr-FR-DeniseNeural"
        c["tts_gender"] = "male" if male else "female"
        style = str(d.get("style", "jarvis"))
        c["reply_style"] = style if style in schema.STYLES else "jarvis"
        c["first_run_done"] = True
        c.save()
        self.assistant.refresh_weather()
        return {"ok": True, "snapshot": self.snapshot()}

    def act_log_clear(self, d):
        self.logs.clear()
