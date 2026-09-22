"""Interagir avec les applications ouvertes : changer de fenêtre, taper, raccourcis, cliquer, ouvrir un site.

Garde-fous (l'IA passe par ici comme tes commandes vocales) :
  - saisie / raccourcis REFUSÉS si la fenêtre active est un terminal, l'éditeur du registre, une console
    d'administration… (on ne fait jamais taper une commande système par une IA) ;
  - seuls les raccourcis d'une liste blanche sont possibles (pas d'Alt+F4, de touche Windows, de Suppr…) ;
  - les clics par nom passent par « UI Automation » (comme un lecteur d'écran) et refusent tout ce qui est
    sensible (supprimer, payer, acheter, désinstaller, formater…) ;
  - les retours à la ligne ne sont jamais tapés (une messagerie enverrait le message) ;
  - Sentinel ne lit pas le contenu de tes fenêtres et n'agit qu'à ta demande.
"""
from __future__ import annotations

import ctypes
import logging
import os
import re
import sys
import time
import webbrowser
from ctypes import wintypes
from difflib import SequenceMatcher

from ..nlu import normalize
from ..replies import R
from .keyboard import send_combo, type_unicode

log = logging.getLogger("sentinel.interact")

TERMINALS = {"cmd.exe", "powershell.exe", "pwsh.exe", "powershell_ise.exe", "windowsterminal.exe", "wt.exe", "conhost.exe",
             "openconsole.exe", "regedit.exe", "mmc.exe", "wsl.exe", "bash.exe", "taskmgr.exe", "secpol.msc", "services.exe"}
SAFE_KEYS = {
    "enter", "esc", "tab", "shift+tab", "space", "up", "down", "left", "right", "pageup", "pagedown", "home", "end", "backspace",
    "ctrl+a", "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+z", "ctrl+y", "ctrl+f", "ctrl+l", "ctrl+t", "ctrl+n", "ctrl+s", "ctrl+r",
    "ctrl+tab", "ctrl+shift+tab", "ctrl+shift+t", "ctrl+shift+n", "ctrl+home", "ctrl+end", "f5", "f6", "f11", "alt+left", "alt+right",
    "ctrl+1", "ctrl+2", "ctrl+3", "ctrl+4", "ctrl+5", "ctrl+6", "ctrl+7", "ctrl+8", "ctrl+9",
}
KEY_ALIASES = {"control": "ctrl", "return": "enter", "escape": "esc", "entree": "enter", "pgdn": "pagedown", "pgup": "pageup",
               "page_down": "pagedown", "page_up": "pageup", "arrowleft": "left", "arrowright": "right", "arrowup": "up", "arrowdown": "down"}
SENSITIVE_LABEL = re.compile(r"supprim|delet|efface|erase|wipe|format|desinstall|uninstall|\bpay|achet|\bbuy|purchas|command(?:er|e)\b|"
                             r"virement|transf[eè]r|reinitialis|\breset|vider|administrat|mot de passe|password")
CLICKABLE = {"ButtonControl", "HyperlinkControl", "MenuItemControl", "TabItemControl", "CheckBoxControl", "RadioButtonControl",
             "ListItemControl", "TreeItemControl", "SplitButtonControl"}
DOMAIN = re.compile(r"^(?:https?://)?(?:[\w-]+\.)+(?:com|fr|org|net|io|tv|gg|be|ch|ca|app|dev|co|eu|info|me|ai|wiki)(?:[/?#]\S*)?$", re.I)

_WIN = sys.platform == "win32"
if _WIN:
    _u = ctypes.WinDLL("user32", use_last_error=True)
    _k = ctypes.WinDLL("kernel32", use_last_error=True)
    _u.GetForegroundWindow.restype = wintypes.HWND
    _u.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    _u.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    _u.IsWindowVisible.argtypes = (wintypes.HWND,)
    _u.IsIconic.argtypes = (wintypes.HWND,)
    _u.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    _u.SetForegroundWindow.argtypes = (wintypes.HWND,)
    _k.OpenProcess.restype = wintypes.HANDLE
    _k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _k.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    _k.CloseHandle.argtypes = (wintypes.HANDLE,)
    _ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _title(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(300)
    _u.GetWindowTextW(hwnd, buf, 300)
    return buf.value


def _exe(hwnd) -> str:
    pid = wintypes.DWORD()
    _u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = _k.OpenProcess(0x1000, False, pid.value)          # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf, size = ctypes.create_unicode_buffer(520), wintypes.DWORD(520)
        if _k.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
    finally:
        _k.CloseHandle(handle)
    return ""


def normalize_keys(keys: str) -> str:
    parts = [KEY_ALIASES.get(p.strip().lower(), p.strip().lower()) for p in re.split(r"[+\s]+", str(keys)) if p.strip()]
    order = {"ctrl": 0, "shift": 1, "alt": 2}
    parts.sort(key=lambda p: order.get(p, 9))                    # ctrl+shift+t, pas shift+ctrl+t
    return "+".join(parts)


class Interactor:
    def __init__(self, cfg) -> None:
        self.cfg = cfg

    # ------------------------------------------------------------------ fenêtre active
    def foreground(self) -> tuple[str, str]:
        """(titre, programme) de la fenêtre active ; ('', '') hors Windows."""
        if not _WIN:
            return "", ""
        hwnd = _u.GetForegroundWindow()
        return (_title(hwnd), _exe(hwnd)) if hwnd else ("", "")

    def foreground_summary(self) -> str:
        title, exe = self.foreground()
        return f"« {title[:80]} » ({exe})" if title else ""

    def _blocked(self) -> bool:
        return self.foreground()[1] in TERMINALS

    # ------------------------------------------------------------------ actions
    def focus(self, query: str) -> str:
        if not _WIN:
            return R(self.cfg, "win_missing", name=query)
        q = normalize(query)
        toks = q.split()
        found: list[tuple[float, int, str]] = []
        me = os.getpid()

        def visit(hwnd, _lparam) -> bool:
            if not _u.IsWindowVisible(hwnd):
                return True
            title = _title(hwnd)
            if not title:
                return True
            pid = wintypes.DWORD()
            _u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == me:
                return True                                      # pas notre propre fenêtre
            hay = normalize(title + " " + _exe(hwnd).replace(".exe", ""))
            if toks and all(t in hay for t in toks):
                score = 0.95
            else:
                score = SequenceMatcher(None, q, normalize(title)).ratio()
            if score >= 0.6:
                found.append((score, int(hwnd), title))
            return True

        _u.EnumWindows(_ENUM(visit), 0)
        if not found:
            return R(self.cfg, "win_missing", name=query)
        found.sort(reverse=True)
        _score, hwnd, title = found[0]
        if _u.IsIconic(hwnd):
            _u.ShowWindow(hwnd, 9)                               # SW_RESTORE
        ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)          # tape Alt : Windows accepte alors le changement de premier plan
        ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)
        _u.SetForegroundWindow(hwnd)
        time.sleep(0.25)
        return R(self.cfg, "win_focus", name=query)

    def focus_exact(self, title: str) -> bool:
        """Ramène au premier plan la fenêtre dont le titre est EXACTEMENT `title` (True si trouvée)."""
        if not _WIN:
            return False
        want = normalize(title)
        found: list[int] = []
        me = os.getpid()

        def visit(hwnd, _lparam) -> bool:
            if _u.IsWindowVisible(hwnd) and normalize(_title(hwnd)) == want:
                pid = wintypes.DWORD()
                _u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value != me:
                    found.append(int(hwnd))
            return True

        _u.EnumWindows(_ENUM(visit), 0)
        if not found:
            return False
        if _u.IsIconic(found[0]):
            _u.ShowWindow(found[0], 9)
        ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)
        _u.SetForegroundWindow(found[0])
        return True

    def press(self, keys: str) -> str:
        combo = normalize_keys(keys)
        if combo not in SAFE_KEYS:
            log.warning("raccourci refusé : %r", keys)
            return R(self.cfg, "key_refused")
        if self._blocked():
            return R(self.cfg, "interact_blocked")
        send_combo(combo)
        return R(self.cfg, "done")

    def type_text(self, text: str) -> str:
        text = re.sub(r"\s*[\r\n]+\s*", " ", str(text)).strip()[:400]
        if not text:
            return ""
        if self._blocked():
            return R(self.cfg, "interact_blocked")
        type_unicode(text)
        return R(self.cfg, "done")

    def scroll(self, direction: str) -> str:
        key = {"down": "pagedown", "up": "pageup", "top": "ctrl+home", "bottom": "ctrl+end"}.get(str(direction).lower(), "pagedown")
        return self.press(key)

    def open_url(self, url: str) -> str:
        url = str(url).strip().strip("«»\"'")
        if not DOMAIN.match(url) and not re.match(r"^https?://[\w.-]+(?:[/?#]\S*)?$", url, re.I):
            return R(self.cfg, "url_refused")
        if not re.match(r"^https?://", url, re.I):
            url = "https://" + url
        webbrowser.open(url)
        return R(self.cfg, "url_open", name=re.sub(r"^https?://(?:www\.)?", "", url).split("/")[0])

    def ui_click(self, label: str) -> str:
        """Clique sur un bouton / lien / onglet de la fenêtre active, retrouvé par son nom (UI Automation)."""
        label = str(label).strip()
        if SENSITIVE_LABEL.search(normalize(label)):
            return R(self.cfg, "ui_refused", name=label)
        if self._blocked():
            return R(self.cfg, "interact_blocked")
        try:
            import uiautomation as auto
        except ImportError:
            return R(self.cfg, "ui_missing")
        wanted = normalize(label)
        best, best_score = None, 0.0
        deadline = time.time() + 4.0
        try:
            top = auto.GetForegroundControl().GetTopLevelControl()
            for ctrl, _depth in auto.WalkControl(top, includeTop=False, maxDepth=14):
                if time.time() > deadline:
                    break
                if ctrl.ControlTypeName not in CLICKABLE or not ctrl.Name or ctrl.IsOffscreen:
                    continue
                name = normalize(ctrl.Name)
                score = 1.0 if name == wanted else 0.9 if wanted in name else SequenceMatcher(None, wanted, name).ratio()
                if score > best_score:
                    best, best_score = ctrl, score
        except Exception:
            log.exception("UI Automation : parcours impossible")
            return R(self.cfg, "ui_notfound", name=label)
        if best is None or best_score < 0.7:
            return R(self.cfg, "ui_notfound", name=label)
        if SENSITIVE_LABEL.search(normalize(best.Name)):
            return R(self.cfg, "ui_refused", name=best.Name)
        try:
            pattern = best.GetInvokePattern()
            if pattern:
                pattern.Invoke()
            else:
                best.Click(simulateMove=False)
        except Exception:
            log.exception("clic impossible sur %r", best.Name)
            return R(self.cfg, "ui_notfound", name=label)
        return R(self.cfg, "ui_click_done", name=best.Name[:40])
