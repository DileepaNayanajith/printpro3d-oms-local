$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw 'Install Python 3.11 (64-bit) from python.org with the Python launcher, then run Setup again.'
}
& py -3.11 -m venv .venv-windows
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 is required. Install it and rerun Setup.' }
& .\.venv-windows\Scripts\python.exe -m pip install -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency install failed.' }
& .\.venv-windows\Scripts\python.exe -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw 'Browser install failed.' }
$stationPath = Join-Path $env:LOCALAPPDATA 'PRINTPRO3D-station'
New-Item -ItemType Directory -Force -Path $stationPath | Out-Null
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls $stationPath /inheritance:r /grant:r "${identity}:(OI)(CI)F" 'SYSTEM:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not protect station login files.' }
$env:PYTHONPATH = (Get-Location).Path
& .\.venv-windows\Scripts\python.exe windows\configure.py
if ($LASTEXITCODE -ne 0) { throw 'Pairing was not completed.' }
