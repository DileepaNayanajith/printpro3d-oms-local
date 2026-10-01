"""Single cloud web process; no printers or browser profiles on the server."""
import json
import os
from pathlib import Path
from waitress import serve
from oms import create_app
from oms.automation import connection
from manage import add_user


def build_app():
    if os.environ.get('OMS_CLOUD')!='1' or os.environ.get('OMS_HTTPS')!='1':
        raise SystemExit('Cloud mode and HTTPS cookies must be enabled.')
    if len(os.environ.get('OMS_SECRET',''))<32:
        raise SystemExit('Set a private OMS_SECRET of at least 32 characters.')
    root=Path(os.environ.get('OMS_INSTANCE_PATH',''))
    if not root.is_absolute() or not root.is_dir():
        raise SystemExit('Mount persistent storage and set OMS_INSTANCE_PATH to its absolute path.')
    app=create_app()
    with connection(app.config['DATABASE']) as c:
        if not c.execute('SELECT 1 FROM users WHERE role=\'admin\' AND active=1').fetchone():
            password=os.environ.get('OMS_OWNER_PASSWORD','')
            if len(password)<16:raise SystemExit('Set OMS_OWNER_PASSWORD to at least 16 characters for first startup.')
            add_user(c,'owner','admin',password)
        # Optional first packing login, never change an existing password.
        password=os.environ.get('OMS_PACKING_PASSWORD','')
        if password and not c.execute("SELECT 1 FROM users WHERE username='packing01'").fetchone():
            add_user(c,'packing01','packer',password)
        # Explicitly provision the phone-only handover account; never reset its password.
        packing_hash=os.environ.get('OMS_PACKING02_PASSWORD_HASH','')
        if packing_hash:
            if not packing_hash.startswith('pbkdf2:sha256:'):raise SystemExit('Invalid packing02 password hash.')
            existing=c.execute("SELECT role FROM users WHERE username='packing02'").fetchone()
            if existing and existing['role']!='packer':raise SystemExit('packing02 already has a different role; owner review required.')
            with c:
                if not existing:c.execute("INSERT INTO users(username,password_hash,role,packing_only) VALUES('packing02',?,'packer',1)",(packing_hash,))
                else:c.execute("UPDATE users SET packing_only=1 WHERE username='packing02'")
    settings=root/'printing.json'
    if not settings.exists():
        values={k:os.environ.get('OMS_SENDER_'+k.upper(),'') for k in ('name','address','phone')}
        if not all(values.values()):raise SystemExit('Configure sender name, address and phone before starting.')
        settings.write_text(json.dumps({'sender':values}))
    return app

if __name__=='__main__':
    serve(build_app(),host='0.0.0.0',port=int(os.environ.get('PORT','8080')),threads=4)
