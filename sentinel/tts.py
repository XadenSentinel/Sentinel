"""Synthèse vocale de Sentinel.

Deux moteurs, choisis automatiquement :
  1. « edge »  : voix neuronales de Microsoft Edge (gratuites, sans clé, connexion Internet requise).
                 Beaucoup plus naturelles que la voix Windows. Voix par défaut : Henri (masculine).
  2. « sapi »  : voix Windows installées (hors-ligne), utilisées si Internet ou `edge-tts` manque.

Pour que ça reste fluide :
  - les phrases longues sont découpées et la phrase suivante est fabriquée pendant qu'on lit la précédente ;
  - chaque phrase fabriquée est gardée en cache (%APPDATA%\\Sentinel\\tts_cache) : les réponses
    habituelles (« Oui ? », « Je t'écoute ») sont instantanées ;
  - le texte est nettoyé avant lecture (pas de « % », d'émojis, de markdown, d'URL lues à voix haute).
"""
from __future__ import annotations

import asyncio
import ctypes
import hashlib
import itertools
import logging
import os
import queue
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from .config import data_dir

log = logging.getLogger("sentinel.tts")

# nom technique -> libellé affiché dans les paramètres
EDGE_VOICES = {
    "fr-FR-HenriNeural": "Henri — homme (recommandée)",
    "fr-FR-RemyMultilingualNeural": "Rémy — homme, multilingue",
    "fr-FR-DeniseNeural": "Denise — femme",
    "fr-FR-EloiseNeural": "Éloïse — femme",
    "fr-FR-VivienneMultilingualNeural": "Vivienne — femme, multilingue",
}
MALE_HINTS = ("paul", "henri", "remy", "claude", "nicolas", "guillaume", "antoine", "thomas", "jean")
CACHE_MAX_FILES = 400


# --------------------------------------------------------------------------- #
# Nettoyage / découpage du texte
# --------------------------------------------------------------------------- #
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200d]")


def clean_for_speech(text: str) -> str:
    text = re.sub(r"https?://\S+", " un lien ", text)
    text = _EMOJI.sub("", text)
    text = re.sub(r"[*_`#>~|]+", " ", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    text = text.replace("°C", " degrés").replace("°", " degrés").replace("%", " pour cent")
    text = text.replace("&", " et ").replace("=", " égale ").replace("/", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def split_sentences(text: str, max_len: int = 220) -> list[str]:
    """Coupe aux fins de phrase ; regroupe les très courts morceaux ; coupe aux virgules si trop long."""
    raw = [p.strip() for p in re.split(r"(?<=[.!?…])\s+", text) if p.strip()]
    out: list[str] = []
    for part in raw:
        while len(part) > max_len:
            cut = part.rfind(",", 0, max_len)
            cut = cut if cut > 40 else part.rfind(" ", 0, max_len)
            cut = cut if cut > 0 else max_len
            out.append(part[:cut + 1].strip())
            part = part[cut + 1:].strip()
        if part:
            out.append(part)
    merged: list[str] = []
    for part in out:
        if merged and (len(merged[-1]) < 25 or len(part) < 12):
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    return merged


# --------------------------------------------------------------------------- #
# Lecture MP3 sans dépendance (MCI de Windows)
# --------------------------------------------------------------------------- #
_alias_counter = itertools.count(1)


def play_mp3(path: Path, volume_pct: int, should_stop: Callable[[], bool] = lambda: False) -> None:
    winmm = ctypes.windll.winmm                    # (ne s'exécute que sous Windows)
    alias = f"sentinel{next(_alias_counter)}"
    buf = ctypes.create_unicode_buffer(64)

    def send(cmd: str) -> int:
        return winmm.mciSendStringW(cmd, buf, len(buf), 0)

    if send(f'open "{path}" type mpegvideo alias {alias}') != 0:
        raise OSError(f"MCI : impossible d'ouvrir {path}")
    try:
        send(f"setaudio {alias} volume to {max(0, min(100, int(volume_pct))) * 10}")
        send(f"play {alias}")
        time.sleep(0.05)
        while True:
            send(f"status {alias} mode")
            if buf.value != "playing" or should_stop():
                break
            time.sleep(0.04)
        if should_stop():
            send(f"stop {alias}")
    finally:
        send(f"close {alias}")


# --------------------------------------------------------------------------- #
class Speaker(threading.Thread):
    """Parle dans son propre thread. `busy` reste levé pendant qu'il parle
    (le micro est alors ignoré pour ne pas s'entendre lui-même)."""

    def __init__(self, cfg, on_state: Callable[[str], None]) -> None:
        super().__init__(daemon=True, name="sentinel-tts")
        self.cfg = cfg
        self.on_state = on_state
        self.busy = threading.Event()
        self.available = True
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts-synth")
        self._warm = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts-warm")
        self._edge_down_until = 0.0
        self._sapi = None
        self._cache = data_dir() / "tts_cache"
        self._interrupt = threading.Event()     # coupe la lecture en cours (interruption vocale)

    # ------------------------------------------------------------------ API
    def say(self, text: str, force: bool = False) -> None:
        """`force` outrepasse le mode silencieux (utilisé pour confirmer qu'on vient de l'activer/désactiver)."""
        if text and self.available and self.cfg["tts_enabled"] and (force or not self.cfg["dnd"]):
            self.busy.set()
            self._queue.put(text)

    def interrupt(self) -> None:
        """Coupe net ce qui est en train d'être dit et vide la file (l'utilisateur a parlé par-dessus)."""
        with self._queue.mutex:
            self._queue.queue.clear()
        self._interrupt.set()

    def shutdown(self) -> None:
        self._queue.put(None)

    def prewarm(self, texts: list[str]) -> None:
        """Fabrique en tâche de fond les phrases habituelles pour qu'elles partent sans délai."""
        if self._engine() != "edge":
            return

        def work() -> None:
            for text in texts:
                for part in split_sentences(clean_for_speech(text)):
                    try:
                        self._synth_edge(part)
                    except Exception:
                        log.debug("préchauffage échoué", exc_info=True)
                        return

        self._warm.submit(work)

    # ------------------------------------------------------------------ moteurs
    def _engine(self) -> str:
        mode = (self.cfg["tts_engine"] or "auto").lower()
        if mode == "sapi" or time.time() < self._edge_down_until:
            return "sapi"
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            return "sapi"
        return "edge"

    def _edge_params(self) -> tuple[str, str, str]:
        voice = self.cfg["tts_edge_voice"] or "fr-FR-HenriNeural"
        rate = max(-50, min(50, int(self.cfg["tts_rate"]) * 5))
        pitch = max(-20, min(20, int(self.cfg["tts_pitch"])))
        return voice, f"{rate:+d}%", f"{pitch:+d}Hz"

    def _synth_edge(self, text: str) -> Path:
        voice, rate, pitch = self._edge_params()
        key = hashlib.sha1(f"{voice}|{rate}|{pitch}|{text}".encode("utf-8")).hexdigest()
        out = self._cache / f"{key}.mp3"
        if out.exists() and out.stat().st_size > 0:
            os.utime(out, None)
            return out
        import edge_tts

        self._cache.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".part")

        async def go() -> None:
            comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
            await asyncio.wait_for(comm.save(str(tmp)), timeout=12)

        asyncio.run(go())
        if not tmp.exists() or tmp.stat().st_size == 0:
            raise RuntimeError("edge-tts n'a renvoyé aucun son")
        os.replace(tmp, out)
        return out

    def _trim_cache(self) -> None:
        try:
            files = sorted(self._cache.glob("*.mp3"), key=lambda p: p.stat().st_mtime)
            for old in files[:-CACHE_MAX_FILES]:
                old.unlink(missing_ok=True)
        except Exception:
            log.debug("nettoyage du cache impossible", exc_info=True)

    def _play(self, path: Path) -> None:
        play_mp3(path, int(self.cfg["tts_volume"]), should_stop=self._interrupt.is_set)

    # --- voix Windows (repli hors-ligne) ---
    def _pick_sapi_voice(self, voice) -> None:
        wanted = (self.cfg["tts_voice"] or "").strip()
        tokens = voice.GetVoices()
        chosen, male, french = None, None, None
        for i in range(tokens.Count):
            tok = tokens.Item(i)
            desc = tok.GetDescription()
            low = desc.lower()
            if wanted and desc == wanted:
                chosen = tok
                break
            is_fr = any(k in low for k in ("french", "français", "francais", "fr-fr", "fr-ca", "hortense", "julie", "paul"))
            if is_fr and french is None:
                french = tok
            if is_fr and male is None and any(h in low for h in MALE_HINTS):
                male = tok
        if chosen is None:
            chosen = (male or french) if self.cfg["tts_gender"] == "male" else (french or male)
        if chosen is not None:
            voice.Voice = chosen

    def _speak_sapi(self, text: str) -> None:
        if self._sapi is None:
            import win32com.client
            self._sapi = win32com.client.Dispatch("SAPI.SpVoice")
        v = self._sapi
        v.Rate = max(-10, min(10, int(self.cfg["tts_rate"])))
        v.Volume = max(0, min(100, int(self.cfg["tts_volume"])))
        self._pick_sapi_voice(v)
        v.Speak(text, 1)                                 # 1 = SVSFlagsAsync : on peut l'interrompre
        while v.Status.RunningState == 2:                # 2 = en cours de lecture
            if self._interrupt.is_set():
                v.Speak("", 2)                            # 2 = SVSFPurgeBeforeSpeak : stoppe net
                return
            time.sleep(0.05)

    # ------------------------------------------------------------------ lecture
    def _speak(self, text: str) -> None:
        text = clean_for_speech(text)
        if not text:
            return
        parts = split_sentences(text)
        if self._engine() == "edge":
            futures = [self._pool.submit(self._synth_edge, p) for p in parts]    # fabriqué d'avance
            for i, fut in enumerate(futures):
                try:
                    path = fut.result(timeout=20)
                except Exception as exc:
                    log.warning("voix Edge indisponible (%s) : repli sur la voix Windows pendant 2 minutes", exc)
                    self._edge_down_until = time.time() + 120
                    for f in futures[i:]:
                        f.cancel()
                    self.on_state("speaking")
                    self._speak_sapi(" ".join(parts[i:]))
                    return
                if i == 0:
                    self.on_state("speaking")
                self._play(path)
                if self._interrupt.is_set():
                    break
        else:
            self.on_state("speaking")
            self._speak_sapi(text)

    def run(self) -> None:
        com = None
        try:
            import pythoncom
            pythoncom.CoInitialize()
            com = pythoncom
        except Exception:
            log.info("COM indisponible : pas de voix Windows de repli")
        self._trim_cache()
        try:
            while True:
                text = self._queue.get()
                if text is None:
                    break
                self.busy.set()
                self._interrupt.clear()
                try:
                    self._speak(text)
                except Exception:
                    log.exception("erreur de synthèse vocale")
                finally:
                    if self._queue.empty():
                        time.sleep(0.35)                # laisse mourir l'écho de la pièce
                        self.busy.clear()
                        self.on_state("rest")
        finally:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._warm.shutdown(wait=False, cancel_futures=True)
            if com is not None:
                com.CoUninitialize()
