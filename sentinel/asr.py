"""Reconnaissance vocale de précision (Whisper, via faster-whisper) — OPTIONNELLE.

Vosk écoute en continu (léger, hors-ligne) et repère le mot déclencheur. Quand une phrase s'adresse à
Sentinel, l'audio de cette phrase est re-transcrit par Whisper, nettement plus fiable en français :
c'est ce texte-là qui devient la commande. Si Whisper est absent, en échec ou ne renvoie rien,
Sentinel garde le texte de Vosk : rien ne casse.

Installation : `pip install faster-whisper`. Au premier lancement le modèle est téléchargé une fois
(« small » ≈ 480 Mo, « medium » ≈ 1,5 Go) dans %APPDATA%\\Sentinel\\whisper. Calcul sur le processeur.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from typing import Callable

from .config import data_dir

log = logging.getLogger("sentinel.asr")

MIN_SAMPLES = 6400                 # 0,4 s : en dessous, ce n'est pas une phrase
MAX_SECONDS = 20
# Phrases que Whisper « invente » sur du bruit ou du silence
HALLUCINATIONS = re.compile(
    r"sous[- ]?titr|amara\.org|merci d.avoir regard|abonnez[- ]vous|traduction par|www\.|©", re.I)

WHISPER_MODELS = {"base": "Base — rapide, précision correcte (≈ 150 Mo)",
                  "small": "Small — équilibré, recommandé (≈ 480 Mo)",
                  "medium": "Medium — très précis, plus lent (≈ 1,5 Go)"}


class WhisperASR:
    def __init__(self, cfg, emit: Callable[..., None]) -> None:
        self.cfg, self.emit = cfg, emit
        self._model = None
        self._model_name = ""
        self._failed: str | None = None
        self._loading = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ état
    @property
    def enabled(self) -> bool:
        """Activé dans les réglages ET chargé sans erreur."""
        return bool(self.cfg["asr_whisper"]) and self._model is not None and self._failed is None

    def reset(self) -> None:
        """Après un changement de réglage : on oublie l'échec et on recharge si besoin."""
        with self._lock:
            self._failed = None
            if self._model_name != self.cfg["whisper_model"]:
                self._model, self._model_name = None, ""
        self.preload()

    def preload(self) -> None:
        if not self.cfg["asr_whisper"]:
            self.emit("asr", "off", "")
            return
        if self._model is not None and self._model_name == self.cfg["whisper_model"]:
            self.emit("asr", "ready", self._model_name)
            return
        if self._loading:
            return
        threading.Thread(target=self._load, daemon=True, name="sentinel-whisper-load").start()

    def _load(self) -> None:
        with self._lock:
            if self._loading:
                return
            self._loading = True
        name = self.cfg["whisper_model"] or "small"
        try:
            self.emit("asr", "loading", name)
            try:
                from faster_whisper import WhisperModel
            except ImportError:
                raise RuntimeError("faster-whisper n'est pas installé : lance « pip install faster-whisper »") from None
            cache = data_dir() / "whisper"
            cache.mkdir(parents=True, exist_ok=True)
            model = WhisperModel(name, device="cpu", compute_type="int8",
                                 cpu_threads=max(2, min(8, (os.cpu_count() or 4) - 1)), download_root=str(cache))
            self._model, self._model_name, self._failed = model, name, None
            self.emit("asr", "ready", name)
        except Exception as exc:
            log.warning("Whisper indisponible : %s", exc)
            self._failed = str(exc)
            self.emit("asr", "error", str(exc)[:160])
        finally:
            self._loading = False

    # ------------------------------------------------------------------ transcription
    def _prompt(self, hints: list[str]) -> str:
        """Petit texte d'amorce : aide Whisper à bien écrire « Sentinel » et les noms de tes programmes."""
        wake = (self.cfg["wake_word"] or "sentinel").capitalize()
        names = ", ".join(dict.fromkeys(h for h in hints if 2 < len(h) < 30))[:220]
        return f"{wake}, assistant vocal. Commandes : monte le son, baisse le volume, mets de la musique, lance, ouvre, ferme, minuteur. {names}".strip()

    def transcribe(self, pcm: bytes, hints: list[str] | None = None) -> str:
        """Audio 16 kHz mono int16 -> texte ('' si rien de fiable)."""
        if not self.enabled or len(pcm) < MIN_SAMPLES * 2:
            return ""
        try:
            import numpy as np

            audio = np.frombuffer(pcm[-MAX_SECONDS * 16000 * 2:], dtype=np.int16).astype(np.float32) / 32768.0
            segments, _info = self._model.transcribe(
                audio, language="fr", beam_size=4, temperature=0.0, condition_on_previous_text=False,
                vad_filter=True, vad_parameters={"min_silence_duration_ms": 350},
                initial_prompt=self._prompt(hints or []), no_speech_threshold=0.5,
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
        except Exception:
            log.exception("transcription Whisper en échec")
            return ""
        if HALLUCINATIONS.search(text):
            log.info("texte Whisper écarté (hallucination probable) : %r", text)
            return ""
        return text
