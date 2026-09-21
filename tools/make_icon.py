"""Génère assets/sentinel.ico (réacteur stylisé). Usage : python tools/make_icon.py"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

ACCENT = (0, 229, 255, 255)
BG = (5, 11, 20, 255)


def draw(size: int) -> Image.Image:
    s = size * 4                                   # sur-échantillonnage pour lisser
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = s / 2
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=s * 0.22, fill=BG)
    # anneau extérieur segmenté
    r = s * 0.40
    for i in range(12):
        a0 = i * 30 + 4
        d.arc((c - r, c - r, c + r, c + r), a0, a0 + 20, fill=ACCENT, width=max(2, int(s * 0.045)))
    # anneau intérieur
    r2 = s * 0.26
    d.ellipse((c - r2, c - r2, c + r2, c + r2), outline=ACCENT, width=max(2, int(s * 0.03)))
    # branches
    for k in range(3):
        a = math.radians(90 + k * 120)
        d.line((c + math.cos(a) * r2 * 0.4, c - math.sin(a) * r2 * 0.4,
                c + math.cos(a) * r2, c - math.sin(a) * r2), fill=ACCENT, width=max(2, int(s * 0.03)))
    # noyau
    r3 = s * 0.10
    d.ellipse((c - r3, c - r3, c + r3, c + r3), fill=ACCENT)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "assets" / "sentinel.ico"
    out.parent.mkdir(exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    draw(256).save(out, format="ICO", sizes=[(n, n) for n in sizes])
    print("Icône écrite :", out)
