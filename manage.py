"""Owner-only local staff account management. Passwords never enter command history."""
import argparse
import getpass
import re
import sqlite3
import os
import secrets
from pathlib import Path
from werkzeug.security import generate_password_hash
from oms import create_app
from oms.automation import connection


def add_user(conn, username, role, password):
    if not re.fullmatch(r'[a-z0-9_.-]{3,40}', username):
        raise ValueError('Use a 3–40 character lowercase username: letters, digits, dot, dash or underscore.')
    if role not in ('admin','caller','packer'):
        raise ValueError('Unknown role.')
    if len(password)<12:
        raise ValueError('Use a password with at least 12 characters.')
    with conn:
        conn.execute('INSERT INTO users(username,password_hash,role) VALUES(?,?,?)',
                     (username,generate_password_hash(password,method="pbkdf2:sha256:1000000"),role))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    add=commands.add_parser('add-user'); add.add_argument('username'); add.add_argument('--role',choices=['admin','caller','packer'],required=True)
    commands.add_parser('list-users')
    commands.add_parser('bootstrap',help='Create owner/caller01/packing01 accounts once; write passwords to private local file')
    disable=commands.add_parser('disable-user'); disable.add_argument('username')
    args=parser.parse_args()
    app=create_app()
    with connection(app.config['DATABASE']) as conn:
        if args.command=='bootstrap':
            if conn.execute('SELECT 1 FROM users LIMIT 1').fetchone():
                raise SystemExit('Accounts already exist. Use add-user; existing passwords were not changed.')
            access=Path(app.instance_path)/'staff-access.txt'
            fd=os.open(access,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            entries=[(name,role,secrets.token_urlsafe(18)) for name,role in [('owner','admin'),('caller01','caller'),('packing01','packer')]]
            try:
                with os.fdopen(fd,'w') as handle:
                    handle.write('PRINTPRO3D staff access — PRIVATE, do not upload to GitHub.\n\n')
                    for name,role,password in entries:
                        handle.write(f'{name} ({role})\nPassword: {password}\n\n')
                with conn:
                    for name,role,password in entries:
                        conn.execute('INSERT INTO users(username,password_hash,role) VALUES(?,?,?)',(name,generate_password_hash(password,method="pbkdf2:sha256:1000000"),role))
            except Exception:
                access.unlink(missing_ok=True)
                raise
            print('Created three staff accounts. Passwords are in instance/staff-access.txt (private, Git-ignored).')
        elif args.command=='add-user':
            password=getpass.getpass('New password (12+ characters): ')
            if password!=getpass.getpass('Repeat password: '):
                raise SystemExit('Passwords did not match. Nothing changed.')
            try:
                add_user(conn,args.username.lower(),args.role,password)
            except (ValueError,sqlite3.IntegrityError) as error:
                raise SystemExit('Could not add user: '+str(error))
            print('User created. Named sign-in is now required; shared station passwords are disabled.')
        elif args.command=='list-users':
            for row in conn.execute('SELECT username,role,active FROM users ORDER BY username'):
                print(row['username'],row['role'],'active' if row['active'] else 'disabled')
        elif args.command=='disable-user':
            with conn:
                changed=conn.execute('UPDATE users SET active=0 WHERE username=?',(args.username.lower(),)).rowcount
            print('User disabled; access is revoked on the next request.' if changed else 'No matching user.')


if __name__=='__main__':
    main()
