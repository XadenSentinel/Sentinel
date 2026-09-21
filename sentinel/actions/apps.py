"""Lancement de n'importe quelle application ou jeu.

Sources indexées au démarrage (en tâche de fond) :
  1. tes alias personnels (onglet Applications)
  2. les jeux Steam installés (lecture des appmanifest_*.acf)
  3. les jeux Epic Games installés (manifestes du lanceur)
  4. TOUT le menu Démarrer (PowerShell Get-StartApps : Win32 + Store)
  5. les raccourcis du Bureau

Le nom prononcé est comparé de façon approximative (« fortnaïte » -> Fortnite).
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

from ..nlu import normalize
from ..replies import R
from .scan import ExeScanner

log = logging.getLogger("sentinel.apps")
CREATE_NO_WINDOW = 0x08000000

BUILTIN = {
    "calculatrice": "calc.exe",
    "bloc notes": "notepad.exe",
    "paint": "mspaint.exe",
    "explorateur": "explorer.exe",
    "explorateur de fichiers": "explorer.exe",
    "gestionnaire des taches": "taskmgr.exe",
    "invite de commandes": "cmd.exe",
    "parametres": "ms-settings:",
    "panneau de configuration": "control.exe",
    "youtube": "https://www.youtube.com",
    "netflix": "https://www.netflix.com",
    "twitch": "https://www.twitch.tv",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "chat gpt": "https://chatgpt.com",
}

Entry = tuple[str, str, str]  # (nom, type, cible)


class AppIndex:
    def __init__(self, cfg, on_indexed: Callable[[int], None] | None = None) -> None:
        self.cfg = cfg
        self.on_indexed = on_indexed
        self.entries: list[Entry] = []
        self.scanner = ExeScanner(cfg)
        self._busy = threading.Lock()

    # ------------------------------------------------------------ indexation
    def refresh_async(self, rescan: bool = False) -> None:
        threading.Thread(target=self.refresh, args=(rescan,), daemon=True, name="sentinel-index").start()

    def refresh(self, rescan: bool = False) -> None:
        """1) sources rapides (Steam, Epic, menu Démarrer, Bureau) -> utilisables tout de suite ;
        2) analyse complète des .exe du PC (cache de 12 h, sauf « Réindexer »)."""
        if not self._busy.acquire(blocking=False):
            return                                                # déjà en cours
        try:
            fast: list[Entry] = []
            for source in (self._steam, self._epic, self._start_apps, self._desktop_links):
                try:
                    fast += source()
                except Exception:
                    log.exception("indexation %s échouée", source.__name__)
            exes = self.scanner.entries if self.scanner.entries else []
            self.entries = fast + exes
            self._announce()
            if rescan or not self.scanner.load_cache():
                try:
                    self.scanner.scan(progress=lambda n: None)
                except Exception:
                    log.exception("analyse des programmes échouée")
            self.entries = fast + self.scanner.entries
            log.info("%d applications indexées (dont %d programmes .exe)", len(self.entries), len(self.scanner.entries))
            self._announce()
        finally:
            self._busy.release()

    def _announce(self) -> None:
        if self.on_indexed:
            self.on_indexed(len(self.entries))

    @staticmethod
    def _start_apps() -> list[Entry]:
        script = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=60, creationflags=CREATE_NO_WINDOW,
        )
        raw = out.stdout.decode("utf-8-sig", "ignore").strip()
        data = json.loads(raw) if raw else []
        if isinstance(data, dict):
            data = [data]
        return [(d["Name"], "startapp", d["AppID"]) for d in data if d.get("Name") and d.get("AppID")]

    @staticmethod
    def _steam() -> list[Entry]:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                steam = Path(winreg.QueryValueEx(key, "SteamPath")[0])
        except OSError:
            return []
        libraries = [steam]
        vdf = steam / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            text = vdf.read_text(encoding="utf-8", errors="ignore")
            libraries += [Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', text)]
        found: list[Entry] = []
        for lib in dict.fromkeys(libraries):
            for acf in (lib / "steamapps").glob("appmanifest_*.acf"):
                t = acf.read_text(encoding="utf-8", errors="ignore")
                appid = re.search(r'"appid"\s+"(\d+)"', t)
                name = re.search(r'"name"\s+"([^"]+)"', t)
                if appid and name and "redistributable" not in name.group(1).lower():
                    found.append((name.group(1), "uri", f"steam://rungameid/{appid.group(1)}"))
        return found

    @staticmethod
    def _epic() -> list[Entry]:
        manifests = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Epic/EpicGamesLauncher/Data/Manifests"
        found: list[Entry] = []
        for item in manifests.glob("*.item"):
            try:
                d = json.loads(item.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
            name, app = d.get("DisplayName"), d.get("AppName")
            if not (name and app):
                continue
            ns, cat = d.get("CatalogNamespace"), d.get("CatalogItemId")
            ident = f"{ns}%3A{cat}%3A{app}" if ns and cat else app
            found.append((name, "uri", f"com.epicgames.launcher://apps/{ident}?action=launch&silent=true"))
        return found

    @staticmethod
    def _desktop_links() -> list[Entry]:
        folders = [Path.home() / "Desktop", Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop"]
        if os.environ.get("OneDrive"):
            folders.append(Path(os.environ["OneDrive"]) / "Desktop")
        found: list[Entry] = []
        for folder in folders:
            for pattern in ("*.lnk", "*.url"):
                found += [(p.stem, "file", str(p)) for p in folder.glob(pattern)]
        return found

    # -------------------------------------------------------------- recherche
    def _candidates(self) -> list[Entry]:
        aliases = [(k, "alias", v) for k, v in self.cfg["app_aliases"].items()]
        builtin = [(k, "alias", v) for k, v in BUILTIN.items()]
        return aliases + builtin + self.entries

    @staticmethod
    def _score(query: str, name: str) -> float:
        q, n = normalize(query), normalize(name)
        if not q or not n:
            return 0.0
        if q == n:
            return 1.0
        if re.search(rf"\b{re.escape(q)}\b", n):
            return 0.85 + 0.1 * len(q) / len(n)        # « code » -> « Visual Studio Code »
        if n in q:
            return 0.8
        qc, nc = q.replace(" ", ""), n.replace(" ", "")
        if len(qc) >= 4 and nc.startswith(qc):                  # « fortnite » -> « FortniteClient »
            return 0.8 + 0.1 * len(qc) / len(nc)
        return SequenceMatcher(None, qc, nc).ratio()

    def find(self, spoken: str, min_score: float = 0.62) -> Entry | None:
        best, best_score = None, 0.0
        for entry in self._candidates():
            score = self._score(spoken, entry[0])
            if entry[1] == "exe":                                # programme trouvé par analyse : seuil plus strict
                if score < max(0.75, min_score):
                    continue
                score -= 0.03                                    # à égalité, un raccourci du menu Démarrer gagne
            elif entry[1] == "alias":
                score += 0.05
            if score > best_score:
                best, best_score = entry, score
        return best if best_score >= min_score else None

    # ---------------------------------------------------------------- lancement
    def open(self, spoken: str) -> str:
        if not spoken:
            return R(self.cfg, "app_ask")
        entry = self.find(spoken)
        if entry is None:
            return R(self.cfg, "app_missing", name=spoken)
        name, kind, target = entry
        try:
            self._launch(kind, target)
        except Exception as exc:
            log.exception("lancement de %s impossible", name)
            return R(self.cfg, "app_fail", name=name, err=exc)
        return R(self.cfg, "app_open", name=name)

    @staticmethod
    def _launch(kind: str, target: str) -> None:
        if kind == "startapp":
            subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + target])
        elif kind == "exe":
            try:                                                 # comme un double-clic : Windows gère les avertissements / droits admin
                os.startfile(target, cwd=str(Path(target).parent))
            except TypeError:
                os.startfile(target)
        else:
            try:
                os.startfile(target)                  # URL, steam://, ms-settings:, chemin, calc.exe...
            except OSError:
                subprocess.Popen(target, shell=True)  # commande libre saisie dans tes alias
