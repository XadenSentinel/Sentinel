"""Mises à jour de Sentinel depuis GitHub Releases.

Deux modes, choisis automatiquement :
  - .exe (PyInstaller) : télécharge le nouveau Sentinel.exe, vérifie son empreinte SHA-256, puis lance un petit
    script qui attend la fermeture de Sentinel, garde l'ancien exe en « Sentinel.old.exe », installe le nouveau
    et le relance ;
  - code source (python main.py) : télécharge le code de la version, le copie sur le projet (sans toucher au
    .venv), met à jour les dépendances (pip) et relance.
Tes réglages, ta mémoire d'apprentissage et tes connexions vivent dans %APPDATA%\\Sentinel : rien n'est perdu.

Sécurité : dépôt fixé dans le code, HTTPS obligatoire, téléchargements et redirections limités à GitHub, empreinte
SHA-256 exigée pour l'exe, protection contre les chemins piégés dans les zip, installation seulement après ton clic,
et retour à la version précédente possible. (L'empreinte protège contre un fichier corrompu ; la confiance dans le
dépôt, elle, dépend de la protection de ton compte GitHub : active la double authentification.)
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import UPDATE_REPO, __version__
from .config import data_dir, exe_dir, is_frozen

log = logging.getLogger("sentinel.updater")

ALLOWED_HOSTS = ("github.com", "githubusercontent.com")
API_BASE = "https://api.github.com"
EXE_ASSET = "Sentinel.exe"
SHA_ASSET = "Sentinel.exe.sha256"
SKIP_NAMES = {".venv", "venv", ".git", "__pycache__", "dist", "build", ".idea", ".vscode"}
Progress = Callable[[int, int], None]


class UpdateError(Exception):
    """Message destiné à l'utilisateur."""


@dataclass
class Release:
    version: str
    tag: str
    notes: str
    page: str
    exe_url: str = ""
    sha_url: str = ""
    zip_url: str = ""


def parse_version(text: str) -> tuple[int, int, int]:
    nums = [int(n) for n in re.findall(r"\d+", str(text))[:3]]
    return tuple(nums + [0] * (3 - len(nums)))  # type: ignore[return-value]


def is_newer(latest: str, current: str = __version__) -> bool:
    return parse_version(latest) > parse_version(current)


def _host_ok(url: str, allowed: tuple[str, ...]) -> bool:
    parts = urllib.parse.urlparse(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host == h or host.endswith("." + h) for h in allowed)


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse toute redirection qui sortirait de GitHub."""

    def __init__(self, allowed: tuple[str, ...], check: bool) -> None:
        self.allowed, self.check = allowed, check

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if self.check and not _host_ok(newurl, self.allowed):
            raise urllib.error.URLError(f"redirection refusée vers {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def swap_script(target: Path, new: Path, old: Path, pid: int, log_file: Path) -> str:
    """Script .bat : attend la fin de Sentinel, garde l'ancien exe, installe le nouveau, relance."""
    return f'''@echo off
chcp 65001 >nul
set "TARGET={target}"
set "NEW={new}"
set "OLD={old}"
powershell -NoProfile -WindowStyle Hidden -Command "try {{ Wait-Process -Id {pid} -Timeout 90 -ErrorAction Stop }} catch {{ }}"
set tries=0
:swap
set /a tries+=1
if exist "%OLD%" del /f /q "%OLD%" >nul 2>nul
move /y "%TARGET%" "%OLD%" >nul 2>nul
if errorlevel 1 goto retry
move /y "%NEW%" "%TARGET%" >nul 2>nul
if errorlevel 1 goto undo
start "" "%TARGET%"
exit /b 0
:undo
move /y "%OLD%" "%TARGET%" >nul 2>nul
goto fail
:retry
if %tries% GEQ 15 goto fail
ping -n 2 127.0.0.1 >nul
goto swap
:fail
echo La mise a jour a echoue (%date% %time%) > "{log_file}"
start "" "%TARGET%"
exit /b 1
'''


class Updater:
    def __init__(self, cfg, repo: str | None = None, api_base: str = API_BASE,
                 allowed_hosts: tuple[str, ...] = ALLOWED_HOSTS, root: Path | None = None) -> None:
        self.cfg = cfg
        self.repo = UPDATE_REPO if repo is None else repo
        self.api_base = api_base.rstrip("/")
        self.allowed = allowed_hosts
        self.root = Path(root) if root else exe_dir()
        self.work = data_dir() / "update"
        self._opener = urllib.request.build_opener(_SafeRedirect(allowed_hosts, allowed_hosts == ALLOWED_HOSTS))

    # ------------------------------------------------------------------ réseau
    @property
    def enabled(self) -> bool:
        return bool(self.repo)

    def _open(self, url: str, timeout: float = 20):
        if self.allowed == ALLOWED_HOSTS and not _host_ok(url, self.allowed):
            raise UpdateError("Adresse de téléchargement refusée (hors GitHub).")
        req = urllib.request.Request(url, headers={"User-Agent": f"Sentinel/{__version__}", "Accept": "application/vnd.github+json"})
        try:
            return self._opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise UpdateError("Aucune version publiée trouvée (dépôt introuvable, privé, ou sans Release).") from exc
            if exc.code == 403:
                raise UpdateError("GitHub limite les requêtes pour l'instant : réessaie dans quelques minutes.") from exc
            raise UpdateError(f"GitHub a répondu HTTP {exc.code}.") from exc
        except Exception as exc:
            raise UpdateError(f"Pas de connexion à GitHub ({exc}).") from exc

    def check(self) -> Release | None:
        """Retourne la version plus récente disponible, ou None si tu es à jour."""
        if not self.enabled:
            raise UpdateError("Aucun dépôt GitHub n'est configuré pour les mises à jour.")
        import json

        with self._open(f"{self.api_base}/repos/{self.repo}/releases/latest") as resp:
            data = json.loads(resp.read().decode("utf-8"))
        self.cfg["update_last_check"] = time.time()
        self.cfg.save()
        tag = str(data.get("tag_name", ""))
        assets = {a.get("name", ""): a.get("browser_download_url", "") for a in data.get("assets", [])}
        rel = Release(version=".".join(map(str, parse_version(tag))), tag=tag, notes=str(data.get("body") or "").strip(),
                      page=str(data.get("html_url", "")), exe_url=assets.get(EXE_ASSET, ""), sha_url=assets.get(SHA_ASSET, ""),
                      zip_url=str(data.get("zipball_url", "")))
        return rel if is_newer(rel.version) else None

    def _download(self, url: str, dest: Path, progress: Progress | None = None, expected_sha: str | None = None) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        digest = hashlib.sha256()
        with self._open(url, timeout=60) as resp, open(tmp, "wb") as out:
            total, done = int(resp.headers.get("Content-Length") or 0), 0
            while chunk := resp.read(1 << 16):
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if expected_sha and digest.hexdigest().lower() != expected_sha.lower():
            tmp.unlink(missing_ok=True)
            raise UpdateError("L'empreinte SHA-256 ne correspond pas : fichier corrompu ou modifié. Mise à jour annulée.")
        os.replace(tmp, dest)
        return dest

    # ------------------------------------------------------------------ installation
    def can_install(self, rel: Release) -> str:
        """'' si on peut installer, sinon la raison."""
        if is_frozen():
            if not rel.exe_url:
                return f"Cette version ne contient pas de {EXE_ASSET}."
            if not rel.sha_url:
                return f"Cette version n'a pas de fichier {SHA_ASSET} : installation refusée par sécurité."
        elif not rel.zip_url:
            return "Cette version ne contient pas de code source à installer."
        return ""

    def install(self, rel: Release, progress: Progress | None = None) -> None:
        """Télécharge et installe. Au retour, l'application doit se fermer : un script/redémarrage a déjà été lancé."""
        reason = self.can_install(rel)
        if reason:
            raise UpdateError(reason)
        self.work.mkdir(parents=True, exist_ok=True)
        if is_frozen():
            self._install_exe(rel, progress)
        else:
            self._install_source(rel, progress)

    def _install_exe(self, rel: Release, progress: Progress | None) -> None:
        with self._open(rel.sha_url) as resp:
            match = re.search(r"\b[0-9a-fA-F]{64}\b", resp.read(4096).decode("utf-8", "ignore"))
        if not match:
            raise UpdateError("Fichier d'empreinte illisible : installation refusée.")
        new = self._download(rel.exe_url, self.work / "Sentinel-new.exe", progress, match.group(0))
        self._launch_swap(new, Path(sys.executable).resolve())

    def _launch_swap(self, new: Path, target: Path) -> None:
        old = target.with_name(target.stem + ".old.exe")
        script = self.work / "apply_update.bat"
        script.write_text(swap_script(target, new, old, os.getpid(), self.work / "echec.txt"), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("_MEIPASS", "_PYI"))}      # indispensable avec PyInstaller
        subprocess.Popen(["cmd", "/c", str(script)], env=env, close_fds=True,
                         creationflags=0x08000000 | 0x00000200)             # sans fenêtre + processus indépendant

    def _install_source(self, rel: Release, progress: Progress | None) -> None:
        archive = self._download(rel.zip_url, self.work / "source.zip", progress)
        self.apply_source_zip(archive)
        from .system import restart_app
        restart_app()

    def apply_source_zip(self, archive: Path) -> None:
        """Copie le code d'un zip GitHub sur le projet (sauvegarde avant, pip après). Sans redémarrage."""
        self._backup_source()
        staging = Path(tempfile.mkdtemp(prefix="sentinel-update-", dir=self.work))
        try:
            with zipfile.ZipFile(archive) as z:
                names = [n for n in z.namelist() if n and not n.endswith("/")]
                if not names:
                    raise UpdateError("Archive vide.")
                prefix = names[0].split("/")[0] + "/" if all(n.split("/")[0] == names[0].split("/")[0] for n in names) else ""
                for member in names:
                    rel_path = member[len(prefix):] if prefix and member.startswith(prefix) else member
                    if not rel_path or Path(rel_path).parts[0] in SKIP_NAMES:
                        continue
                    dest = (staging / rel_path).resolve()
                    if not str(dest).startswith(str(staging.resolve()) + os.sep):
                        raise UpdateError("Archive refusée : chemin suspect.")
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(member) as src, open(dest, "wb") as out:
                        shutil.copyfileobj(src, out)
            if not (staging / "main.py").exists() or not (staging / "sentinel").is_dir():
                raise UpdateError("Cette archive ne ressemble pas à Sentinel : installation annulée.")
            shutil.copytree(staging, self.root, dirs_exist_ok=True)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        self._update_dependencies()

    def _update_dependencies(self) -> None:
        req = self.root / "requirements.txt"
        if not req.exists():
            return
        try:
            out = subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req)], capture_output=True, text=True,
                                 timeout=900, creationflags=0x08000000 if sys.platform == "win32" else 0)
            if out.returncode != 0:
                log.warning("pip a signalé un problème : %s", out.stderr[-400:])
        except Exception:
            log.exception("mise à jour des dépendances impossible")

    # ------------------------------------------------------------------ retour arrière
    def _backup_source(self) -> None:
        base = str(self.work / "backup")
        tmp = Path(tempfile.mkdtemp(prefix="bk-", dir=self.work))
        try:
            shutil.copytree(self.root / "sentinel", tmp / "sentinel", ignore=shutil.ignore_patterns("__pycache__"))
            for name in ("main.py", "requirements.txt"):
                if (self.root / name).exists():
                    shutil.copy2(self.root / name, tmp / name)
            (tmp / "VERSION.txt").write_text(__version__, encoding="utf-8")
            shutil.make_archive(base, "zip", tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def previous_version(self) -> str:
        """Version disponible pour un retour arrière ('' si aucune)."""
        if is_frozen():
            old = Path(sys.executable).resolve()
            return "précédente" if old.with_name(old.stem + ".old.exe").exists() else ""
        backup = self.work / "backup.zip"
        if backup.exists():
            try:
                with zipfile.ZipFile(backup) as z:
                    return z.read("VERSION.txt").decode("utf-8").strip()
            except Exception:
                return "précédente"
        return ""

    def rollback(self) -> None:
        """Revient à la version d'avant la dernière mise à jour, puis prépare le redémarrage."""
        if not self.previous_version():
            raise UpdateError("Aucune version précédente conservée.")
        if is_frozen():
            target = Path(sys.executable).resolve()
            old = target.with_name(target.stem + ".old.exe")
            swap = target.with_name(target.stem + ".rollback.exe")
            shutil.copy2(old, swap)                                   # le script installe cette copie et garde l'exe actuel
            self._launch_swap(swap, target)
        else:
            with zipfile.ZipFile(self.work / "backup.zip") as z:
                z.extractall(self.root)
            from .system import restart_app
            restart_app()
