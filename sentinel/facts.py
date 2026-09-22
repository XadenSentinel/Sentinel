"""Mémoire à long terme : ce que tu demandes explicitement à Sentinel de retenir sur toi.

« Souviens-toi que mon chat s'appelle Nuage » -> Sentinel le garde et le rappelle au cerveau IA à
chaque conversation. Différent de la mémoire d'apprentissage (learning.py), qui ne retient que des
corrections de commandes. Stocké en local (%APPDATA%\\Sentinel\\facts.json), jamais envoyé nulle part
sauf au cerveau IA que tu as choisi (Ollama en local, ou Claude si tu l'as activé).
"""
from __future__ import annotations

import json
import logging
import threading
import time

from .config import data_dir

log = logging.getLogger("sentinel.facts")

MAX_FACTS = 200
PROMPT_LIMIT = 40


class FactsMemory:
    def __init__(self) -> None:
        self._path = data_dir() / "facts.json"
        self._lock = threading.RLock()
        self.items: list[dict] = []
        try:
            self.items = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            pass
        except Exception:
            log.exception("facts.json illisible : mémoire vide")

    def _save(self) -> None:
        try:
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.items[-MAX_FACTS:], ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            log.warning("mémoire à long terme non enregistrée", exc_info=True)

    def add(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        with self._lock:
            self.items.append({"text": text[:400], "ts": int(time.time())})
            self._save()

    def remove(self, ts: int) -> None:
        with self._lock:
            self.items = [i for i in self.items if i.get("ts") != ts]
            self._save()

    def clear(self) -> None:
        with self._lock:
            self.items = []
            self._save()

    def prompt_block(self) -> str:
        with self._lock:
            recent = self.items[-PROMPT_LIMIT:]
        if not recent:
            return ""
        lines = "\n".join(f"- {i['text']}" for i in recent)
        return f"\nCe que l'utilisateur t'a demandé de retenir sur lui (utilise-le si pertinent) :\n{lines}\n"
