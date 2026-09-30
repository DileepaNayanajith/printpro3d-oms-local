$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'
if (Test-Path $python) {
    & $python -m venv .venv-windows
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.11 -m venv .venv-windows
} else { throw 'Install Python 3.11, then run Setup again.' }
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 is required. Install it and rerun Setup.' }
& .\.venv-windows\Scripts\python.exe -m pip install -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency install failed. Check internet access and rerun Setup.' }
& .\.venv-windows\Scripts\python.exe -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw 'Browser install failed. Check internet access and rerun Setup.' }
$stationPath = Join-Path $env:LOCALAPPDATA 'PRINTPRO3D-station'
New-Item -ItemType Directory -Force -Path $stationPath | Out-Null
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls $stationPath /inheritance:r /grant:r "${identity}:(OI)(CI)F" 'SYSTEM:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not protect station login files.' }
$env:PYTHONPATH = (Get-Location).Path
& .\.venv-windows\Scripts\python.exe windows\configure.py
if ($LASTEXITCODE -ne 0) { throw 'Pairing was not completed.' }
