# -*- mode: python ; coding: utf-8 -*-
"""Recette PyInstaller pour Sentinel.

    pyinstaller --clean --noconfirm sentinel.spec

ONEFILE = True  -> un seul Sentinel.exe (démarrage un peu plus lent : ~3-8 s)
ONEFILE = False -> dossier dist/Sentinel/ (démarrage rapide, à distribuer zippé)
"""
from PyInstaller.utils.hooks import collect_all, collect_data_files

ONEFILE = True

datas = [("assets", "assets")]            # icône de fenêtre -> bundle_dir()/assets
binaries = []
hiddenimports = [
    "win32com", "win32com.client", "pythoncom", "pywintypes", "win32timezone",
    "comtypes", "comtypes.client", "comtypes.stream",
    "pycaw", "pycaw.pycaw",
    "pystray._win32",
    "PIL._tkinter_finder", "PIL.ImageGrab", "win32clipboard", "winsound",
]

# Paquets qui embarquent des DLL / fichiers de données : on prend tout.
for pkg in ("vosk", "sounddevice", "_sounddevice_data", "yt_dlp", "customtkinter", "monitorcontrol", "edge_tts", "aiohttp", "certifi", "faster_whisper", "ctranslate2", "tokenizers", "onnxruntime", "av"):   # monitorcontrol : facultatif
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:                  # paquet absent : on prévient mais on continue
        print(f"[spec] avertissement : {pkg} introuvable ({exc})")

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
