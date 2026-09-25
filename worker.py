"""One visible browser worker; staff sign in themselves. No password collection."""
import argparse
import fcntl
import os
import time
from pathlib import Path

from oms import create_app
from oms.automation import (connection, heartbeat, recover_interrupted, claim,
                            prepare_one, submit_one, submit_packed, snapshot, transition)
from oms.fde_browser import FDEBrowser, PORTAL_URL


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--login', action='store_true', help='Wait for manual login, then run without restarting the browser')
    parser.add_argument('--enable-submit', action='store_true', help='Allow one submission after packing confirmation or explicit order review')
    args = parser.parse_args()
    app = create_app()
    root = Path(app.instance_path)
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(root / 'browser-binaries'))
    from playwright.sync_api import sync_playwright
    profile = root / 'fde-browser-profile'
    profile.mkdir(mode=0o700, exist_ok=True)
    os.chmod(profile, 0o700)
    with (root / 'fde-worker.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another FDE browser worker/login window is already running.')
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch_persistent_context(str(profile), headless=False)
            page = browser.pages[0] if browser.pages else browser.new_page()
            # This standalone profile does not borrow the Codex/browser login session.
            page.goto(PORTAL_URL)
            if args.login:
                input('Sign in in the browser, then press Enter here. This same browser will stay open for the worker. ')
            adapter = FDEBrowser(page)
            active = None
            with connection(app.config['DATABASE']) as conn:
                recover_interrupted(conn)
                print('FDE worker started. Live submit: ' + ('packing confirmation or per-order review required' if args.enable_submit else 'disabled'))
                try:
                    while True:
                        heartbeat(conn, args.enable_submit)
                        if active is not None:
                            job = snapshot(conn, active)
                            if job['state'] == 'login_required' and adapter.signed_in():
                                transition(conn, active, 'login_required', 'queued', 'Login restored; resuming form preparation')
                                active = None
                            elif job['state'] == 'prepared' and job['packing_confirmed']:
                                submit_packed(conn, active, adapter, args.enable_submit)
                            elif job['state'] == 'approved':
                                submit_one(conn, active, adapter, args.enable_submit)
                            elif job['state'] == 'succeeded' or job['state'] == 'queued':
                                active = None
                            # Keep current page visible for review or manual reconciliation.
                        else:
                            waiting = conn.execute("SELECT order_id FROM booking_jobs WHERE state='login_required' ORDER BY order_id LIMIT 1").fetchone()
                            active = waiting['order_id'] if waiting else claim(conn)
                            if active is not None:
                                if snapshot(conn,active)['state']=='preparing':
                                    prepare_one(conn, active, adapter)
                        page.wait_for_timeout(1500)
                except KeyboardInterrupt:
                    print('Worker stopped. Unfinished browser jobs require review on restart.')
                finally:
                    with conn:
                        conn.execute('DELETE FROM browser_worker WHERE id=1')
                    recover_interrupted(conn)
                    browser.close()


if __name__ == '__main__':
    main()
