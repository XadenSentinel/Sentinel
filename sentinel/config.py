"""Configuration persistante et chemins (compatibles PyInstaller)."""
from __future__ import annotations


def _permissions_defaults() -> dict:
    from .permissions import DEFAULTS
    return DEFAULTS

import copy
import json
import logging
import os
import sys
import threading
from pathlib import Path

APP_NAME = "Sentinel"
log = logging.getLogger("sentinel.config")


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def bundle_dir() -> Path:
    """Ressources embarquées dans l'exe (dossier temporaire _MEIPASS en --onefile)."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def exe_dir() -> Path:
    """Dossier contenant l'exe (ou le projet en mode développement)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """%APPDATA%\\Sentinel : config, logs, modèle vocal téléchargé."""
    base = os.environ.get("APPDATA") or str(Path.home())
    p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


DEFAULTS: dict = {
    # --- déclenchement ---
    "wake_word": "sentinel",
    "wake_aliases": ["sentinelle", "sentinal", "centinel", "santinel"],
    "listen_timeout": 7,          # secondes d'écoute après le mot déclencheur seul
    "mic_device": None,           # index sounddevice, None = micro par défaut
    "model_path": "",             # dossier du modèle Vosk (vide = détection auto)
    "show_heard": True,           # affiche tout ce qui est entendu dans le journal
    # --- voix ---
    "tts_enabled": True,
    "tts_voice": "",              # vide = première voix française trouvée
    "tts_rate": 1,                # -10 .. 10
    "tts_volume": 100,            # 0 .. 100
    # --- interface ---
    "accent": "Cyan",
    "custom_accent": "",          # couleur d'accent libre (#RRGGBB) : prioritaire sur « accent »
    "theme": "Abysse",            # voir ui/theme.py (redémarrage nécessaire)
    "custom_bg": "",              # couleur de fond libre (#RRGGBB, sombre) : prioritaire sur « theme »
    "hud_bg": "stars",            # stars | gradient | solid | minimal
    "hud_fx": True,               # balayage lumineux, télémétrie animée
    "assistant_name": "",         # nom affiché (vide = le mot déclencheur)
    "first_run_done": False,      # assistant de bienvenue déjà passé
    "ui": "web",                  # web (nouvelle interface) | classic (ancienne fenêtre)
    "sphere_density": 1400,       # nombre de particules de la sphère
    "skip_intro": False,          # passer directement à l'accueil, sans écran de démarrage
    "update_check": True,         # chercher une mise à jour au démarrage (au plus une fois par jour)
    "update_last_check": 0.0,
    "permissions": dict(_permissions_defaults()),   # familles d'actions activées / avec confirmation
    "dnd": False,                  # mode silencieux : n'exécute rien de moins, mais ne parle plus
    "wake_sound": True,            # petit bip quand Sentinel te reconnaît
    "barge_in": False,             # couper Sentinel si tu parles par-dessus (par défaut off : dépend du micro/HP)
    "brain_stream": True,          # commencer à parler dès la première phrase de l'IA, quand c'est possible
    "minimize_to_tray": True,
    "start_with_windows": False,
    # --- actions ---
    "volume_step": 10,
    "search_engine": "google",
    "music_provider": "youtube",  # youtube | ytmusic | spotify
    "music_radio": True,
    "playlists": {},              # "rap fr" -> lien YouTube / YouTube Music / Spotify
    "app_aliases": {},            # "fortnite" -> chemin, URL ou commande
    "corrections": {},            # "dans so" -> "damso" (mots mal compris)
    "shortcuts": {                # "mode jeu" -> "coupe le son ; lance fortnite" (macros vocales)
        "bonjour": "quelle heure est il ; quelle est la meteo",     # routine de base ; personnalisable
        "bonne nuit": "mets l'ordinateur en veille",
    },
    # --- personnalité ---
    "user_name": "",              # comment Sentinel t'appelle (vide = rien)
    "reply_style": "jarvis",      # jarvis | cool | court
    "custom_replies": {},         # clé de phrase -> ta phrase (voir page Réponses)
    # --- météo / luminosité / captures ---
    # --- reconnaissance vocale de précision (facultative : pip install faster-whisper) ---
    "asr_whisper": False,         # re-transcrire avec Whisper les phrases adressées à Sentinel
    "whisper_model": "small",     # base | small | medium
    # --- voix neuronale (Microsoft Edge, gratuite) avec repli sur la voix Windows ---
    "tts_engine": "auto",         # auto | edge | sapi
    "tts_edge_voice": "fr-FR-HenriNeural",
    "tts_pitch": 0,               # Hz, -20..+20
    "tts_gender": "male",         # voix Windows de repli : male | female
    # --- accès au PC ---
    "scan_full_disk": True,       # indexer les .exe de tous les disques (sinon : dossiers usuels)
    "scan_extra_paths": [],       # dossiers à ajouter à l'analyse
    "allow_scripts": False,       # autoriser « ouvre le fichier » sur .bat/.ps1/.vbs… (déconseillé)
    # --- cerveau IA (modèle local Ollama, gratuit) ---
    "brain_enabled": True,
    "brain_mode": "auto",         # auto : règles d'abord, IA si pas compris | always : IA pour tout
    "brain_backend": "ollama",    # ollama | openai (API compatible OpenAI : LM Studio, etc.)
    "brain_url": "http://127.0.0.1:11434",
    "brain_model": "",            # vide = choisi automatiquement parmi les modèles installés
    "brain_api_key": "",
    "follow_up": True,            # après une réponse de l'IA, écoute la suite sans mot déclencheur
    # --- Spotify (lecture directe : compte Premium requis par Spotify) ---
    "spotify_client_id": "",
    "weather_city": "",           # ville pour la météo (vide = météo désactivée)
    "brightness_step": 10,
    "screenshot_dir": "",         # vide = Images\\Sentinel
    "discord_keys": {
        "toggle_mute": "ctrl+alt+f9",
        "toggle_deafen": "ctrl+alt+f10",
        "leave_voice": "ctrl+alt+f11",
    },
}


class Config:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._path = data_dir() / "config.json"
        self._data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as f:
                stored = json.load(f)
        except FileNotFoundError:
            return
        except Exception:
            log.exception("config.json illisible, valeurs par défaut utilisées")
            return
        with self._lock:
            for key, value in stored.items():
                if key not in DEFAULTS:
                    continue
                if key == "discord_keys" and isinstance(value, dict):
                    self._data[key].update(value)
                else:
                    self._data[key] = value

    def save(self) -> None:
        with self._lock:
            tmp = self._path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)

    def __getitem__(self, key: str):
        with self._lock:
            return self._data[key]

    def __setitem__(self, key: str, value) -> None:
        with self._lock:
            self._data[key] = value


# Réglages partageables avec des amis (jamais de clés, de chemins ni d'identifiants)
PROFILE_KEYS = (
    "wake_word", "wake_aliases", "assistant_name", "user_name", "reply_style", "custom_replies", "shortcuts", "app_aliases",
    "corrections", "playlists", "accent", "custom_accent", "theme", "custom_bg", "hud_bg", "hud_fx", "weather_city",
    "tts_engine", "tts_edge_voice", "tts_pitch", "tts_rate", "tts_gender", "search_engine", "music_provider", "music_radio",
    "brain_mode", "follow_up", "volume_step", "brightness_step",
)


def export_profile(cfg: "Config", path) -> None:
    data = {k: cfg[k] for k in PROFILE_KEYS}
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"sentinel_profile": 1, "settings": data}, f, ensure_ascii=False, indent=2)


def import_profile(cfg: "Config", path) -> int:
    """Applique un profil exporté. Retourne le nombre de réglages importés (les clés inconnues sont ignorées)."""
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    return apply_profile(cfg, payload)


def apply_profile(cfg: "Config", payload) -> int:
    settings = payload.get("settings", {}) if isinstance(payload, dict) else {}
    count = 0
    for key in PROFILE_KEYS:
        if key in settings and type(settings[key]) is type(cfg[key]):
            cfg[key] = settings[key]
            count += 1
    cfg.save()
    return count
