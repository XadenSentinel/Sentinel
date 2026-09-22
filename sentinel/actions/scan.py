"""Analyse de l'ordinateur : programmes (.exe) de tous les disques + dossiers et fichiers personnels.

Sentinel ne fait qu'OUVRIR ce qu'il trouve, exactement comme un double-clic :
  - il ne désactive ni Windows Defender, ni SmartScreen, ni le contrôle de compte (UAC) : si un programme
    demande les droits administrateur, Windows affiche sa fenêtre habituelle et c'est toi qui valides ;
  - il ne supprime, ne déplace et ne modifie aucun fichier ;
  - il refuse d'ouvrir des scripts (.bat, .ps1, .vbs…) trouvés par la recherche de fichiers.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import re
import subprocess
import threading
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Iterator

from ..config import data_dir
from ..nlu import normalize
from ..replies import R

log = logging.getLogger("sentinel.scan")

# Dossiers qu'on n'explore jamais (système, caches, dépendances de développement…)
SKIP_DIRS = {
    "windows", "$recycle.bin", "system volume information", "recovery", "$windows.~bt", "$windows.~ws",
    "config.msi", "msocache", "perflogs", "winsxs", "windowsapps", "node_modules", ".git", "__pycache__",
    "site-packages", "temp", "tmp", "cache", "caches", "code cache", "gpucache", "crashpad", "crash reports",
    "installer", "redist", "_commonredist", "vcredist", "directx", "dotnet", "package cache", "common files",
    "windows defender", "windows defender advanced threat protection", "windows nt", "windowspowershell",
    "reference assemblies", "microsoft.net", ".gradle", ".cache", ".npm", ".nuget", "$sysreset",
}
# Noms de programmes qui ne sont pas des applications (désinstallateurs, aides, services…)
_NOISE = re.compile(
    r"^(unins\w*|uninstall\w*|setup\w*|install\w*|update\w*|updater\w*|autoupdate\w*|crash\w*|report\w*|"
    r"vc_?redist\w*|vcredist\w*|dxsetup|dxwebsetup|dotnet\w*|ndp\w*|notification\w*|elevat\w*|cef\w*|"
    r"\w*_proxy|\w*helper\w*|\w*_service|\w*service_?host|createdump|7z\w*|jabswitch|\w*handler|\w*broker|"
    r"python\w*|pip\w*|node|npm|java|jre\w*|conhost|wsl\w*|msedgewebview2|\w*crashpad\w*|\w*updater\w*)$"
)
_GENERIC = {"launcher", "app", "main", "start", "run", "game", "client", "bin", "application", "program",
            "play", "engine", "loader", "launch"}
_GENERIC_DIRS = {"bin", "binaries", "win64", "win32", "x64", "x86", "release", "debug", "app", "client",
                 "game", "program files", "program files (x86)", "programs", "win", "windows", "shipping"}
BLOCKED_EXT = {".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".hta",
               ".scr", ".pif", ".com", ".reg", ".msi", ".msp", ".jar", ".dll", ".sys"}
SKIP_FILE_EXT = {".dll", ".sys", ".tmp", ".log", ".ini", ".dat", ".cache", ".bak", ".db", ".lock", ".exe",
                 ".pyc", ".class", ".o", ".obj", ".ldb", ".manifest", ".mui"}

KNOWN_FOLDERS = {
    "telechargements": "shell:Downloads", "telechargement": "shell:Downloads", "downloads": "shell:Downloads",
    "documents": "shell:Personal", "mes documents": "shell:Personal",
    "images": "shell:My Pictures", "photos": "shell:My Pictures", "mes images": "shell:My Pictures",
    "musique": "shell:My Music", "ma musique": "shell:My Music",
    "videos": "shell:My Video", "mes videos": "shell:My Video",
    "bureau": "shell:Desktop", "corbeille": "shell:RecycleBinFolder",
    "ce pc": "shell:MyComputerFolder", "mon ordinateur": "shell:MyComputerFolder", "mon pc": "shell:MyComputerFolder",
}


# --------------------------------------------------------------------------- #
# Outils
# --------------------------------------------------------------------------- #
def fixed_drives() -> list[str]:
    """Disques durs internes (C:\\, D:\\…). Vide hors Windows."""
    if os.name != "nt":
        return []
    k32 = ctypes.windll.kernel32
    bits, out = k32.GetLogicalDrives(), []
    for i in range(26):
        if bits >> i & 1:
            root = f"{chr(65 + i)}:\\"
            if k32.GetDriveTypeW(root) == 3:                    # DRIVE_FIXED
                out.append(root)
    return out


def walk_files(root: str, max_depth: int, deadline: float, want_dirs: bool = False) -> Iterator[tuple[str, bool]]:
    """Parcourt un dossier (sans suivre les liens), renvoie (chemin, est_un_dossier)."""
    stack = [(root, 0)]
    n = 0
    while stack:
        path, depth = stack.pop()
        try:
            with os.scandir(path) as it:
                entries = list(it)
        except OSError:
            continue
        n += 1
        if n % 200 == 0:
            time.sleep(0)                                       # rend la main : analyse discrète
            if time.monotonic() > deadline:
                return
        for e in entries:
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_dir:
                low = e.name.lower()
                if low in SKIP_DIRS or low.startswith("$"):
                    continue
                if want_dirs:
                    yield e.path, True
                if depth < max_depth:
                    stack.append((e.path, depth + 1))
            else:
                yield e.path, False


def _pretty(stem: str) -> str:
    stem = re.sub(r"[_\-.]+", " ", stem)
    stem = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", stem)
    return re.sub(r"\s+", " ", stem).strip()


def exe_display_name(path: str) -> str | None:
    """Nom « parlable » d'un .exe (None si c'est du bruit : désinstallateur, aide, service…)."""
    p = Path(path)
    stem = p.stem
    low = stem.lower()
    if _NOISE.match(low):
        return None
    norm = normalize(stem).replace(" ", "")
    if low in _GENERIC or "shipping" in low or norm in _GENERIC:
        for parent in p.parents:
            if parent.name and parent.name.lower() not in _GENERIC_DIRS and not re.fullmatch(r"[a-z]:\\?", parent.name.lower()):
                return _pretty(parent.name)
        return None
    return _pretty(stem)


# --------------------------------------------------------------------------- #
# Programmes (.exe)
# --------------------------------------------------------------------------- #
class ExeScanner:
    """Liste tous les programmes installés sur le PC (avec cache sur disque)."""

    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.entries: list[tuple[str, str, str]] = []           # (nom, "exe", chemin)
        self._cache_file = data_dir() / "exe_index.json"

    def roots(self) -> list[tuple[str, int]]:
        env = os.environ
        roots: list[tuple[str, int]] = []
        for var in ("ProgramFiles", "ProgramFiles(x86)"):
            if env.get(var):
                roots.append((env[var], 4))
        local = env.get("LOCALAPPDATA")
        if local:
            roots += [(str(Path(local) / "Programs"), 4), (local, 3)]
        if env.get("APPDATA"):
            roots.append((env["APPDATA"], 3))
        home = Path.home()
        roots += [(str(home / "Desktop"), 3), (str(home / "Downloads"), 3)]
        if self.cfg["scan_full_disk"]:
            roots += [(d, 6) for d in fixed_drives()]
        roots += [(p.strip(), 6) for p in self.cfg["scan_extra_paths"] if str(p).strip()]
        return roots

    def load_cache(self, max_age_hours: float = 12.0) -> bool:
        try:
            data = json.loads(self._cache_file.read_text(encoding="utf-8"))
            if data.get("full") != bool(self.cfg["scan_full_disk"]) or time.time() - data["built"] > max_age_hours * 3600:
                return False
            self.entries = [(n, "exe", p) for n, p in data["entries"] if os.path.exists(p)]
            return bool(self.entries)
        except Exception:
            return False

    def scan(self, budget_seconds: float = 240.0, progress: Callable[[int], None] | None = None) -> list[tuple[str, str, str]]:
        deadline = time.monotonic() + budget_seconds
        found: dict[str, tuple[str, str]] = {}                   # chemin (minuscule) -> (nom, chemin)
        for root, depth in self.roots():
            if not os.path.isdir(root):
                continue
            for path, is_dir in walk_files(root, depth, deadline):
                if is_dir or not path.lower().endswith(".exe") or path.lower() in found:
                    continue
                name = exe_display_name(path)
                if name:
                    found[path.lower()] = (name, path)
            if progress:
                progress(len(found))
            if time.monotonic() > deadline:
                log.warning("analyse des programmes interrompue (temps maximal atteint)")
                break
        best: dict[str, tuple[str, str]] = {}                    # un seul programme par nom : le chemin le moins profond
        for name, path in found.values():
            key = normalize(name)
            if key not in best or path.count("\\") + path.count("/") < best[key][1].count("\\") + best[key][1].count("/"):
                best[key] = (name, path)
        self.entries = [(n, "exe", p) for n, p in best.values()]
        try:
            self._cache_file.write_text(json.dumps({"built": time.time(), "full": bool(self.cfg["scan_full_disk"]),
                                                    "entries": [[n, p] for n, _, p in self.entries]}), encoding="utf-8")
        except OSError:
            log.debug("cache des programmes non écrit", exc_info=True)
        log.info("%d programmes (.exe) trouvés", len(self.entries))
        return self.entries


# --------------------------------------------------------------------------- #
# Fichiers et dossiers personnels
# --------------------------------------------------------------------------- #
class FileFinder:
    MAX_ENTRIES = 150_000          # plafond volontairement modéré : au-delà, ça pèse sur la mémoire pour peu de gain

    def __init__(self, cfg, on_indexed: Callable[[int], None] | None = None) -> None:
        self.cfg = cfg
        self.on_indexed = on_indexed
        self.items: list[tuple[str, str, bool, int]] = []       # (nom normalisé, chemin, dossier?, profondeur)
        self._lock = threading.Lock()

    def roots(self) -> list[str]:
        home = Path.home()
        roots = [str(home / n) for n in ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos")]
        for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
            if os.environ.get(var):
                roots.append(os.environ[var])
        roots += [p.strip() for p in self.cfg["scan_extra_paths"] if str(p).strip()]
        return list(dict.fromkeys(r for r in roots if os.path.isdir(r)))

    def refresh_async(self, delay: float = 15.0) -> None:
        threading.Thread(target=self.refresh, args=(delay,), daemon=True, name="sentinel-files").start()

    def refresh(self, delay: float = 0.0) -> None:
        time.sleep(delay)                                        # laisse d'abord démarrer l'appli
        items: list[tuple[str, str, bool, int]] = []
        deadline = time.monotonic() + 180
        for root in self.roots():
            base = root.count("\\") + root.count("/")
            for path, is_dir in walk_files(root, 6, deadline, want_dirs=True):
                if not is_dir and Path(path).suffix.lower() in SKIP_FILE_EXT:
                    continue
                name = Path(path).name if is_dir else Path(path).stem
                items.append((normalize(name), path, is_dir, path.count("\\") + path.count("/") - base))
                if len(items) >= self.MAX_ENTRIES:
                    break
            if len(items) >= self.MAX_ENTRIES or time.monotonic() > deadline:
                break
        with self._lock:
            self.items = items
        log.info("%d fichiers et dossiers indexés", len(items))
        import gc
        gc.collect()                                              # libère la mémoire de travail du parcours
        if self.on_indexed:
            self.on_indexed(len(items))

    # ------------------------------------------------------------ recherche
    @staticmethod
    def _tokens(q: str) -> list[str]:
        return [t for t in normalize(q).split() if len(t) >= 2 and t not in ("le", "la", "les", "de", "du", "des", "mon", "ma", "mes")]

    def find(self, query: str, want_dir: bool | None, ext_hint: set[str] | None = None) -> str | None:
        toks = self._tokens(query)
        if not toks:
            return None
        with self._lock:
            items = self.items
        best, best_score = None, 0.0
        q = " ".join(toks)
        for name, path, is_dir, depth in items:
            if want_dir is not None and is_dir != want_dir:
                continue
            if ext_hint and not is_dir and Path(path).suffix.lower() not in ext_hint:
                continue
            if all(t in name for t in toks):
                score = 0.9 + 0.09 * min(1.0, len(q) / max(1, len(name))) - 0.01 * depth
            elif len(items) < 60_000 or name[:1] == q[:1]:
                score = SequenceMatcher(None, q, name).ratio() - 0.01 * depth if abs(len(name) - len(q)) <= max(6, len(q)) else 0.0
            else:
                continue
            if score > best_score:
                best, best_score = path, score
        return best if best_score >= 0.62 else None


def known_folder(query: str) -> str | None:
    q = normalize(query)
    q = re.sub(r"^(?:le |la |les |mon |ma |mes |l |dossier |du |de |des )+", "", q).strip()
    if q in KNOWN_FOLDERS:
        return KNOWN_FOLDERS[q]
    m = re.fullmatch(r"(?:disque|lecteur|volume)\s+([a-z])(?: deux points)?", q)
    if m:
        return f"{m.group(1).upper()}:\\"
    return None


def open_path(target: str) -> None:
    """Ouvre un dossier dans l'Explorateur, ou un fichier avec son programme par défaut (comme un double-clic)."""
    if target.startswith("shell:") or os.path.isdir(target):
        subprocess.Popen(["explorer.exe", target])
    else:
        os.startfile(target)                                     # noqa: S606  (ouverture normale de Windows)


class PathOpener:
    """« ouvre le dossier téléchargements », « ouvre le fichier facture »."""

    KINDS = {
        "dossier": (True, None), "repertoire": (True, None),
        "fichier": (False, None), "document": (False, None),
        "pdf": (False, {".pdf"}), "photo": (False, {".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif"}),
        "image": (False, {".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif", ".bmp"}),
        "video": (False, {".mp4", ".mkv", ".avi", ".mov", ".webm"}),
        "musique": (False, {".mp3", ".flac", ".wav", ".m4a", ".ogg"}),
    }

    def __init__(self, cfg, finder: FileFinder) -> None:
        self.cfg, self.finder = cfg, finder

    def open(self, kind: str | None, query: str) -> str:
        query = (query or "").strip()
        if not query:
            return R(self.cfg, "path_ask")
        target = known_folder(query) if kind in (None, "dossier", "repertoire") else None
        if target is None:
            want_dir, exts = self.KINDS.get(normalize(kind or ""), (None, None))
            target = self.finder.find(query, want_dir, exts)
        if target is None:
            return R(self.cfg, "path_missing", name=query)
        if Path(target).suffix.lower() in BLOCKED_EXT and not self.cfg["allow_scripts"]:
            return R(self.cfg, "path_blocked", name=Path(target).name)
        try:
            open_path(target)
        except Exception as exc:
            log.exception("ouverture impossible : %s", target)
            return R(self.cfg, "app_fail", name=query, err=exc)
        return R(self.cfg, "path_open", name=query)
