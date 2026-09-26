"""Store Text.lk credentials locally without putting them in chat, Git or shell history."""
import getpass
import json
import os
import re
from pathlib import Path
from oms import create_app,sms
from oms.automation import connection

if __name__=='__main__':
    app=create_app();root=Path(app.instance_path)
    print('Text.lk setup. Use an approved sender ID for customer messages. Demo sender IDs cannot be activated.')
    sender=input('Approved sender ID (e.g. PRINTPRO3D): ').strip()
    if not re.fullmatch(r'[A-Za-z0-9]{1,11}',sender) or sender.lower()=='textlkdemo':
        raise SystemExit('Enter your Text.lk-approved alphanumeric sender ID, not TextLKDemo.')
    token=getpass.getpass('Text.lk API token (hidden): ').strip()
    if not token or '\n' in token or '\r' in token:raise SystemExit('A valid token is required.')
    enabled=input('Enable SMS for NEW order/dispatch events only? Type ENABLE: ').strip()=='ENABLE'
    with connection(app.config['DATABASE']) as conn:
        first=conn.execute('SELECT COALESCE(MAX(id),0)+1 FROM sms_outbox').fetchone()[0]
    data={'sender_id':sender,'token':token,'enabled':enabled,'first_message_id':first}
    path=root/'textlk.json';tmp=root/'textlk.json.tmp'
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    os.chmod(tmp,0o600)
    with os.fdopen(fd,'w') as f:json.dump(data,f)
    os.replace(tmp,path)
    print('Saved privately. Automatic SMS '+('enabled for new events only.' if enabled else 'disabled.'))
    print('Run start_staff.command or start_sms.command. Old setup messages remain held.')
