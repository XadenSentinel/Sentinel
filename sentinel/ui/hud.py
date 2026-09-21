"""HUD principal de Sentinel : un seul Canvas qui dessine tout l'écran d'accueil.

- réacteur animé (anneaux, arcs, noyau qui pulse avec ta voix) entouré d'un anneau de barres audio ;
- balayage « radar » quand l'IA réfléchit, ondes quand Sentinel parle ;
- horloge, date, état, phrase entendue et réponse écrits directement sur le canvas (pas de widgets en plus).

Performance : les éléments sont créés UNE fois ; à chaque image on ne fait que déplacer / recolorer
(≈ 100 éléments), et la grille de fond n'est redessinée qu'au redimensionnement.
"""
from __future__ import annotations

import math
import tkinter as tk

from . import theme as T

N_BARS = 64
# (rotation °/image, luminosité) par état
STATES = {
    "loading":   (3.0, 0.60), "idle": (0.45, 0.62), "listening": (1.6, 1.00), "thinking": (5.5, 0.92),
    "speaking":  (1.0, 1.00), "off": (0.08, 0.24), "nomodel": (0.08, 0.30), "error": (0.08, 0.32),
}


def blend(fg: str, bg: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    f = [int(fg[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(bg[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(b[k] + (f[k] - b[k]) * t) for k in range(3))


class Hud(tk.Canvas):
    def __init__(self, master, accent: str, style: str = "stars", fx: bool = True) -> None:
        super().__init__(master, bg=T.BG, highlightthickness=0, bd=0)
        self.accent = accent
        self.style, self.fx = style, fx
        self.stars: list[list] = []            # [x, y, vitesse, taille, phase]
        self._star_ids: list[int] = []
        self._scan_y = 0.0
        self._frame = 0
        self.w = self.h = 0
        self.rot = 0.0
        self.phase = 0.0
        self.bars = [0.0] * N_BARS
        self.texts = {"clock": "", "date": "", "badge": "", "tele": "", "state": "", "hint": "", "heard": "", "reply": ""}
        self._ready = False
        self._pal_key = None
        self.bind("<Configure>", self._on_resize)

    # ------------------------------------------------------------------ API
    def set_accent(self, color: str) -> None:
        self.accent = color
        self._rebuild()

    def set_style(self, style: str, fx: bool) -> None:
        self.style, self.fx = style, fx
        self._rebuild()

    def set_text(self, key: str, value: str) -> None:
        if self.texts.get(key) == value:
            return
        self.texts[key] = value
        if self._ready:
            self.itemconfigure(self._txt[key], text=value)

    # ------------------------------------------------------------------ construction
    def _on_resize(self, ev) -> None:
        if abs(ev.width - self.w) > 3 or abs(ev.height - self.h) > 3:
            self.w, self.h = ev.width, ev.height
            self._rebuild()

    def _layout(self) -> None:
        w, h = self.w, self.h
        text_h = 150
        top = 78
        region_h = max(160, h - text_h - top - 10)
        self.cx = w / 2
        self.cy = top + region_h / 2
        self.R = max(60.0, min(w * 0.33, region_h / 2 / 1.18))

    def _rebuild(self) -> None:
        if self.w < 50 or self.h < 50:
            return
        self._layout()
        self.delete("all")
        a, cx, cy, R = self.accent, self.cx, self.cy, self.R
        grid = blend(a, T.BG, 0.07)
        faint = blend(a, T.BG, 0.16)
        edge = blend(a, T.BG, 0.45)

        # ---- fond : dégradé, étoiles, grille très discrète, cercles, coins ----
        if self.style in ("stars", "gradient"):
            bands = 40
            for i in range(bands):
                y0, y1 = self.h * i / bands, self.h * (i + 1) / bands + 1
                self.create_rectangle(0, y0, self.w, y1, fill=T.mix(T.GRAD_TOP, T.GRAD_BOTTOM, i / (bands - 1)), outline="")
        if self.style != "minimal":
            step = 44
            for x in range(step // 2, self.w, step):
                self.create_line(x, 0, x, self.h, fill=grid)
            for y in range(step // 2, self.h, step):
                self.create_line(0, y, self.w, y, fill=grid)
        self.stars, self._star_ids = [], []
        if self.style == "stars":
            import random
            rnd = random.Random(7)
            for _ in range(46):
                self.stars.append([rnd.uniform(0, self.w), rnd.uniform(0, self.h), rnd.uniform(0.08, 0.35),
                                   rnd.choice((1, 1, 2, 2, 3)), rnd.uniform(0, 6.3)])
            self._star_ids = [self.create_oval(0, 0, 0, 0, fill=faint, outline="") for _ in self.stars]
        for k in (1.36, 1.62):
            self.create_oval(cx - R * k, cy - R * k, cx + R * k, cy + R * k, outline=blend(a, T.BG, 0.09))
        m, ln = 14, 30
        for sx, sy, dx, dy in ((m, m, 1, 1), (self.w - m, m, -1, 1), (m, self.h - m, 1, -1), (self.w - m, self.h - m, -1, -1)):
            self.create_line(sx, sy + dy * ln, sx, sy, sx + dx * ln, sy, fill=edge, width=2)
        self.create_line(m + 4, 66, self.w * 0.30, 66, fill=faint)                        # filet sous l'horloge
        self.create_line(self.w * 0.70, 66, self.w - m - 4, 66, fill=faint)

        # ---- anneau de barres (dynamique) ----
        self._bar_ids, self._cos, self._sin = [], [], []
        for i in range(N_BARS):
            ang = 2 * math.pi * i / N_BARS - math.pi / 2
            self._cos.append(math.cos(ang))
            self._sin.append(math.sin(ang))
            self._bar_ids.append(self.create_line(cx, cy, cx, cy, width=3, capstyle="round", fill=faint))

        # ---- structure du réacteur ----
        self._ring_out = self.create_oval(cx - R, cy - R, cx + R, cy + R, outline=faint, width=2)
        self._ticks = self.create_oval(cx - R * 0.94, cy - R * 0.94, cx + R * 0.94, cy + R * 0.94,
                                       outline=faint, width=6, dash=(1, 5))
        self._arcs_a = [self.create_arc(cx - R * 0.82, cy - R * 0.82, cx + R * 0.82, cy + R * 0.82, style=tk.ARC,
                                        start=k * 120, extent=70, outline=faint, width=5) for k in range(3)]
        self._arcs_b = [self.create_arc(cx - R * 0.66, cy - R * 0.66, cx + R * 0.66, cy + R * 0.66, style=tk.ARC,
                                        start=k * 180, extent=105, outline=faint, width=3) for k in range(2)]
        self._ring_mid = self.create_oval(cx - R * 0.52, cy - R * 0.52, cx + R * 0.52, cy + R * 0.52, outline=faint)
        self._segs = [self.create_arc(cx - R * 0.42, cy - R * 0.42, cx + R * 0.42, cy + R * 0.42, style=tk.ARC,
                                      start=k * 45, extent=36, outline=faint, width=max(6, int(R * 0.055))) for k in range(8)]
        self._sweep = [self.create_arc(cx - R * 0.74, cy - R * 0.74, cx + R * 0.74, cy + R * 0.74, style=tk.ARC,
                                       start=0, extent=7, outline=faint, width=9, state="hidden") for _ in range(9)]
        self._glow = [self.create_oval(cx, cy, cx, cy, outline=faint, width=2) for _ in range(4)]
        self._core = self.create_oval(cx, cy, cx, cy, fill=faint, outline=faint, width=2)
        self._dots = [self.create_oval(cx, cy, cx, cy, fill=faint, outline="") for _ in range(4)]

        # ---- textes ----
        ty = self.h - 150
        self._txt = {
            "clock": self.create_text(m + 10, 12, anchor="nw", font=(T.FONT_MONO, 30, "bold"), fill=a),
            "date": self.create_text(m + 12, 50, anchor="nw", font=(T.FONT_UI, 11), fill=T.DIM),
            "badge": self.create_text(self.w - m - 10, 18, anchor="ne", font=(T.FONT_MONO, 11, "bold"), fill=T.DIM),
            "tele": self.create_text(self.w - m - 10, 40, anchor="ne", font=(T.FONT_MONO, 10), fill=blend(a, T.BG, 0.55)),
            "state": self.create_text(cx, ty + 12, font=(T.FONT_MONO, 20, "bold"), fill=a),
            "hint": self.create_text(cx, ty + 42, font=(T.FONT_UI, 12), fill=T.DIM),
            "heard": self.create_text(cx, ty + 82, font=(T.FONT_UI, 15), fill=T.TEXT, width=min(self.w - 80, 720), justify="center"),
            "reply": self.create_text(cx, ty + 124, font=(T.FONT_UI, 13), fill=T.OK, width=min(self.w - 80, 720), justify="center"),
        }
        for key, value in self.texts.items():
            self.itemconfigure(self._txt[key], text=value)
        self._scan = self.create_line(0, 0, self.w, 0, fill=blend(a, T.BG, 0.14), width=2, state="normal" if self.fx else "hidden")
        self._pal_key = None
        self._ready = True

    # ------------------------------------------------------------------ animation
    def _palette(self, bright: float) -> dict:
        a = self.accent
        return {
            "strong": blend(a, T.BG, bright), "mid": blend(a, T.BG, bright * 0.6), "dim": blend(a, T.BG, bright * 0.28),
            "core": blend(blend("#FFFFFF", a, 0.35), T.BG, bright),
            "bars": [blend(a, T.BG, bright * (0.22 + 0.78 * k / 11)) for k in range(12)],
            "sweep": [blend(a, T.BG, bright * (1 - i / 9) * 0.95) for i in range(9)],
        }

    def draw(self, state: str, level: float) -> None:
        if not self._ready:
            return
        speed, bright = STATES.get(state, STATES["idle"])
        self.rot = (self.rot + speed) % 360
        self.phase += 0.24 if state == "speaking" else 0.07
        ph, cx, cy, R = self.phase, self.cx, self.cy, self.R
        pulse = 0.5 + 0.5 * math.sin(ph)
        lvl = min(1.0, level * 7) if state in ("idle", "listening") else 0.0

        key = (state, self.accent)
        if key != self._pal_key:                                  # couleurs recalculées seulement si l'état change
            self._pal, self._pal_key = self._palette(bright), key
        pal = self._pal

        # -- barres audio autour du réacteur --
        r0, rmax = R * 1.05, R * 0.17
        for i in range(N_BARS):
            if state == "speaking":
                target = 0.18 + 0.62 * abs(math.sin(i * 0.33 + ph * 5.2)) * (0.65 + 0.35 * math.sin(ph * 2.1 + i * 0.1))
            elif state == "thinking":
                d = (i * 360 / N_BARS - self.rot * 1.2) % 360
                target = 0.85 * max(0.0, 1 - d / 70) + 0.06
            elif state in ("idle", "listening"):
                target = 0.05 + 0.04 * math.sin(i * 0.5 + ph) + lvl * (0.45 + 0.55 * abs(math.sin(i * 0.71 + ph * 3.3)))
            else:
                target = 0.03
            self.bars[i] += (target - self.bars[i]) * 0.35
            v = min(1.0, self.bars[i])
            r1 = r0 + rmax * v
            self.coords(self._bar_ids[i], cx + r0 * self._cos[i], cy + r0 * self._sin[i],
                        cx + r1 * self._cos[i], cy + r1 * self._sin[i])
            self.itemconfigure(self._bar_ids[i], fill=pal["bars"][min(11, int(v * 11.99))])

        # -- structure --
        self.itemconfigure(self._ring_out, outline=pal["mid"])
        self.itemconfigure(self._ticks, outline=pal["dim"], dashoffset=int(self.rot * 0.6))
        self.itemconfigure(self._ring_mid, outline=pal["dim"])
        for k, item in enumerate(self._arcs_a):
            self.itemconfigure(item, start=self.rot + k * 120, outline=pal["strong"])
        for k, item in enumerate(self._arcs_b):
            self.itemconfigure(item, start=-self.rot * 1.6 + k * 180, outline=pal["mid"])
        for k, item in enumerate(self._segs):
            self.itemconfigure(item, start=self.rot * 0.5 + k * 45 + 4, outline=pal["strong"])

        # -- balayage radar (IA qui réfléchit) --
        sweeping = state == "thinking"
        for i, item in enumerate(self._sweep):
            if sweeping:
                self.itemconfigure(item, state="normal", start=(-self.rot * 2.0 - i * 6) % 360, outline=pal["sweep"][i])
            else:
                self.itemconfigure(item, state="hidden")

        # -- noyau qui pulse --
        core = R * 0.15 + R * 0.028 * pulse + R * 0.10 * lvl
        for j, item in enumerate(self._glow, start=1):
            r = core + (5 - j) * R * 0.03
            self.coords(item, cx - r, cy - r, cx + r, cy + r)
            self.itemconfigure(item, outline=blend(self.accent, T.BG, bright * (0.12 + 0.11 * j)))
        self.coords(self._core, cx - core, cy - core, cx + core, cy + core)
        self.itemconfigure(self._core, fill=pal["core"], outline=pal["strong"])

        # -- étoiles qui dérivent lentement + balayage lumineux --
        self._frame += 1
        if self.stars and self._frame % 2 == 0:
            for star, item in zip(self.stars, self._star_ids):
                star[1] = (star[1] + star[2]) % self.h
                star[4] += 0.05
                x, y, size = star[0], star[1], star[3]
                self.coords(item, x, y, x + size, y + size)
                self.itemconfigure(item, fill=blend(self.accent, T.BG, (0.16 + 0.30 * abs(math.sin(star[4]))) * bright))
        if self.fx:
            self._scan_y = (self._scan_y + 1.6) % self.h
            self.coords(self._scan, 0, self._scan_y, self.w, self._scan_y)

        # -- petits satellites --
        for k, item in enumerate(self._dots):
            ang = math.radians(self.rot * (1.4 if k % 2 else -1.1) + k * 90)
            rr = R * (0.94 if k % 2 else 0.74)
            x, y = cx + rr * math.cos(ang), cy - rr * math.sin(ang)
            self.coords(item, x - 3, y - 3, x + 3, y + 3)
            self.itemconfigure(item, fill=pal["strong"])
