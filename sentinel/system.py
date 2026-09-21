"""Petits utilitaires Windows : instance unique et lancement au démarrage."""
from __future__ import annotations

import sys
from pathlib import Path

from .config import APP_NAME, is_frozen

_ERROR_ALREADY_EXISTS = 183


def acquire_single_instance():
    """Retourne un handle (à garder en vie) ou None si Sentinel tourne déjà."""
    if sys.platform != "win32":
        return object()
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Local\\SentinelAssistantMutex")
    if kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
        return None
    return handle


def set_autostart(enabled: bool) -> None:
    """Ajoute / retire Sentinel du démarrage de Windows (clé HKCU\\...\\Run)."""
    if sys.platform != "win32":
        return
    import winreg

    if is_frozen():
        command = f'"{sys.executable}" --minimized'
    else:  # mode développement : pythonw = pas de console
        pyw = Path(sys.executable).with_name("pythonw.exe")
        command = f'"{pyw}" "{Path(sys.argv[0]).resolve()}" --minimized'

    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_SET_VALUE,
    )
    try:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


# --------------------------------------------------------------------------- #
# Télémétrie pour le HUD (sans dépendance : appels Windows directs)
# --------------------------------------------------------------------------- #
_cpu_prev: tuple | None = None


def cpu_percent() -> float:
    global _cpu_prev
    if sys.platform != "win32":
        return 0.0
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = (("lo", wintypes.DWORD), ("hi", wintypes.DWORD))

    idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        return 0.0
    now = tuple((f.hi << 32) | f.lo for f in (idle, kernel, user))
    prev, _cpu_prev = _cpu_prev, now
    if prev is None:
        return 0.0
    d_idle, d_kernel, d_user = (a - b for a, b in zip(now, prev))
    total = d_kernel + d_user                      # (le temps noyau inclut le temps d'inactivité)
    return max(0.0, min(100.0, 100.0 * (total - d_idle) / total)) if total else 0.0


def ram_percent() -> float:
    if sys.platform != "win32":
        return 0.0
    import ctypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = (("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong))

    st = MEMORYSTATUSEX()
    st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    return float(st.dwMemoryLoad) if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)) else 0.0


def restart_app(delay: int = 3) -> None:
    """Relance Sentinel après quelques secondes (le temps que l'instance actuelle se ferme et libère son verrou)."""
    import os
    import subprocess

    exe = sys.executable
    args = "" if getattr(sys, "frozen", False) else f' "{os.path.abspath(sys.argv[0])}"'
    env = {k: v for k, v in os.environ.items() if not k.startswith(("_MEIPASS", "_PYI"))}   # indispensable pour un .exe PyInstaller
    subprocess.Popen(["cmd", "/c", f'ping -n {delay} 127.0.0.1 >nul & "{exe}"{args}'], env=env,
                     creationflags=0x08000000, close_fds=True)               # CREATE_NO_WINDOW
