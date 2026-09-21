"""Simulation de touches via l'API Windows SendInput (ctypes, sans dépendance)."""
from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR))


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR))


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD))


class _INPUTUNION(ctypes.Union):  # l'union DOIT contenir MOUSEINPUT (le plus grand) sinon SendInput échoue
    _fields_ = (("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT))


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = (("type", wintypes.DWORD), ("u", _INPUTUNION))


_user32 = ctypes.WinDLL("user32", use_last_error=True) if sys.platform == "win32" else None
if _user32:
    _user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    _user32.SendInput.restype = wintypes.UINT

# --- table des touches -------------------------------------------------------
VK: dict[str, int] = {
    "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "windows": 0x5B,
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 0x09,
    "backspace": 0x08, "delete": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "pause": 0x13, "printscreen": 0x2C,
}
for _i in range(1, 25):
    VK[f"f{_i}"] = 0x6F + _i          # F1 = 0x70
for _i in range(10):
    VK[str(_i)] = 0x30 + _i
    VK[f"num{_i}"] = 0x60 + _i        # pavé numérique
for _c in "abcdefghijklmnopqrstuvwxyz":
    VK[_c] = ord(_c.upper())

MEDIA = {"playpause": 0xB3, "next": 0xB0, "prev": 0xB1, "stop": 0xB2,
         "volup": 0xAF, "voldown": 0xAE, "mute": 0xAD}

_MODIFIERS = {0x10, 0x11, 0x12, 0x5B}
_EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B,
             0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB2, 0xB3}


def _event(vk: int, up: bool) -> None:
    flags = KEYEVENTF_KEYUP if up else 0
    if vk in _EXTENDED:
        flags |= KEYEVENTF_EXTENDEDKEY
    scan = _user32.MapVirtualKeyW(vk, 0)
    inp = INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(vk, scan, flags, 0, 0))
    if _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) != 1:
        raise OSError(f"SendInput a échoué (erreur {ctypes.get_last_error()})")


def press_vk(vk: int, times: int = 1) -> None:
    for _ in range(times):
        _event(vk, False)
        _event(vk, True)
        time.sleep(0.02)


def press_media(name: str) -> None:
    press_vk(MEDIA[name])


def send_combo(combo: str) -> None:
    """Envoie un raccourci de type 'ctrl+alt+f9' ou 'ctrl+shift+m'."""
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    if not parts:
        raise ValueError("raccourci vide")
    try:
        codes = [VK[p] for p in parts]
    except KeyError as exc:
        raise ValueError(f"touche inconnue : {exc.args[0]}") from None
    mods = [c for c in codes if c in _MODIFIERS]
    keys = [c for c in codes if c not in _MODIFIERS]
    for c in mods + keys:
        _event(c, False)
        time.sleep(0.02)
    time.sleep(0.05)
    for c in reversed(mods + keys):
        _event(c, True)
        time.sleep(0.02)


def type_unicode(text: str, delay: float = 0.004) -> None:
    """Tape un texte caractère par caractère (accents, majuscules, symboles) dans la fenêtre active."""
    data = text.encode("utf-16-le")
    for i in range(0, len(data), 2):
        code = int.from_bytes(data[i:i + 2], "little")
        for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
            inp = INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0, code, flags, 0, 0))
            if _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) != 1:
                raise OSError(f"SendInput a échoué (erreur {ctypes.get_last_error()})")
        time.sleep(delay)
