"""Point d'entrée de Sentinel.

    python main.py              # lance la fenêtre
    python main.py --minimized  # démarre réduit dans la zone de notification
    python main.py --classic    # ancienne interface (fenêtre Tk) au lieu de la nouvelle interface web
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import queue
import sys


def _message_box(title: str, text: str) -> None:
    """Petite boîte de dialogue Windows (fonctionne même sans console)."""
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)
    else:
        print(f"{title}: {text}", file=sys.stderr)


def _setup_logging() -> None:
    from sentinel.config import data_dir

    handler = logging.handlers.RotatingFileHandler(
        data_dir() / "sentinel.log", maxBytes=500_000, backupCount=2, encoding="utf-8")
    handlers: list[logging.Handler] = [handler]
    if sys.stderr is not None and not getattr(sys, "frozen", False):
        handlers.append(logging.StreamHandler(sys.stderr))   # mode dev : erreurs visibles dans le terminal
    logging.basicConfig(
        level=logging.INFO, handlers=handlers,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    def _excepthook(exc_type, exc, tb):
        logging.getLogger("sentinel").critical("Exception non gérée", exc_info=(exc_type, exc, tb))
    sys.excepthook = _excepthook


def main() -> int:
    parser = argparse.ArgumentParser(description="Sentinel - assistant vocal")
    parser.add_argument("--minimized", action="store_true",
                        help="démarre réduit (zone de notification)")
    parser.add_argument("--classic", action="store_true",
                        help="utilise l'ancienne interface au lieu de la nouvelle interface web")
    args = parser.parse_args()

    _setup_logging()
    log = logging.getLogger("sentinel.main")

    from sentinel.system import acquire_single_instance
    mutex = acquire_single_instance()          # doit rester référencé jusqu'à la fin
    if mutex is None:
        _message_box("Sentinel", "Sentinel est déjà en cours d'exécution.\n"
                                 "Cherchez son icône près de l'horloge.")
        return 0

    try:
        from sentinel.assistant import Assistant
        from sentinel.config import Config

        cfg = Config()
        from sentinel.ui import theme
        theme.apply(cfg["theme"], cfg["custom_bg"])        # doit précéder l'import de l'interface
        from sentinel.ui.app import SentinelApp
        ui_queue: "queue.Queue" = queue.Queue()
        assistant = Assistant(cfg, ui_queue)

        web = None
        if not args.classic and cfg["ui"] == "web":
            from sentinel.webui.window import find_browser
            if find_browser():
                from sentinel.webui.controller import WebController
                tk_queue: "queue.Queue" = queue.Queue()      # événements pour la fenêtre classique (réglages avancés)
                web = WebController(cfg, assistant, ui_queue, tk_queue)
            else:
                log.warning("Edge / Chrome introuvable : ancienne interface utilisée")

        if web:
            app = SentinelApp(cfg, assistant, tk_queue, start_hidden=True)   # fenêtre classique cachée
            app.web = web
            web.start()
            assistant.start()
            if not args.minimized:
                app.after(300, web.open_window)
        else:
            app = SentinelApp(cfg, assistant, ui_queue, start_hidden=args.minimized)
            assistant.start()
        log.info("Sentinel démarré")
        app.mainloop()
        log.info("Sentinel arrêté proprement")
        return 0
    except Exception as exc:
        log.exception("Erreur fatale")
        _message_box("Sentinel - erreur",
                     f"Une erreur fatale est survenue :\n\n{type(exc).__name__}: {exc}\n\n"
                     "Détails complets dans %APPDATA%\\Sentinel\\sentinel.log")
        return 1
    finally:
        del mutex


if __name__ == "__main__":
    sys.exit(main())
