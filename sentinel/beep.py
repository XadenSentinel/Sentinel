"""Petit son de confirmation quand Sentinel te reconnaît (sans fichier audio, généré à la volée)."""
from __future__ import annotations

import logging
import sys
import threading

log = logging.getLogger("sentinel.beep")


def _beep(freq: int, ms: int) -> None:
    if sys.platform != "win32":
        return
    import winsound
    winsound.Beep(freq, ms)


def play_wake() -> None:
    """Deux notes courtes et discrètes, jouées en tâche de fond (ne bloque jamais l'appelant)."""
    def work() -> None:
        try:
            _beep(880, 70)
            _beep(1244, 70)
        except Exception:
            log.debug("son de réveil indisponible", exc_info=True)

    threading.Thread(target=work, daemon=True, name="sentinel-beep").start()
