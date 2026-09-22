"""Ouvre l'interface dans une fenêtre d'application (sans barre d'adresse ni onglets) avec Edge ou Chrome."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("sentinel.window")


def find_browser() -> str | None:
    """Edge en priorité (présent sur tous les Windows 10/11), puis Chrome, Brave, Chromium."""
    if sys.platform == "win32":
        roots = [os.environ.get(v) for v in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
        rels = [r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe",
                r"BraveSoftware\Brave-Browser\Application\brave.exe", r"Chromium\Application\chrome.exe"]
        for rel in rels:
            for root in filter(None, roots):
                path = Path(root) / rel
                if path.exists():
                    return str(path)
        return None
    for name in ("microsoft-edge", "google-chrome", "chromium", "chromium-browser", "brave-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def launch_app_window(exe: str, url: str, profile_dir: Path, size: tuple[int, int] = (1280, 800)) -> subprocess.Popen:
    """Profil dédié : la fenêtre est indépendante de ton navigateur habituel (pas de session, pas d'extensions)."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    args = [exe, f"--app={url}", f"--user-data-dir={profile_dir}", f"--window-size={size[0]},{size[1]}",
            "--no-first-run", "--no-default-browser-check", "--disable-extensions", "--disable-sync",
            "--hide-crash-restore-bubble", "--disable-features=Translate"]
    log.info("ouverture de la fenêtre : %s", Path(exe).name)
    return subprocess.Popen(args, close_fds=True)
