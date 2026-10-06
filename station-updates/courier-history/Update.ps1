$ErrorActionPreference = 'Stop'
try {
  $station = Join-Path $env:LOCALAPPDATA 'PRINTPRO3D\Station'
  $target = Join-Path $station 'oms\fde_reports.py'
  if (-not (Test-Path $target)) { throw 'Installed PRINTPRO3D station not found for this Windows user.' }
  $running = Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -match 'home_worker\.py' }
  if ($running) { throw 'Close the PRINTPRO3D station worker windows after any active jobs finish, then run this update again.' }
  $source = Join-Path $PSScriptRoot 'fde_reports.py'
  if ((Get-FileHash $source -Algorithm SHA256).Hash.ToLower() -ne '13d637f85697e153941b9644d1a47600a950d8fdb9e4543de43748ca7c514ae9') { throw 'Update file is damaged. Extract the ZIP again.' }
  $backup = $target + '.before-courier-history'
  if (-not (Test-Path $backup)) { Copy-Item $target $backup }
  Copy-Item $source $target -Force
  Write-Host 'Updated. Open PRINTPRO3D Start on the desktop. Log into FDE if needed, then click Refresh FDE reports in the OMS.' -ForegroundColor Green
  Write-Host 'Settings, printer configuration and browser logins have been kept.'
} catch { Write-Host $_.Exception.Message -ForegroundColor Red; exit 1 }
