@echo off
REM ============================================================
REM  Fabrique dist\Sentinel.exe  (double-clic ou : build.bat)
REM ============================================================
setlocal
cd /d "%~dp0"

where py >nul 2>nul && (set PY=py -3) || (set PY=python)

if not exist .venv (
    echo [1/4] Creation de l'environnement virtuel...
    %PY% -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat || goto :error

echo [2/4] Installation des dependances...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt || goto :error

echo [3/4] Generation de l'icone...
python tools\make_icon.py || goto :error

echo [4/4] Compilation avec PyInstaller...
pyinstaller --clean --noconfirm sentinel.spec || goto :error

echo.
echo  Termine !  ->  dist\Sentinel.exe
echo  Creation du raccourci sur le Bureau...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\create_shortcut.ps1" -Exe
pause
exit /b 0

:error
echo.
echo  *** ECHEC : lisez les messages ci-dessus. ***
pause
exit /b 1
