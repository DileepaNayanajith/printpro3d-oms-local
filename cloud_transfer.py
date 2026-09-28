"""Explicit offline database transfer. Never include browser profiles or API keys."""
import argparse
import json
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path


def export(source,target):
    source=Path(source);target=Path(target)
    if target.exists():raise ValueError('Choose a new output file; refusing to overwrite.')
    with tempfile.TemporaryDirectory() as temp:
        snapshot=Path(temp)/'oms.sqlite3'
        with sqlite3.connect(source/'oms.sqlite3') as c, sqlite3.connect(snapshot) as dest:
            c.backup(dest)
            if dest.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Database check failed.')
            # Transport credentials and live heartbeat/claims must never migrate.
            for table in ('home_station','station_tasks','station_health','browser_worker','whatsapp_worker'):
                if dest.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():dest.execute('DELETE FROM '+table)
            dest.commit()
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as f,zipfile.ZipFile(f,'w',zipfile.ZIP_DEFLATED) as z:
            z.write(snapshot,'oms.sqlite3')
            if (source/'printing.json').exists():
                settings=json.loads((source/'printing.json').read_text())
                z.writestr('printing.json',json.dumps({'sender':settings['sender']}))
            for file in (source/'waybills').glob('*.pdf'):
                if not file.is_symlink():z.write(file,'waybills/'+file.name)


def restore(archive,target):
    target=Path(target)
    # Run with the cloud server stopped, before its first startup.
    if (target/'oms.sqlite3').exists():raise ValueError('Target already contains a database. Refusing to replace it.')
    target.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target) as temp, zipfile.ZipFile(archive) as z:
        if sum(i.file_size for i in z.infolist())>100*1024*1024:raise ValueError('Archive too large.')
        names=z.namelist()
        if len(names)!=len(set(names)) or 'oms.sqlite3' not in names:raise ValueError('Invalid archive.')
        for name in names:
            path=Path(name)
            if name not in ('oms.sqlite3','printing.json') and not (len(path.parts)==2 and path.parts[0]=='waybills' and path.suffix=='.pdf'):
                raise ValueError('Unexpected archive member.')
            if path.is_absolute() or '..' in path.parts or '\\' in name:raise ValueError('Unsafe archive path.')
            dest=Path(temp)/path;dest.parent.mkdir(exist_ok=True);dest.write_bytes(z.read(name))
        with sqlite3.connect(Path(temp)/'oms.sqlite3') as c:
            if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Database check failed.')
            # Never replay any job that might already have had an external effect.
            c.execute("UPDATE booking_jobs SET state='needs_review',message='Migrated interrupted job. Check FDE before retrying.' WHERE state IN ('preparing','prepared','approved','submitting')")
            c.execute("UPDATE print_jobs SET state='needs_review',message='Migrated print job: check paper output.' WHERE state IN ('rendering','sending','queued')")
            for table in ('whatsapp_outbox','whatsapp_confirmations'):
                c.execute(f"UPDATE {table} SET state='needs_review',detail='Migrated pending message. Check chat before retrying.' WHERE state IN ('sending','preparing','queued')")
            c.commit()
        for name in names:
            dest=target/name;dest.parent.mkdir(exist_ok=True);os.replace(Path(temp)/name,dest)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['export','restore']);p.add_argument('source');p.add_argument('target')
    args=p.parse_args()
    (export if args.action=='export' else restore)(args.source,args.target)
    print('Transfer complete. Treat the archive as private customer data.')
