"""Distribution des événements de Sentinel vers les fenêtres web (Server-Sent Events)."""
from __future__ import annotations

import dataclasses
import queue
import threading

# Derniers événements de ces types : rejoués à une page qui vient de se connecter.
REPLAY = {"state", "ready", "weather", "brain", "asr", "update", "apps_indexed", "files_indexed",
          "timers", "telemetry", "model_missing"}


def jsonable(x, depth: int = 0):
    if x is None or isinstance(x, (bool, int, float, str)):
        return x
    if depth > 6:
        return str(x)
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return jsonable(dataclasses.asdict(x), depth + 1)
    if isinstance(x, dict):
        return {str(k): jsonable(v, depth + 1) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [jsonable(v, depth + 1) for v in x]
    return str(x)


def translate(ev: tuple) -> dict:
    """('log', 'cmd', 'texte') -> {'t': 'log', 'a': ['cmd', 'texte']}"""
    return {"t": str(ev[0]), "a": [jsonable(a) for a in ev[1:]]}


class EventBus:
    def __init__(self) -> None:
        self._subs: list[queue.Queue] = []
        self._last: dict[str, dict] = {}
        self._lock = threading.Lock()

    def publish(self, ev: dict) -> None:
        with self._lock:
            if ev["t"] in REPLAY:
                self._last[ev["t"]] = ev
            for q in self._subs:
                try:
                    q.put_nowait(ev)
                except queue.Full:                       # client trop lent : on abandonne cet événement
                    pass

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=500)
        with self._lock:
            for ev in self._last.values():
                q.put_nowait(ev)
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)
