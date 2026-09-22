"""Cerveau IA de Sentinel : comprend les phrases libres, décide des actions, discute.

Fonctionne avec un modèle de langage LOCAL et GRATUIT (Ollama : https://ollama.com) — rien ne quitte ton PC.
Un serveur compatible OpenAI (LM Studio, etc.) marche aussi.

Principe : l'IA ne touche jamais au PC directement. Elle répond par un objet JSON
  {"actions": [{"intent": "...", "args": {...}}], "say": "phrase à prononcer"}
que Sentinel VÉRIFIE (liste blanche d'actions, arguments contrôlés, garde-fous sur les actions sensibles)
avant de l'exécuter avec les mêmes fonctions que les commandes vocales classiques.
"""
from __future__ import annotations

import datetime
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request

from .say_stream import SayStreamer
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from .nlu import Intent, normalize
from .replies import DAYS, MONTHS

log = logging.getLogger("sentinel.brain")

MEMORY_TURNS = 8               # nombre d'échanges gardés en mémoire
MEMORY_EXPIRE = 10 * 60        # oubli après 10 minutes de silence
MAX_ACTIONS = 8
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODELS = ["claude-haiku-4-5-20251001", "claude-sonnet-5", "claude-opus-5"]   # du plus rapide / économique au plus puissant
PREFERRED = ("qwen2.5:7b", "qwen2.5", "qwen3", "gemma3", "llama3.1", "llama3.2", "mistral", "phi4", "phi3")


class BrainError(Exception):
    pass


@dataclass
class BrainResult:
    actions: list[Intent] = field(default_factory=list)
    say: str = ""
    refused: bool = False


# --------------------------------------------------------------------------- #
# Actions autorisées (liste blanche) et vérification des arguments
# --------------------------------------------------------------------------- #
def _int(lo: int, hi: int):
    def f(v):
        return max(lo, min(hi, int(float(str(v).replace(",", ".").strip().rstrip("%")))))
    return f


def _bool(v) -> bool:
    return v if isinstance(v, bool) else str(v).strip().lower() in ("true", "1", "oui", "yes", "vrai")


def _dir(v) -> int:
    if isinstance(v, (int, float)):
        return 1 if v > 0 else -1
    return -1 if re.search(r"-|moins|bas|down|baiss|dimin|reduis", str(v).lower()) else 1


def _str(v) -> str:
    s = str(v).strip()
    if not s or s.lower() == "null":
        raise ValueError("vide")
    return s[:120]


def _text(v) -> str:
    s = str(v).strip()
    if not s or s.lower() == "null":
        raise ValueError("vide")
    return s[:400]


def _opt_str(v):
    return None if v is None or str(v).strip().lower() in ("", "null", "none") else str(v).strip()[:120]


def _opt_int(v):
    return None if v is None or str(v).strip().lower() in ("", "null", "none") else _int(1, 100)(v)


def _enum(*values: str):
    def f(v):
        s = str(v).strip().lower()
        if s not in values:
            raise ValueError(s)
        return s
    return f


def _opt_enum(*values: str):
    def f(v):
        return None if v is None or str(v).strip().lower() in ("", "null", "none") else _enum(*values)(v)
    return f


# nom -> (description pour l'IA, arguments : (nom, vérificateur, obligatoire, défaut))
SPECS: dict[str, tuple[str, list[tuple]]] = {
    "volume_set": ('volume Windows à un niveau précis : {"value": 0-100}', [("value", _int(0, 100), True, None)]),
    "volume_rel": ('monter/baisser le volume : {"direction": 1 ou -1, "amount": nombre ou null}',
                   [("direction", _dir, True, None), ("amount", _opt_int, False, None)]),
    "volume_mute": ('couper/remettre le son : {"mute": true|false}', [("mute", _bool, True, None)]),
    "volume_get": ("dire le volume actuel", []),
    "media": ('contrôle média : {"action": "playpause"|"next"|"prev"}', [("action", _enum("playpause", "next", "prev"), True, None)]),
    "music": ('jouer un titre/artiste/playlist : {"query": "titre et artiste", "playlist": nom ou null, '
              '"radio": true si seulement un artiste, "provider": "spotify"|"youtube"|null}',
              [("query", _opt_str, False, None), ("playlist", _opt_str, False, None), ("radio", _bool, False, False),
               ("provider", _opt_enum("spotify", "youtube", "ytmusic"), False, None)]),
    "open_app": ('lancer un programme ou un jeu : {"name": "nom"}', [("name", _str, True, None)]),
    "close_app": ('fermer un programme : {"name": "nom", "force": false}', [("name", _str, True, None), ("force", _bool, False, False)]),
    "open_path": ('ouvrir un dossier ou un fichier du PC : {"kind": "dossier"|"fichier"|"pdf"|"photo"|"image"|"video"|null, "query": "nom"}',
                  [("kind", _opt_str, False, None), ("query", _str, True, None)]),
    "window_close": ("fermer la fenêtre active", []),
    "tab_close": ("fermer l'onglet actif", []),
    "window_switch": ("passer à l'autre fenêtre (Alt+Tab)", []),
    "desktop": ("afficher le bureau", []),
    "sleep": ("mettre le PC en veille", []),
    "lock": ("verrouiller la session", []),
    "screenshot": ("capture d'écran", []),
    "brightness_set": ('luminosité de l\'écran : {"value": 0-100}', [("value", _int(0, 100), True, None)]),
    "brightness_rel": ('luminosité +/- : {"direction": 1 ou -1, "amount": nombre ou null}',
                       [("direction", _dir, True, None), ("amount", _opt_int, False, None)]),
    "brightness_get": ("dire la luminosité", []),
    "timer_set": ('minuteur : {"seconds": durée en secondes, "label": nom ou null}',
                  [("seconds", _int(1, 86400), True, None), ("label", _opt_str, False, None)]),
    "timer_get": ("temps restant du minuteur", []),
    "timer_cancel": ("annuler les minuteurs", []),
    "weather": ('météo : {"when": "today"|"tomorrow", "city": ville ou null}',
                [("when", _enum("today", "tomorrow"), False, "today"), ("city", _opt_str, False, None)]),
    "web": ('recherche web dans le navigateur : {"query": "mots"}', [("query", _str, True, None), ("engine", _opt_str, False, None)]),
    "discord_mute": ('micro Discord : {"mute": true|false}', [("mute", _bool, True, None)]),
    "discord_toggle": ("basculer le micro Discord", []),
    "discord_deafen": ('sourdine Discord : {"on": true|false}', [("on", _bool, True, None)]),
    "discord_leave": ("quitter le salon vocal Discord", []),
    "focus_window": ('passer à une fenêtre DÉJÀ ouverte : {"title": "nom de l\'appli ou de la page"}', [("title", _str, True, None)]),
    "press_keys": ('raccourci clavier dans la fenêtre active : {"keys": "ctrl+t"} — autorisés : ctrl+t (nouvel onglet), ctrl+l (barre d\'adresse), '
                   'ctrl+f, ctrl+a/c/v/x/z, ctrl+s, enter, esc, tab, flèches, pageup/pagedown, f5, f11, alt+left/right', [("keys", _str, True, None)]),
    "type_text": ('taper du texte dans la fenêtre active (champ de saisie, barre de recherche) : {"text": "texte"}', [("text", _text, True, None)]),
    "ui_click": ('cliquer sur un bouton/lien/onglet visible de la fenêtre active : {"label": "texte exact du bouton"}', [("label", _str, True, None)]),
    "open_url": ('ouvrir un site web : {"url": "youtube.com"}', [("url", _str, True, None)]),
    "scroll": ('faire défiler la page : {"direction": "down"|"up"|"top"|"bottom"}', [("direction", _enum("down", "up", "top", "bottom"), True, None)]),
    "wait": ('attendre entre deux étapes (page qui charge) : {"seconds": 1 à 5}', [("seconds", _int(1, 5), True, None)]),
    "time": ("dire l'heure", []),
    "date": ("dire la date", []),
}
INFO_INTENTS = {"time", "date", "volume_get", "brightness_get", "timer_get", "weather"}
TRUTH_INTENTS = INFO_INTENTS | {"music", "open_app", "close_app", "open_path", "screenshot", "web", "timer_set", "open_url"}

# Actions sensibles : l'IA ne peut les déclencher que si la phrase de l'utilisateur les évoque vraiment.
GUARDS = {
    "sleep": r"veille|hibern",
    "lock": r"verrouill|bloqu|lock",
    "close_app": r"ferm|quitt|arret|stop|termin|tue|kill|coup|etein|clos|en finir",
    "window_close": r"ferm|quitt|arret|stop|termin|clos",
    "tab_close": r"ferm|quitt|arret|stop|termin|clos",
    "discord_leave": r"quitt|deconnect|sors|raccroch|part|leave",
}


def check_action(name: str, args, user_norm: str) -> Intent | None:
    """Vérifie une action proposée par l'IA. None = refusée (inconnue, mal formée ou non justifiée)."""
    spec = SPECS.get(name)
    if spec is None:
        log.warning("action inconnue proposée par l'IA : %r", name)
        return None
    if not isinstance(args, dict):
        args = {}
    clean: dict = {}
    try:
        for arg, validator, required, default in spec[1]:
            if arg in args and args[arg] is not None:
                clean[arg] = validator(args[arg])
            elif required:
                raise ValueError(f"argument manquant : {arg}")
            else:
                clean[arg] = default
    except (ValueError, TypeError) as exc:
        log.warning("arguments refusés pour %s : %s", name, exc)
        return None
    if name == "ui_click":                                       # le bouton doit avoir été nommé par l'utilisateur
        toks = [t for t in normalize(clean["label"]).split() if len(t) >= 3]
        if toks and not any(t[:5] in user_norm for t in toks):
            log.warning("ui_click refusé : « %s » n'a pas été demandé (%r)", clean["label"], user_norm)
            return None
    if name == "press_keys" and "enter" in clean["keys"].lower() and not re.search(
            r"entree|valid|envoi|envoy|cherch|recherch|lance la|confirm|soumet|\bgo\b|\bok\b", user_norm):
        log.warning("touche Entrée refusée : non demandée (%r)", user_norm)
        return None
    guard = GUARDS.get(name)
    if guard and not re.search(guard, user_norm):
        log.warning("action sensible %s refusée : la phrase ne la demande pas (%r)", name, user_norm)
        return None
    return Intent(name, clean)


# --------------------------------------------------------------------------- #
def extract_json(text: str) -> dict | None:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    blob = text[start:end + 1]
    for candidate in (blob, re.sub(r",\s*([}\]])", r"\1", blob)):
        try:
            data = json.loads(candidate)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            continue
    return None


def clean_say(text: str, limit: int = 500) -> str:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    text = re.sub(r"[*_`#]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        cut = text.rfind(". ", 0, limit)
        text = text[:cut + 1] if cut > 80 else text[:limit].rsplit(" ", 1)[0] + "…"
    return text


class Brain:
    def __init__(self, cfg, app_names: Callable[[], list[str]] | None = None) -> None:
        self.cfg = cfg
        self.app_names = app_names or (lambda: [])
        self.context: Callable[[], str] = lambda: ""                # fenêtre active (fournie par l'assistant)
        self.learned: Callable[[str], str] = lambda text: ""        # corrections apprises (fournies par l'assistant)
        self.memory: deque[dict] = deque(maxlen=MEMORY_TURNS * 2)
        self._last_use = 0.0
        self._status: dict | None = None
        self._status_at = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ connexion
    @property
    def enabled(self) -> bool:
        return bool(self.cfg["brain_enabled"])

    def _base(self) -> str:
        return (self.cfg["brain_url"] or "http://127.0.0.1:11434").rstrip("/")

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.cfg["brain_api_key"]:
            h["Authorization"] = "Bearer " + self.cfg["brain_api_key"]
        return h

    def _request(self, path: str, body: dict | None = None, timeout: float = 60) -> dict:
        req = urllib.request.Request(self._base() + path, data=json.dumps(body).encode("utf-8") if body is not None else None,
                                     headers=self._headers(), method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise BrainError(f"HTTP {exc.code} : {exc.read().decode('utf-8', 'ignore')[:150]}") from exc
        except Exception as exc:
            raise BrainError(str(exc)) from exc

    def _anthropic(self, system: str, convo: list[dict], model: str, max_tokens: int = 700, timeout: float = 40) -> str:
        """API Anthropic (Claude) : clé personnelle de l'utilisateur, paiement à l'usage chez Anthropic."""
        body = {"model": model, "max_tokens": max_tokens, "temperature": 0.2, "system": system, "messages": convo}
        req = urllib.request.Request(ANTHROPIC_URL, data=json.dumps(body).encode("utf-8"), method="POST", headers={
            "x-api-key": (self.cfg["brain_api_key"] or "").strip(), "anthropic-version": "2023-06-01",
            "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")[:200]
            hint = {401: "clé API invalide", 403: "accès refusé", 429: "trop de requêtes ou crédit épuisé",
                    529: "service surchargé"}.get(exc.code, "")
            raise BrainError(f"Claude : HTTP {exc.code} {hint} {detail}".strip()) from exc
        except Exception as exc:
            raise BrainError(f"Claude : {exc}") from exc
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")

    def list_models(self) -> list[str]:
        if self.cfg["brain_backend"] == "anthropic":
            return list(ANTHROPIC_MODELS)
        if self.cfg["brain_backend"] == "openai":
            data = self._request("/v1/models", timeout=4)
            names = [m.get("id", "") for m in data.get("data", [])]
        else:
            data = self._request("/api/tags", timeout=4)
            names = [m.get("name", "") for m in data.get("models", [])]
        return [n for n in names if n and "embed" not in n.lower()]

    def pick_model(self, models: list[str]) -> str:
        wanted = (self.cfg["brain_model"] or "").strip()
        if self.cfg["brain_backend"] == "anthropic":
            return wanted if wanted.startswith("claude") else ANTHROPIC_MODELS[0]
        if wanted:
            return wanted
        for pref in PREFERRED:
            for m in models:
                if pref in m.lower():
                    return m
        return models[0] if models else ""

    def status(self, force: bool = False, verify: bool = False) -> dict:
        """{'ok': bool, 'model': str, 'models': [...], 'message': str} (mis en cache 20 s).
        `verify` : pour Claude, fait un vrai mini-appel (quelques jetons) au lieu de seulement vérifier qu'une clé existe."""
        with self._lock:
            if self._status and not force and time.time() - self._status_at < 20:
                return self._status
        if self.cfg["brain_backend"] == "anthropic":
            model = self.pick_model([])
            if not (self.cfg["brain_api_key"] or "").strip():
                st = {"ok": False, "model": model, "models": list(ANTHROPIC_MODELS), "message": "Colle ta clé API Anthropic pour activer Claude."}
            else:
                st = {"ok": True, "model": model, "models": list(ANTHROPIC_MODELS), "message": f"Clé enregistrée · modèle {model}"}
                if verify:
                    try:
                        self._anthropic("Réponds OK.", [{"role": "user", "content": "test"}], model, max_tokens=8, timeout=15)
                        st["message"] = f"Connecté à Claude · modèle {model}"
                    except BrainError as exc:
                        st = {"ok": False, "model": model, "models": list(ANTHROPIC_MODELS), "message": str(exc)[:140]}
            with self._lock:
                self._status, self._status_at = st, time.time()
            return st
        try:
            models = self.list_models()
            model = self.pick_model(models)
            if not models and not self.cfg["brain_model"]:
                st = {"ok": False, "model": "", "models": [], "message": "Connecté, mais aucun modèle installé. Lance : ollama pull qwen2.5:7b"}
            else:
                st = {"ok": True, "model": model, "models": models, "message": f"Connecté · modèle {model}"}
        except BrainError as exc:
            log.debug("cerveau IA injoignable : %s", exc)
            st = {"ok": False, "model": "", "models": [], "message": "Ollama n'est pas lancé (ou pas installé)."}
        with self._lock:
            self._status, self._status_at = st, time.time()
        return st

    def available(self) -> bool:
        return self.enabled and self.status()["ok"]

    def find_ollama(self) -> str | None:
        """Chemin de l'exécutable Ollama, si on le trouve dans son dossier d'installation habituel."""
        import os
        import shutil

        found = shutil.which("ollama")
        if found:
            return found
        local = os.environ.get("LOCALAPPDATA")
        if local:
            path = os.path.join(local, "Programs", "Ollama", "ollama.exe")
            if os.path.exists(path):
                return path
        return None

    def launch_local(self) -> bool:
        """Lance Ollama en tâche de fond s'il est installé. Retourne False si introuvable."""
        exe = self.find_ollama()
        if not exe:
            return False
        import subprocess
        import sys

        try:
            flags = 0x08000000 if sys.platform == "win32" else 0     # CREATE_NO_WINDOW
            subprocess.Popen([exe, "serve"], creationflags=flags, close_fds=True)
        except Exception:
            log.exception("lancement d'Ollama impossible")
            return False
        return True

    # ------------------------------------------------------------------ prompt
    def system_prompt(self, user_text: str = "") -> str:
        c = self.cfg
        now = datetime.datetime.now()
        name = (c["user_name"] or "").strip()
        style = {
            "jarvis": "Tu vouvoies l'utilisateur, avec l'élégance calme d'un majordome (style Jarvis).",
            "cool": "Tu tutoies l'utilisateur, ton décontracté et chaleureux, un peu d'humour.",
            "court": "Tu réponds de façon ultra brève, sans fioritures.",
        }.get(c["reply_style"], "Tu vouvoies l'utilisateur.")
        actions = "\n".join(f"- {n} : {d}" for n, (d, _) in SPECS.items())
        apps = ", ".join(self.app_names()[:120])
        try:
            window = self.context()
        except Exception:
            window = ''
        return (
            f"Tu es {(c['assistant_name'] or c['wake_word'] or 'Sentinel').strip().capitalize()}, l'assistant vocal personnel de {name or 'l’utilisateur'} sur son PC Windows. "
            f"Nous sommes {DAYS[now.weekday()]} {now.day} {MONTHS[now.month - 1]} {now.year}, il est {now.hour} h {now.minute:02d}. "
            f"{style} Ta réponse est LUE À VOIX HAUTE : phrases courtes et naturelles (1 à 3 maximum), en français, "
            "sans liste, sans émoji, sans markdown, sans lien.\n\n"
            "Tu peux agir sur le PC avec ces ACTIONS (et uniquement celles-ci) :\n" + actions + "\n\n"
            "Tu réponds TOUJOURS par un seul objet JSON : {\"actions\": [ {\"intent\": \"nom\", \"args\": {…}} ], \"say\": \"phrase\"}.\n"
            "Règles :\n"
            "1. Si l'utilisateur demande quelque chose que tu peux faire avec une action, mets-la dans \"actions\" et une courte "
            "confirmation naturelle dans \"say\". Plusieurs actions possibles, dans l'ordre demandé.\n"
            "2. Si l'utilisateur pose une question, discute, demande un avis, une blague, une explication : \"actions\" est vide "
            "et tu réponds directement dans \"say\" avec tes connaissances.\n"
            "3. N'exécute JAMAIS d'action qui n'est pas clairement demandée. Si c'est ambigu (ex. « je vais me coucher »), "
            "propose dans \"say\" et attends la réponse.\n"
            "4. Pour l'heure, la date, la météo, le volume, la luminosité ou les minuteurs, utilise l'action correspondante "
            "(tu ne connais pas ces valeurs) et laisse \"say\" vide.\n"
            "5. Pour la musique : \"query\" contient titre et artiste tels que dits (« Life Damso »). Si seulement un artiste "
            "est cité, mets \"radio\": true. Mets \"provider\": \"spotify\" seulement si l'utilisateur le demande.\n"
            "6. Si tu ne sais pas ou ne peux pas faire, dis-le honnêtement et brièvement.\n"
            + "7. Pour agir DANS une application ou un site : focus_window (si tu dois changer de fenêtre), puis press_keys / "
              "type_text / ui_click, avec wait entre deux étapes si une page doit charger. Chaque étape est exécutée dans l'ordre "
              "et le plan s'arrête à la première qui échoue. Ne tape jamais dans un terminal. Pour une simple recherche web, "
              "préfère l'action web.\n"
            + (f"\nApplications et jeux installés (extrait) : {apps}.\n" if apps else "")
            + (f"Fenêtre active en ce moment : {window}.\n" if window else "")
            + self.learned(user_text)
            + "\nExemples :\n"
            "Utilisateur : « mets un peu moins fort »\n"
            "{\"actions\":[{\"intent\":\"volume_rel\",\"args\":{\"direction\":-1,\"amount\":null}}],\"say\":\"Voilà, un peu moins fort.\"}\n"
            "Utilisateur : « lance Djadja d'Aya Nakamura sur Spotify »\n"
            "{\"actions\":[{\"intent\":\"music\",\"args\":{\"query\":\"Djadja Aya Nakamura\",\"radio\":false,\"provider\":\"spotify\"}}],\"say\":\"C'est parti.\"}\n"
            "Utilisateur : « dans dix minutes rappelle-moi de sortir le linge »\n"
            "{\"actions\":[{\"intent\":\"timer_set\",\"args\":{\"seconds\":600,\"label\":\"sortir le linge\"}}],\"say\":\"Entendu, dans dix minutes.\"}\n"
            "Utilisateur : « il pleut demain à Lille ? »\n"
            "{\"actions\":[{\"intent\":\"weather\",\"args\":{\"when\":\"tomorrow\",\"city\":\"Lille\"}}],\"say\":\"\"}\n"
            "Utilisateur : « sur YouTube, cherche des vidéos de chats »\n"
            "{\"actions\":[{\"intent\":\"web\",\"args\":{\"query\":\"vidéos de chats\",\"engine\":\"youtube\"}}],\"say\":\"\"}\n"
            "Utilisateur : « dans Chrome, va sur wikipedia.org et cherche Einstein »\n"
            "{\"actions\":[{\"intent\":\"focus_window\",\"args\":{\"title\":\"Chrome\"}},{\"intent\":\"open_url\",\"args\":{\"url\":\"wikipedia.org\"}},"
            "{\"intent\":\"wait\",\"args\":{\"seconds\":3}},{\"intent\":\"web\",\"args\":{\"query\":\"Einstein wikipedia\"}}],\"say\":\"C\'est fait.\"}\n"
            "Utilisateur : « clique sur Se connecter »\n"
            "{\"actions\":[{\"intent\":\"ui_click\",\"args\":{\"label\":\"Se connecter\"}}],\"say\":\"\"}\n"
            "Utilisateur : « ouvre un nouvel onglet et écris météo lille »\n"
            "{\"actions\":[{\"intent\":\"press_keys\",\"args\":{\"keys\":\"ctrl+t\"}},{\"intent\":\"wait\",\"args\":{\"seconds\":1}},"
            "{\"intent\":\"type_text\",\"args\":{\"text\":\"météo lille\"}},{\"intent\":\"press_keys\",\"args\":{\"keys\":\"enter\"}}],\"say\":\"Voilà.\"}\n"
            "Utilisateur : « raconte-moi une blague »\n"
            "{\"actions\":[],\"say\":\"Pourquoi les plongeurs plongent-ils toujours en arrière ? Parce que sinon ils tombent dans le bateau.\"}\n"
            "Utilisateur : « je vais me coucher »\n"
            "{\"actions\":[],\"say\":\"Bonne nuit ! Voulez-vous que je mette le PC en veille ?\"}"
        )

    # ------------------------------------------------------------------ appel du modèle en flux (réponse plus rapide)
    def can_stream(self) -> bool:
        return bool(self.cfg["brain_stream"]) and self.cfg["brain_backend"] in ("ollama", "openai", "anthropic")

    def _stream_lines(self, path: str, body: dict, timeout: float = 90):
        """Ouvre une requête en flux et donne les lignes brutes au fur et à mesure qu'elles arrivent."""
        req = urllib.request.Request(self._base() + path, data=json.dumps(body).encode("utf-8"),
                                     headers=self._headers(), method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", "ignore").strip()
                if line:
                    yield line

    def _chat_stream(self, messages: list[dict], on_text: Callable[[str], None]) -> str:
        """Comme _chat, mais appelle on_text(morceau) au fil de l'eau. Retourne le texte JSON complet."""
        model = self.pick_model(self.status()["models"])
        if not model:
            raise BrainError("aucun modèle")
        full = []
        try:
            if self.cfg["brain_backend"] == "anthropic":
                body = {"model": model, "max_tokens": 700, "temperature": 0.2, "system": messages[0]["content"],
                        "messages": messages[1:], "stream": True}
                req = urllib.request.Request(ANTHROPIC_URL, data=json.dumps(body).encode("utf-8"), method="POST",
                                             headers={"x-api-key": (self.cfg["brain_api_key"] or "").strip(),
                                                      "anthropic-version": "2023-06-01", "content-type": "application/json"})
                with urllib.request.urlopen(req, timeout=90) as resp:
                    for raw_line in resp:
                        line = raw_line.decode("utf-8", "ignore")
                        if not line.startswith("data: "):
                            continue
                        try:
                            ev = json.loads(line[6:])
                        except json.JSONDecodeError:
                            continue
                        if ev.get("type") == "content_block_delta":
                            piece = ev.get("delta", {}).get("text", "")
                            full.append(piece)
                            on_text(piece)
            elif self.cfg["brain_backend"] == "openai":
                for line in self._stream_lines("/v1/chat/completions", {
                        "model": model, "messages": messages, "temperature": 0.2, "max_tokens": 450, "stream": True,
                        "response_format": {"type": "json_object"}}):
                    if not line.startswith("data: ") or line.strip() == "data: [DONE]":
                        continue
                    try:
                        piece = json.loads(line[6:])["choices"][0]["delta"].get("content", "")
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    full.append(piece)
                    on_text(piece)
            else:
                for line in self._stream_lines("/api/chat", {
                        "model": model, "messages": messages, "stream": True, "format": "json", "think": False,
                        "keep_alive": "30m", "options": {"temperature": 0.2, "num_predict": 450, "num_ctx": 4096}}):
                    try:
                        piece = json.loads(line).get("message", {}).get("content", "")
                    except json.JSONDecodeError:
                        continue
                    full.append(piece)
                    on_text(piece)
        except urllib.error.HTTPError as exc:
            raise BrainError(f"HTTP {exc.code}") from exc
        except Exception as exc:
            raise BrainError(str(exc)) from exc
        return "".join(full)

    def _chat(self, messages: list[dict]) -> str:
        model = self.pick_model(self.status()["models"])
        if not model:
            raise BrainError("aucun modèle")
        if self.cfg["brain_backend"] == "anthropic":
            return self._anthropic(messages[0]["content"], messages[1:], model)
        if self.cfg["brain_backend"] == "openai":
            data = self._request("/v1/chat/completions", {
                "model": model, "messages": messages, "temperature": 0.2, "max_tokens": 450,
                "response_format": {"type": "json_object"}}, timeout=90)
            return data["choices"][0]["message"]["content"]
        data = self._request("/api/chat", {
            "model": model, "messages": messages, "stream": False, "format": "json", "think": False, "keep_alive": "30m",
            "options": {"temperature": 0.2, "num_predict": 450, "num_ctx": 4096}}, timeout=90)
        return data["message"]["content"]

    def ask(self, text: str, on_speak: Callable[[str], None] | None = None) -> BrainResult:
        """Envoie la phrase au modèle. Lève BrainError si le cerveau est indisponible.
        Avec `on_speak`, et si la réponse est une simple discussion (aucune action), Sentinel reçoit le
        texte au fur et à mesure qu'il arrive, pour commencer à le dire sans attendre la fin — jamais
        pendant qu'une action doit encore s'exécuter, voir say_stream.py."""
        if not self.enabled:
            raise BrainError("désactivé")
        if time.time() - self._last_use > MEMORY_EXPIRE:
            self.memory.clear()
        messages = [{"role": "system", "content": self.system_prompt(text)}, *self.memory, {"role": "user", "content": text}]
        try:
            if on_speak is not None and self.can_stream():
                streamer = SayStreamer()
                raw = self._chat_stream(messages, lambda piece: on_speak(streamer.feed(piece)))
            else:
                raw = self._chat(messages)
        except BrainError:
            self.status(force=True)                              # rafraîchit l'état affiché
            raise
        self._last_use = time.time()
        result = self.parse(raw, normalize(text))
        self.memory.append({"role": "user", "content": text})
        self.memory.append({"role": "assistant", "content": json.dumps(
            {"actions": [{"intent": a.name, "args": a.args} for a in result.actions], "say": result.say}, ensure_ascii=False)})
        return result

    def parse(self, raw: str, user_norm: str) -> BrainResult:
        data = extract_json(raw)
        if data is None:                                         # le modèle a répondu en texte libre : on le dit tel quel
            return BrainResult(say=clean_say(raw))
        actions: list[Intent] = []
        refused = False
        for item in (data.get("actions") or [])[:MAX_ACTIONS]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("intent", "")).strip()
            it = check_action(name, item.get("args"), user_norm)
            if it is None:
                refused = refused or (name in GUARDS)             # sensible et non demandée ; les actions inventées sont ignorées
            else:
                actions.append(it)
        say = clean_say(str(data.get("say") or ""))
        return BrainResult(actions=actions, say=say, refused=refused and not actions)

    def forget(self) -> None:
        self.memory.clear()
