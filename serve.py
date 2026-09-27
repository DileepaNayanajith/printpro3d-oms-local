"""Staff pilot server. LAN mode requires named accounts before binding."""
import argparse
import ipaddress
import sqlite3
import subprocess
import sys
from pathlib import Path
from waitress import serve
from oms import create_app


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default='127.0.0.1',help='This computer’s private Wi-Fi IPv4 address, or 127.0.0.1')
    parser.add_argument('--port',type=int,default=5055)
    args=parser.parse_args()
    address=ipaddress.ip_address(args.host)
    if address.version!=4 or not (address.is_private or address.is_loopback) or address.is_unspecified:
        raise SystemExit('Choose a specific private IPv4 address, not a public or wildcard address.')
    app=create_app()
    with sqlite3.connect(app.config['DATABASE']) as conn:
        count=conn.execute('SELECT COUNT(*) FROM users WHERE active=1').fetchone()[0]
    if not address.is_loopback and not count:
        raise SystemExit('Create staff accounts first: python manage.py bootstrap')

    bindings=[f'{args.host}:{args.port}']
    if not address.is_loopback:
        bindings.append(f'127.0.0.1:{args.port}')
    # Printing must also work when staff start serve.py directly. The worker's
    # file lock prevents a second sender if a print worker already exists.
    project = Path(__file__).resolve().parent
    with (Path(app.instance_path) / 'print-worker.log').open('a') as log:
        subprocess.Popen([sys.executable, str(project / 'print_worker.py')],
                         cwd=str(project), stdout=log, stderr=subprocess.STDOUT,
                         start_new_session=True)
    serve(app, listen=' '.join(bindings), threads=4)



if __name__=='__main__':
    main()
