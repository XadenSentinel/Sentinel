# Cree un raccourci "Sentinel" sur le Bureau (sans fenetre de terminal).
#   Sans option : lance le projet avec l'environnement .venv (pythonw main.py)
#   -Exe        : pointe vers dist\Sentinel.exe (apres avoir lance build.bat)
param([switch]$Exe)
$root = Split-Path $PSScriptRoot -Parent
$icon = Join-Path $root "assets\sentinel.ico"
if ($Exe) {
    $target = Join-Path $root "dist\Sentinel.exe"
    $arguments = ""
    if (-not (Test-Path $target)) { Write-Host "dist\Sentinel.exe introuvable : lance d'abord build.bat"; exit 1 }
} else {
    $target = Join-Path $root ".venv\Scripts\pythonw.exe"
    $arguments = '"' + (Join-Path $root "main.py") + '"'
    if (-not (Test-Path $target)) {
        Write-Host "Environnement .venv introuvable. Lance d'abord :  python -m venv .venv  puis  .venv\Scripts\activate  puis  pip install -r requirements.txt"
        exit 1
    }
}
$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) "Sentinel.lnk"
$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($lnk)
$s.TargetPath = $target
$s.Arguments = $arguments
$s.WorkingDirectory = $root
if (Test-Path $icon) { $s.IconLocation = $icon }
$s.Description = "Sentinel - assistant vocal"
$s.Save()
Write-Host "Raccourci cree sur le Bureau : $lnk"
