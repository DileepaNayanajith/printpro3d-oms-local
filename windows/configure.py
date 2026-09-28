"""Pair this Windows user with the online OMS. No keys in command history."""
import getpass
import json
import os
import subprocess
from pathlib import Path
from home_worker import station_root
from oms.station_client import API, save

root=station_root();root.mkdir(parents=True,exist_ok=True)
print('PRINTPRO3D HOME PC SETUP')
url=input('Online OMS address (https://...): ').strip()
token=getpass.getpass('Pairing key from Owner > Home PC: ').strip()
api=API(url,token)
api.post('poll',{'kind':'print','ready':False})
candidates=[Path(os.environ.get('ProgramFiles','C:/Program Files'))/'SumatraPDF/SumatraPDF.exe',
 Path(os.environ.get('LOCALAPPDATA',''))/'SumatraPDF/SumatraPDF.exe']
exe=next((p for p in candidates if p.is_file()),None)
if not exe:
 exe=Path(input('Full path to SumatraPDF.exe: ').strip().strip('"'))
if not exe.is_file():raise SystemExit('SumatraPDF was not found. Install it, then rerun Setup.')
result=subprocess.run(['powershell','-NoProfile','-Command','Get-Printer | Select-Object -ExpandProperty Name'],capture_output=True,text=True)
print('Available printers:\n'+result.stdout)
printer=input('Copy the exact HP printer name: ').strip()
if not printer or printer not in result.stdout.splitlines():raise SystemExit('Printer name did not match. Setup was not saved.')
save(root/'settings.json',{'url':url.rstrip('/'),'token':token,'sumatra':str(exe),'printer':printer})
print('Paired. In Windows printer preferences choose A4 and Landscape. Run Start Station.cmd and sign in to FDE and WhatsApp.')
