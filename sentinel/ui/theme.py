"""Thèmes, palettes et polices de l'interface Sentinel.

`apply(nom, fond_perso)` doit être appelé AVANT d'importer les modules de l'interface (main.py s'en charge) :
les couleurs sont lues une fois au chargement. Changer de thème demande donc de relancer Sentinel.
"""
from __future__ import annotations

import re

THEMES = {   # bg = fond, panel = cartes, panel2 = éléments actifs, grad = dégradé du HUD (haut, bas)
    "Abysse":    dict(bg="#040811", panel="#0A1424", panel2="#112038", border="#16304A", text="#DCF4FF", dim="#6F8CA8", grad=("#07132A", "#02040A")),
    "Onyx":      dict(bg="#070707", panel="#101010", panel2="#1A1A1A", border="#2A2A2A", text="#EDEDED", dim="#8A8A8A", grad=("#141414", "#030303")),
    "Nébuleuse": dict(bg="#0A0614", panel="#130C24", panel2="#1F1438", border="#3A2565", text="#EADFFF", dim="#8F7FB5", grad=("#1D0E3D", "#05030C")),
    "Matrice":   dict(bg="#020A05", panel="#07140C", panel2="#0D2415", border="#15442A", text="#D8FFE6", dim="#6FA687", grad=("#05230F", "#010603")),
    "Braise":    dict(bg="#0E0605", panel="#190D0A", panel2="#291510", border="#4A2418", text="#FFE9DD", dim="#B08670", grad=("#2E0F08", "#050201")),
    "Océan":     dict(bg="#02090C", panel="#08151B", panel2="#0F2630", border="#164352", text="#D9F6FF", dim="#6C9BAA", grad=("#04222E", "#010507")),
    "Crépuscule": dict(bg="#0B0713", panel="#160F22", panel2="#231736", border="#4A2A63", text="#FBE6FF", dim="#A886B8", grad=("#2A0F3A", "#12061A")),
}
ACCENTS = {
    "Cyan": "#00E5FF", "Orange": "#FF9F1C", "Rouge": "#FF3B47", "Vert": "#39FF88", "Violet": "#B388FF",
    "Magenta": "#FF3DCB", "Or": "#FFD21F", "Bleu électrique": "#3D8BFF", "Blanc glacé": "#E6F4FF",
}
DEFAULT_THEME = "Abysse"

BG = PANEL = PANEL2 = BORDER = TEXT = DIM = ""
GRAD_TOP = GRAD_BOTTOM = ""
DANGER = "#FF4D5E"
OK = "#39FF88"
FONT_MONO = "Consolas"
FONT_UI = "Segoe UI"
FONT_HEAD = "Bahnschrift"        # police « technique » de Windows 10/11 (repli automatique sinon)

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def is_hex(value: str) -> bool:
    return bool(_HEX.match(value or ""))


def mix(a: str, b: str, t: float) -> str:
    """Mélange de deux couleurs (t = 0 -> a, t = 1 -> b)."""
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(ca[k] + (cb[k] - ca[k]) * t) for k in range(3))


def luminance(color: str) -> float:
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def derive(bg: str) -> dict:
    """Palette complète à partir d'une seule couleur de fond (sombre) choisie par l'utilisateur."""
    return dict(bg=bg, panel=mix(bg, "#FFFFFF", 0.05), panel2=mix(bg, "#FFFFFF", 0.10), border=mix(bg, "#FFFFFF", 0.20),
                text="#E8F2FF", dim=mix(bg, "#FFFFFF", 0.55), grad=(mix(bg, "#FFFFFF", 0.10), mix(bg, "#000000", 0.55)))


def apply(name: str = DEFAULT_THEME, custom_bg: str = "") -> str:
    """Charge un thème (ou une couleur de fond perso). Retourne le nom réellement appliqué."""
    global BG, PANEL, PANEL2, BORDER, TEXT, DIM, GRAD_TOP, GRAD_BOTTOM
    if is_hex(custom_bg) and luminance(custom_bg) <= 0.25:
        pal, used = derive(custom_bg), "Personnalisé"
    else:
        used = name if name in THEMES else DEFAULT_THEME
        pal = THEMES[used]
    BG, PANEL, PANEL2, BORDER, TEXT, DIM = (pal[k] for k in ("bg", "panel", "panel2", "border", "text", "dim"))
    GRAD_TOP, GRAD_BOTTOM = pal["grad"]
    return used


apply()      # valeurs par défaut : l'application les remplace au démarrage selon la config
