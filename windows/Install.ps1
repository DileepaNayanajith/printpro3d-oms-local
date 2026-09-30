$ErrorActionPreference = 'Stop'
try {
    $source = Split-Path $PSScriptRoot -Parent
    $destination = Join-Path $env:LOCALAPPDATA 'PRINTPRO3D\Station'
    Write-Host 'PRINTPRO3D Home Station installer' -ForegroundColor Cyan
    Write-Host 'This installs the station for your Windows user. Existing logins and settings are kept.'
    if ($source -ne $destination) {
        New-Item -ItemType Directory -Force -Path $destination | Out-Null
        & robocopy $source $destination /E /XD .venv-windows .git __pycache__ instance /XF *.pyc /NFL /NDL /NJH /NJS | Out-Null
        if ($LASTEXITCODE -ge 8) { throw 'Could not copy the station files.' }
    }
    $python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'
    $hasPython = Test-Path $python
    if (-not $hasPython -and (Get-Command py -ErrorAction SilentlyContinue)) {
        & py -3.11 -c "import sys; assert sys.version_info[:2] == (3,11)" 2>$null
        $hasPython = $LASTEXITCODE -eq 0
    }
    if (-not $hasPython) {
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            Start-Process 'https://www.python.org/downloads/windows/'
            throw 'Install Python 3.11 with the Python launcher, then run Install again. Windows App Installer (winget) is unavailable.'
        }
        Write-Host 'Installing Python 3.11. Review any installer prompts.'
        & winget install --exact --id Python.Python.3.11 --source winget --scope user
        if ($LASTEXITCODE -ne 0) { throw 'Python installation was not completed. Run Install again after installing Python 3.11.' }
    }
    $sumatraPaths = @((Join-Path $env:LOCALAPPDATA 'SumatraPDF\SumatraPDF.exe'), (Join-Path $env:ProgramFiles 'SumatraPDF\SumatraPDF.exe'))
    if (-not ($sumatraPaths | Where-Object { Test-Path $_ })) {
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            Write-Host 'Installing SumatraPDF for HP label printing. Review any installer prompts.'
            & winget install --exact --id SumatraPDF.SumatraPDF --source winget --scope user
        }
        if (-not ($sumatraPaths | Where-Object { Test-Path $_ })) {
            Start-Process 'https://www.sumatrapdfreader.org/free-pdf-reader'
            Write-Host 'If SumatraPDF is not installed yet, install it before pairing the printer.'
        }
    }
    & (Join-Path $destination 'windows\Setup.ps1')
    if (-not (Test-Path (Join-Path $destination '.venv-windows\Scripts\python.exe'))) { throw 'Station setup did not finish.' }
    $shell = New-Object -ComObject WScript.Shell
    foreach ($item in @(@('PRINTPRO3D Start', 'Start Station.cmd'), @('PRINTPRO3D Pair PC', 'Setup.cmd'))) {
        $shortcut = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) ($item[0]+'.lnk')))
        $shortcut.TargetPath = Join-Path $destination ('windows\'+$item[1])
        $shortcut.WorkingDirectory = $destination
        $shortcut.Save()
    }
    Write-Host 'Installed. Use PRINTPRO3D Start on your desktop after pairing.' -ForegroundColor Green
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
