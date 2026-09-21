"""Minuteurs vocaux (plusieurs en parallèle, avec un nom facultatif)."""
from __future__ import annotations

import datetime
import itertools
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from ..replies import R, fr_time

log = logging.getLogger("sentinel.timers")


def format_duration(seconds: int) -> str:
    """90 -> « 1 minute 30 » ; 5400 -> « 1 heure 30 » ; 45 -> « 45 secondes » (pour être prononcé)."""
    seconds = int(round(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    if h:
        text = f"{h} heure{'s' if h > 1 else ''}"
        return f"{text} {m}" if m else text
    if m:
        text = f"{m} minute{'s' if m > 1 else ''}"
        return f"{text} {s}" if s else text
    return f"{s} seconde{'s' if s > 1 else ''}"


def format_clock(seconds: float) -> str:
    """Affichage à l'écran : 07:05 ou 1:02:03."""
    seconds = max(0, int(seconds + 0.999))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


@dataclass
class TimerItem:
    id: int
    seconds: int
    label: str | None
    ends_at: float                       # time.monotonic()
    handle: threading.Timer | None = field(default=None, repr=False)

    @property
    def left(self) -> float:
        return max(0.0, self.ends_at - time.monotonic())


class Timers:
    def __init__(self, cfg, on_done: Callable[[TimerItem], None]) -> None:
        self.cfg = cfg
        self.on_done = on_done
        self._items: dict[int, TimerItem] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ API
    def add(self, seconds: int, label: str | None = None) -> TimerItem:
        item = TimerItem(next(self._ids), int(seconds), label, time.monotonic() + seconds)
        item.handle = threading.Timer(seconds, self._fire, args=(item.id,))
        item.handle.daemon = True
        with self._lock:
            self._items[item.id] = item
        item.handle.start()
        return item

    def snapshot(self) -> list[TimerItem]:
        with self._lock:
            return sorted(self._items.values(), key=lambda t: t.ends_at)

    def cancel_all(self) -> int:
        with self._lock:
            items, self._items = list(self._items.values()), {}
        for it in items:
            if it.handle:
                it.handle.cancel()
        return len(items)

    def shutdown(self) -> None:
        self.cancel_all()

    def _fire(self, timer_id: int) -> None:
        with self._lock:
            item = self._items.pop(timer_id, None)
        if item is None:                 # annulé entre-temps
            return
        try:
            self.on_done(item)
        except Exception:
            log.exception("erreur dans la fin du minuteur")

    # --------------------------------------------------------- phrases parlées
    def say_set(self, seconds: int | None, label: str | None) -> str:
        if not seconds:
            return R(self.cfg, "timer_ask")
        if seconds > 24 * 3600:
            return R(self.cfg, "timer_ask")
        self.add(seconds, label)
        if label == "réveil":
            at = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
            return R(self.cfg, "alarm_set", heure=fr_time(at))
        duree = format_duration(seconds)
        if label:
            return R(self.cfg, "timer_set_label", duree=duree, label=label)
        return R(self.cfg, "timer_set", duree=duree)

    def say_left(self) -> str:
        items = self.snapshot()
        if not items:
            return R(self.cfg, "timer_none")
        if len(items) == 1:
            return R(self.cfg, "timer_left", reste=format_duration(items[0].left))
        return R(self.cfg, "timer_left_many", n=len(items), reste=format_duration(items[0].left))

    def say_cancel(self) -> str:
        n = self.cancel_all()
        if n == 0:
            return R(self.cfg, "timer_none")
        return R(self.cfg, "timer_cancel") if n == 1 else R(self.cfg, "timer_cancel_many", n=n)

    def say_done(self, item: TimerItem) -> str:
        if item.label == "réveil":
            return R(self.cfg, "alarm_done")
        duree = format_duration(item.seconds)
        if item.label:
            return R(self.cfg, "timer_done_label", duree=duree, label=item.label)
        return R(self.cfg, "timer_done", duree=duree)
