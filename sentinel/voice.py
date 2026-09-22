"""Voix : écoute permanente hors-ligne (Vosk). La synthèse vocale est dans tts.py.

Le micro est analysé EN LOCAL : rien ne part sur Internet. Le mot déclencheur
est repéré dans le texte reconnu (comparaison approximative + alias), puis la
suite de la phrase est envoyée comme commande. Si tu dis seulement
« Sentinel », il écoute la phrase suivante pendant `listen_timeout` secondes.
"""
from __future__ import annotations

import json
import logging
import math
import queue
import threading
import time
import urllib.request
import zipfile
from array import array
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Iterator

from .config import bundle_dir, data_dir, exe_dir
from .nlu import normalize
from .asr import WhisperASR
from .tts import Speaker  # noqa: F401  (réexporté : la synthèse vocale vit dans tts.py)

log = logging.getLogger("sentinel.voice")

SAMPLE_RATE = 16000
MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-fr-0.22.zip"

Emit = Callable[..., None]
MAX_UTTERANCE_CHUNKS = 80          # 80 blocs de 0,25 s = 20 s
LOOSE_WAKE = 0.66                  # seuil « ça ressemble à Sentinel » pour déclencher Whisper
BARGE_RMS = 0.11                   # niveau micro à partir duquel une voix par-dessus Sentinel compte
BARGE_FRAMES = 5                   # nombre de blocs consécutifs au-dessus du seuil avant de couper


# --------------------------------------------------------------------------- #
# Modèle Vosk
# --------------------------------------------------------------------------- #
def _model_candidates(cfg) -> Iterator[Path]:
    """Dossiers susceptibles de contenir un modèle Vosk, le meilleur d'abord.

    - le chemin choisi dans la config passe en premier ;
    - ensuite les gros modèles (vosk-model-fr-0.22…) avant les « small » ;
    - un niveau de dossier en trop (double extraction du zip) est toléré.
    """
    if cfg["model_path"]:
        yield Path(cfg["model_path"])
    found: list[Path] = []
    for base in (data_dir() / "models", exe_dir() / "models", bundle_dir() / "models"):
        if not base.is_dir():
            continue
        for sub in base.iterdir():
            if not sub.is_dir():
                continue
            found.append(sub)
            found.extend(p for p in sub.iterdir() if p.is_dir())   # dossier imbriqué
    found.sort(key=lambda p: ("small" in p.name.lower(), p.name))
    yield from found


def find_model(cfg) -> Path | None:
    for path in _model_candidates(cfg):
        if (path / "am").is_dir():
            return path
    return None


def download_model(progress: Callable[[float], None]) -> None:
    """Télécharge et décompresse le modèle français (~41 Mo) dans %APPDATA%\\Sentinel\\models."""
    dest = data_dir() / "models"
    dest.mkdir(parents=True, exist_ok=True)
    archive = dest / "model.zip"
    with urllib.request.urlopen(MODEL_URL, timeout=30) as resp, open(archive, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            progress(done / total if total else 0.0)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(dest)
    archive.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# Périphériques
# --------------------------------------------------------------------------- #
def list_mics() -> list[str]:
    try:
        import sounddevice as sd

        api = sd.default.hostapi
        return [f"{i}: {d['name']}" for i, d in enumerate(sd.query_devices())
                if d["max_input_channels"] > 0 and d["hostapi"] == api]
    except Exception:
        return []


def list_voices() -> list[str]:
    try:
        import win32com.client

        tokens = win32com.client.Dispatch("SAPI.SpVoice").GetVoices()
        return [tokens.Item(i).GetDescription() for i in range(tokens.Count)]
    except Exception:
        return []


def _is_french(description: str) -> bool:
    d = description.lower()
    return any(k in d for k in ("french", "français", "francais", "hortense", "julie", "paul", "fr-fr", "fr-ca"))


def _rms(data: bytes) -> float:
    samples = array("h")
    samples.frombytes(data)
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768.0


# --------------------------------------------------------------------------- #
# Écoute + mot déclencheur
# --------------------------------------------------------------------------- #
class Listener(threading.Thread):
    def __init__(self, cfg, speaker: Speaker, emit: Emit,
                 on_wake: Callable[[], None], on_command: Callable[[str], None]) -> None:
        super().__init__(daemon=True, name="sentinel-listener")
        self.cfg, self.speaker, self.emit = cfg, speaker, emit
        self.on_wake, self.on_command = on_wake, on_command
        self.enabled = threading.Event()
        self.enabled.set()
        self.level = 0.0                 # niveau micro 0..1 (animation du réacteur)
        self.active_until = 0.0          # >0 : fenêtre « je t'écoute » ouverte
        self._halt = threading.Event()   # (pas « _stop » : nom réservé par threading.Thread)
        self._restart = threading.Event()
        self.asr = WhisperASR(cfg, emit)                  # précision : re-transcrit les phrases pour Sentinel
        self.hints: Callable[[], list[str]] = lambda: []  # noms d'applis donnés à Whisper (fournis par l'assistant)

    # -- contrôle -------------------------------------------------------------
    def stop(self) -> None:
        self._halt.set()

    def restart_stream(self) -> None:
        self._restart.set()

    def trigger(self) -> None:
        """Équivalent d'avoir dit le mot déclencheur (bouton « Parler »)."""
        self.active_until = time.time() + float(self.cfg["listen_timeout"])
        self.emit("state", "listening")

    # -- boucle principale ------------------------------------------------------
    def run(self) -> None:
        while not self._halt.is_set():
            model_dir = find_model(self.cfg)
            if model_dir is None:
                self.emit("model_missing")
                while not self._halt.is_set() and find_model(self.cfg) is None:
                    time.sleep(1.0)
                continue
            try:
                self._listen(model_dir)
            except Exception as exc:
                log.exception("erreur d'écoute")
                self.emit("state", "error")
                self.emit("log", "error", f"Micro / reconnaissance : {exc}")
                time.sleep(3)

    def _listen(self, model_dir: Path) -> None:
        import sounddevice as sd
        from vosk import KaldiRecognizer, Model, SetLogLevel

        SetLogLevel(-1)
        self.emit("log", "info", "Chargement du modèle vocal…")
        recognizer = KaldiRecognizer(Model(str(model_dir)), SAMPLE_RATE)
        log.info("modèle vocal chargé : %s", model_dir.name)
        self.asr.preload()
        audio: queue.Queue[bytes] = queue.Queue(maxsize=100)
        utterance: list[bytes] = []                     # audio de la phrase en cours (pour Whisper)

        def callback(indata, frames, time_info, status):
            try:
                audio.put_nowait(bytes(indata))
            except queue.Full:
                pass

        self._restart.clear()
        with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=4000, dtype="int16",
                               channels=1, device=self.cfg["mic_device"], callback=callback):
            self.emit("ready", model_dir.name)
            self.emit("state", "idle" if self.enabled.is_set() else "off")
            was_muted = False
            wake_flag = False
            while not self._halt.is_set() and not self._restart.is_set():
                try:
                    data = audio.get(timeout=0.3)
                except queue.Empty:
                    self._tick()
                    continue
                self.level = 0.6 * self.level + 0.4 * _rms(data)

                if not self.enabled.is_set() or self.speaker.busy.is_set():
                    was_muted = True
                    utterance.clear()
                    if self.active_until and self.speaker.busy.is_set():
                        self.active_until = time.time() + float(self.cfg["listen_timeout"])
                    if self.enabled.is_set() and self.speaker.busy.is_set() and self.cfg["barge_in"]:
                        if _rms(data) > BARGE_RMS:
                            self._loud_run = getattr(self, "_loud_run", 0) + 1
                            if self._loud_run >= BARGE_FRAMES:
                                self._loud_run = 0
                                self.speaker.interrupt()
                                self.active_until = time.time() + float(self.cfg["listen_timeout"])
                                self.emit("state", "listening")
                        else:
                            self._loud_run = 0
                    continue
                if was_muted:
                    recognizer.Reset()
                    was_muted = wake_flag = False
                    utterance.clear()
                self._tick()
                utterance.append(data)
                del utterance[:-MAX_UTTERANCE_CHUNKS]           # on ne garde que les ~20 dernières secondes

                if recognizer.AcceptWaveform(data):
                    text = json.loads(recognizer.Result()).get("text", "").strip()
                    pcm = b"".join(utterance)
                    utterance.clear()
                    handled = self._on_utterance(text, pcm, wake_flag) if text else False
                    if wake_flag and not handled and not self.active_until:
                        self.emit("state", "idle")
                    wake_flag = False
                elif not self.active_until and not wake_flag:
                    partial = json.loads(recognizer.PartialResult()).get("partial", "")
                    if partial and self._find_wake(normalize(partial).split()):
                        wake_flag = True
                        self.emit("state", "listening")

    def _on_utterance(self, text: str, pcm: bytes, wake_flag: bool) -> bool:
        """Phrase terminée : si elle s'adresse à Sentinel, Whisper la re-transcrit (plus fiable que Vosk)."""
        if self.asr.enabled and self._worth_refining(text, wake_flag):
            self.emit("state", "thinking")
            refined = self.asr.transcribe(pcm, self.hints())
            if refined:
                if self.cfg["show_heard"]:
                    self.emit("log", "info", f"Vosk : « {text} »  →  Whisper : « {refined} »")
                if self._on_final(refined):
                    return True
        return self._on_final(text)

    def _worth_refining(self, text: str, wake_flag: bool) -> bool:
        """Vaut-il la peine de lancer Whisper ? Oui si fenêtre ouverte, ou mot déclencheur (même approximatif)."""
        if wake_flag or (self.active_until and time.time() <= self.active_until):
            return True
        tokens = normalize(text).split()
        names = self._wake_names()
        pool = tokens + [a + b for a, b in zip(tokens, tokens[1:])]
        return any(len(t) >= 4 and SequenceMatcher(None, t, n).ratio() >= LOOSE_WAKE
                   for t in pool for n in names)

    def _tick(self) -> None:
        if self.active_until and time.time() > self.active_until and not self.speaker.busy.is_set():
            self.active_until = 0.0
            self.emit("state", "idle")

    # -- mot déclencheur --------------------------------------------------------
    def _wake_names(self) -> list[str]:
        names = [self.cfg["wake_word"], *self.cfg["wake_aliases"]]
        return [n for n in (normalize(x) for x in names) if n]

    def _find_wake(self, tokens: list[str]) -> tuple[int, int] | None:
        """Retourne (début, fin) du mot déclencheur dans la liste de mots, ou None."""
        names = self._wake_names()

        def similar(word: str) -> bool:
            return any(word == n or (len(word) >= 4 and SequenceMatcher(None, word, n).ratio() >= 0.8)
                       for n in names)

        for i, tok in enumerate(tokens):
            if similar(tok):
                return i, i + 1
            if i + 1 < len(tokens) and similar(tok + tokens[i + 1]):   # « sentine elle »
                return i, i + 2
        return None

    @staticmethod
    def _raw_after(text: str, skip: int) -> str:
        """Partie du texte ORIGINAL (accents, majuscules, ponctuation) située après les `skip` premiers mots normalisés."""
        seen = 0
        words = text.split()
        for i, w in enumerate(words):
            if seen >= skip:
                return " ".join(words[i:])
            seen += len(normalize(w).split())
        return ""

    def _on_final(self, text: str) -> bool:
        """Traite une phrase complète. Retourne True si elle a déclenché quelque chose."""
        n = normalize(text)
        tokens = n.split()
        span = self._find_wake(tokens)
        now = time.time()
        active = bool(self.active_until) and now <= self.active_until

        if self.cfg["show_heard"] or span or active:
            self.emit("log", "heard", text)

        if span:
            command = " ".join(tokens[span[1]:])
            if command:
                self.active_until = 0.0
                self.on_command(self._raw_after(text, span[1]) or command)
            else:
                self.active_until = now + float(self.cfg["listen_timeout"]) + 2.0   # +2 s : le temps du « Oui ? »
                self.emit("state", "listening")
                self.on_wake()
            return True
        if active:
            self.active_until = 0.0
            self.on_command(text)
            return True
        return False
