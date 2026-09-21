# -*- mode: python ; coding: utf-8 -*-
"""Recette PyInstaller pour Sentinel.

    pyinstaller --clean --noconfirm sentinel.spec

ONEFILE = True  -> un seul Sentinel.exe (démarrage un peu plus lent : ~3-8 s)
ONEFILE = False -> dossier dist/Sentinel/ (démarrage rapide, à distribuer zippé)
"""
import importlib.util

from PyInstaller.utils.hooks import collect_all, collect_data_files

ONEFILE = True


def present(pkg):
    """Le paquet est-il installé ? (évite de perdre du temps, ou de bloquer, sur un paquet absent)"""
    return importlib.util.find_spec(pkg) is not None


datas = [("assets", "assets")]            # icône de fenêtre -> bundle_dir()/assets
binaries = []
hiddenimports = [
    "win32com", "win32com.client", "pythoncom", "pywintypes", "win32timezone",
    "comtypes", "comtypes.client", "comtypes.stream",
    "pycaw", "pycaw.pycaw",
    "pystray._win32",
    "PIL._tkinter_finder", "PIL.ImageGrab", "win32clipboard", "winsound",
    # importés à l'intérieur de fonctions : on les déclare pour être sûr
    "edge_tts", "aiohttp", "yt_dlp", "uiautomation",
]

# Paquets qui embarquent des DLL ou des fichiers de données : collecte complète (ils sont petits).
for pkg in ("vosk", "sounddevice", "_sounddevice_data", "customtkinter"):
    if present(pkg):
        print(f"[spec] collecte complete : {pkg}", flush=True)
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h

# Paquets Python purs : l'analyse des imports suffit, on ajoute seulement leurs fichiers de données.
for pkg in ("certifi",):
    if present(pkg):
        print(f"[spec] donnees : {pkg}", flush=True)
        datas += collect_data_files(pkg)

# Facultatifs et lourds (Whisper, luminosité d'écran externe) : seulement s'ils sont installés.
for pkg in ("faster_whisper", "ctranslate2", "tokenizers", "onnxruntime", "av", "monitorcontrol"):
    if present(pkg):
        print(f"[spec] collecte facultative : {pkg}", flush=True)
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h

print("[spec] collecte terminee, analyse des imports...", flush=True)

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "scipy", "pandas", "IPython", "pytest", "numpy.tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name="Sentinel",
        icon="assets/sentinel.ico",
        console=False,                        # aucune fenêtre de terminal
        upx=False,                            # UPX = plus de faux positifs antivirus
        runtime_tmpdir=None,
    )
else:
    exe = EXE(
        pyz, a.scripts, [], exclude_binaries=True,
        name="Sentinel",
        icon="assets/sentinel.ico",
        console=False,
        upx=False,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="Sentinel", upx=False)
