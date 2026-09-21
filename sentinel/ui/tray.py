"""Icône dans la zone de notification (pystray). Optionnelle : renvoie None si absente."""
from __future__ import annotations

import logging
import queue

log = logging.getLogger("sentinel.tray")


def create_tray(ui_queue: "queue.Queue", accent: str):
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        log.warning("pystray / Pillow absents : pas d'icône de notification")
        return None

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), outline=accent, width=5)
    d.ellipse((20, 20, 44, 44), fill=accent)

    menu = pystray.Menu(
        pystray.MenuItem("Afficher Sentinel", lambda: ui_queue.put(("show",)), default=True),
        pystray.MenuItem("Activer / couper l'écoute", lambda: ui_queue.put(("toggle_listen",))),
        pystray.MenuItem("Quitter", lambda: ui_queue.put(("quit",))),
    )
    icon = pystray.Icon("Sentinel", img, "Sentinel — assistant vocal", menu)
    icon.run_detached()          # thread séparé : compatible avec la boucle Tkinter
    return icon
