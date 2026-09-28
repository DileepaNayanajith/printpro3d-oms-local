"""Produce a source-only Windows package from an explicit allowlist."""
from pathlib import Path
import zipfile
root=Path(__file__).resolve().parent
out=root/'dist';out.mkdir(exist_ok=True)
files=[root/'home_worker.py',root/'requirements.lock.txt',root/'docs/CLOUD-AND-WINDOWS.md']
for folder in ('windows','oms'):
    files.extend(p for p in (root/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
with zipfile.ZipFile(out/'PRINTPRO3D-Windows-Station.zip','w',zipfile.ZIP_DEFLATED) as z:
    for p in files:z.write(p,p.relative_to(root))
print('Built dist/PRINTPRO3D-Windows-Station.zip — no orders, credentials or browser profiles included.')
