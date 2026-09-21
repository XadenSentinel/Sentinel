@echo off
REM ============================================================
REM  Cree le raccourci "Sentinel" sur le Bureau (double-clic)
REM  Il lance Sentinel sans fenetre noire, avec son icone.
REM ============================================================
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\create_shortcut.ps1"
echo.
pause
