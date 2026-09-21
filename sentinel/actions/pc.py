"""Actions sur le PC : fermer une application, veille, verrouillage, capture d'écran,
changement de fenêtre, luminosité de l'écran.

Rien ici n'utilise d'API payante : PowerShell / WMI, `taskkill`, Pillow et SendInput.
"""
from __future__ import annotations

import csv
import datetime
import io
import logging
import subprocess
import sys
import threading
from difflib import SequenceMatcher
from pathlib import Path

from ..nlu import normalize
from ..replies import R
from .keyboard import send_combo

log = logging.getLogger("sentinel.pc")
CREATE_NO_WINDOW = 0x08000000

# Processus qu'on refuse de fermer par la voix (système, ou Sentinel lui-même).
PROTECTED = {
    "system", "registry", "smss", "csrss", "wininit", "winlogon", "services", "lsass", "svchost", "dwm",
    "explorer", "fontdrvhost", "sihost", "taskhostw", "ctfmon", "conhost", "runtimebroker", "audiodg",
    "spoolsv", "dllhost", "wudfhost", "searchhost", "startmenuexperiencehost", "shellexperiencehost",
    "textinputhost", "securityhealthservice", "msmpeng", "nissrv", "memcompression",
    "python", "pythonw", "sentinel",
}

# Nom prononcé -> début possible du nom de processus (les alias perso .exe sont ajoutés automatiquement).
KNOWN = {
    "chrome": "chrome", "google chrome": "chrome", "edge": "msedge", "firefox": "firefox", "brave": "brave",
    "opera": "opera", "discord": "discord", "spotify": "spotify", "steam": "steam", "epic": "epicgameslauncher",
    "word": "winword", "excel": "excel", "powerpoint": "powerpnt", "outlook": "outlook", "teams": "teams",
    "vlc": "vlc", "obs": "obs64", "notepad": "notepad", "bloc notes": "notepad", "paint": "mspaint",
    "calculatrice": "calculator", "gestionnaire des taches": "taskmgr", "telegram": "telegram",
    "whatsapp": "whatsapp", "twitch": "twitch", "minecraft": "javaw", "code": "code",
}


# --------------------------------------------------------------------------- #
# Processus en cours (fonctions pures : testables sans Windows)
# --------------------------------------------------------------------------- #
def parse_tasklist(text: str) -> dict[str, list[str]]:
    """Sortie de `tasklist /v /fo csv /nh` -> {nom_image_en_minuscules: [titres de fenêtres]}."""
    procs: dict[str, list[str]] = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2 or not row[0]:
            continue
        image = row[0].strip().lower()
        title = row[8].strip() if len(row) > 8 else ""
        if title.upper() in ("N/A", "N/D", "AUCUN", "INDISPONIBLE", "N/A "):
            title = ""
        procs.setdefault(image, [])
        if title:
            procs[image].append(title)
    return procs


def _stem(image: str) -> str:
    return image[:-4] if image.endswith(".exe") else image


def _compact(text: str) -> str:
    return normalize(text).replace(" ", "")


def score(spoken: str, image: str, titles: list[str], hint: str | None = None) -> float:
    q, s = _compact(spoken), _compact(_stem(image))
    if not q or not s:
        return 0.0
    if hint and _compact(hint):
        if s == _compact(hint):
            return 1.0
        if s.startswith(_compact(hint)):
            return 0.95
    if q == s:
        return 1.0
    best = SequenceMatcher(None, q, s).ratio()
    if len(q) >= 3 and (q in s or (len(s) >= 4 and s in q)):
        best = max(best, 0.9)
    if len(q) >= 4 and any(q in _compact(t) for t in titles):
        best = max(best, 0.8)
    return best


def pick_process(spoken: str, procs: dict[str, list[str]], extra_hints: dict[str, str] | None = None,
                 threshold: float = 0.8) -> str | None:
    """Nom d'image (ex. « discord.exe ») qui correspond le mieux à ce qu'on a dit, sinon None."""
    hints = dict(KNOWN)
    hints.update(extra_hints or {})
    key = normalize(spoken)
    hint = hints.get(key)
    best, best_score = None, 0.0
    for image, titles in procs.items():
        sc = score(spoken, image, titles, hint)
        # à égalité, on préfère le processus qui possède une fenêtre visible
        if sc > best_score or (sc == best_score and best is not None and titles and not procs[best]):
            best, best_score = image, sc
    return best if best_score >= threshold else None


# --------------------------------------------------------------------------- #
class PcControl:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self._brightness_backend: str | None = None

    # ------------------------------------------------------------------ outils
    @staticmethod
    def _run(cmd: list[str], timeout: float = 10) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, capture_output=True, timeout=timeout,
                              creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0)

    @staticmethod
    def _decode(raw: bytes) -> str:
        for enc in ("oem", "utf-8", "cp1252"):
            try:
                return raw.decode(enc)
            except (LookupError, UnicodeDecodeError):
                continue
        return raw.decode("utf-8", "replace")

    # ----------------------------------------------------------- fermer une appli
    def _alias_hints(self) -> dict[str, str]:
        hints = {}
        for spoken, target in self.cfg["app_aliases"].items():
            t = str(target).strip().strip('"')
            if t.lower().endswith(".exe"):
                hints[normalize(spoken)] = Path(t).stem
        return hints

    def close_app(self, name: str, force: bool = False) -> str:
        if not name:
            return R(self.cfg, "close_ask")
        try:
            out = self._run(["tasklist", "/v", "/fo", "csv", "/nh"], timeout=20)
            procs = parse_tasklist(self._decode(out.stdout))
        except Exception:
            log.exception("liste des processus indisponible")
            return R(self.cfg, "error")
        image = pick_process(name, procs, self._alias_hints())
        if image is None:
            return R(self.cfg, "close_none", name=name)
        stem = _stem(image)
        own = Path(sys.executable).stem.lower()
        if stem in PROTECTED or stem == own:
            return R(self.cfg, "close_protected", name=name)
        cmd = ["taskkill", "/IM", image] + (["/F"] if force else [])
        try:
            res = self._run(cmd)
        except Exception:
            log.exception("taskkill impossible")
            return R(self.cfg, "error")
        log.info("taskkill %s -> code %s", image, res.returncode)
        if res.returncode == 0:
            return R(self.cfg, "close_app", name=name)
        return R(self.cfg, "close_refused", name=name)

    def close_window(self) -> str:
        send_combo("alt+f4")
        return R(self.cfg, "close_window")

    def close_tab(self) -> str:
        send_combo("ctrl+w")
        return R(self.cfg, "tab_close")

    # ------------------------------------------------------- veille / verrouillage
    def sleep(self) -> str:
        def go() -> None:
            try:   # (si l'hibernation est activée dans Windows, c'est elle qui est utilisée)
                subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                               creationflags=CREATE_NO_WINDOW, timeout=30)
            except Exception:
                log.exception("mise en veille impossible")

        threading.Timer(4.0, go).start()      # laisse le temps de prononcer la réponse
        return R(self.cfg, "sleep")

    def lock(self) -> str:
        import ctypes
        ctypes.windll.user32.LockWorkStation()
        return R(self.cfg, "lock")

    # ------------------------------------------------------------------ fenêtres
    def window_switch(self) -> str:
        send_combo("alt+tab")
        return R(self.cfg, "window_switch")

    def desktop(self) -> str:
        send_combo("win+d")
        return R(self.cfg, "desktop")

    # ------------------------------------------------------------ capture d'écran
    @staticmethod
    def _pictures_dir() -> Path:
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(0, 0x27, 0, 0, buf) == 0 and buf.value:   # CSIDL_MYPICTURES
                return Path(buf.value)
        except Exception:
            pass
        for name in ("Pictures", "Images"):
            if (Path.home() / name).is_dir():
                return Path.home() / name
        return Path.home()

    def screenshot(self) -> str:
        try:
            import ctypes
            try:
                ctypes.windll.user32.SetProcessDPIAware()      # capture en pleine résolution
            except Exception:
                pass
            from PIL import ImageGrab

            folder = Path(self.cfg["screenshot_dir"]) if self.cfg["screenshot_dir"] else self._pictures_dir() / "Sentinel"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"Capture_{datetime.datetime.now():%Y-%m-%d_%H-%M-%S}.png"
            img = ImageGrab.grab(all_screens=True)
            img.save(path)
            log.info("capture enregistrée : %s", path)
            self._to_clipboard(img)
        except Exception:
            log.exception("capture d'écran impossible")
            return R(self.cfg, "screenshot_fail")
        return R(self.cfg, "screenshot")

    @staticmethod
    def _to_clipboard(img) -> None:
        """Copie aussi la capture dans le presse-papiers (Ctrl+V dans Discord, Paint…). Facultatif."""
        try:
            import win32clipboard
            buf = io.BytesIO()
            img.convert("RGB").save(buf, "BMP")
            data = buf.getvalue()[14:]          # on retire l'en-tête de fichier BMP
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            log.debug("copie dans le presse-papiers impossible", exc_info=True)

    # ------------------------------------------------------------------ luminosité
    def _powershell(self, script: str) -> subprocess.CompletedProcess:
        return self._run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=15)

    def _get_wmi(self) -> int | None:
        res = self._powershell(
            "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness | "
            "Select-Object -First 1).CurrentBrightness")
        text = self._decode(res.stdout).strip()
        return int(text) if res.returncode == 0 and text.isdigit() else None

    def _set_wmi(self, pct: int) -> bool:
        res = self._powershell(
            "$m = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods | Select-Object -First 1; "
            "if (-not $m) { exit 3 }; "
            f"Invoke-CimMethod -InputObject $m -MethodName WmiSetBrightness -Arguments @{{Timeout=1; Brightness=[byte]{int(pct)}}} | Out-Null")
        return res.returncode == 0

    @staticmethod
    def _get_ddc() -> int | None:          # écrans externes (module facultatif « monitorcontrol »)
        from monitorcontrol import get_monitors
        for mon in get_monitors():
            with mon:
                return int(mon.get_luminance())
        return None

    @staticmethod
    def _set_ddc(pct: int) -> bool:
        from monitorcontrol import get_monitors
        done = False
        for mon in get_monitors():
            try:
                with mon:
                    mon.set_luminance(int(pct))
                done = True
            except Exception:
                log.debug("écran DDC/CI ignoré", exc_info=True)
        return done

    def get_brightness(self) -> int | None:
        for backend, fn in (("wmi", self._get_wmi), ("ddc", self._get_ddc)):
            if self._brightness_backend not in (None, backend):
                continue
            try:
                value = fn()
            except Exception:
                log.debug("lecture luminosité %s impossible", backend, exc_info=True)
                continue
            if value is not None:
                self._brightness_backend = backend
                return value
        return None

    def set_brightness(self, pct: int) -> bool:
        pct = max(0, min(100, int(pct)))
        order = [("wmi", self._set_wmi), ("ddc", self._set_ddc)]
        if self._brightness_backend:
            order = [b for b in order if b[0] == self._brightness_backend] or order
        for backend, fn in order:
            try:
                if fn(pct):
                    self._brightness_backend = backend
                    return True
            except Exception:
                log.debug("réglage luminosité %s impossible", backend, exc_info=True)
        return False

    def brightness_set(self, pct: int) -> str:
        return R(self.cfg, "brightness_set", p=pct) if self.set_brightness(pct) else R(self.cfg, "brightness_unsupported")

    def brightness_change(self, direction: int, amount: int | None) -> str:
        step = amount if amount is not None else int(self.cfg["brightness_step"])
        current = self.get_brightness()
        if current is None:
            return R(self.cfg, "brightness_unsupported")
        target = max(0, min(100, current + direction * step))
        return R(self.cfg, "brightness_change", p=target) if self.set_brightness(target) else R(self.cfg, "brightness_unsupported")

    def brightness_describe(self) -> str:
        current = self.get_brightness()
        return R(self.cfg, "brightness_get", p=current) if current is not None else R(self.cfg, "brightness_unsupported")


__all__ = ["PcControl", "parse_tasklist", "pick_process"]
