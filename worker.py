"""One visible browser worker; staff sign in themselves. No password collection."""
import argparse
import fcntl
import os
import time
from pathlib import Path

from oms import create_app
from oms.automation import (connection, heartbeat, recover_interrupted, claim,
                            prepare_one, submit_one, snapshot)
from oms.fde_browser import FDEBrowser, PORTAL_URL


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--login', action='store_true', help='Open dedicated FDE profile for manual login only')
    parser.add_argument('--enable-submit', action='store_true', help='Allow one click ONLY after admin approves that prepared order in OMS')
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
                input('Sign in in the browser. After login, press Enter here to close and save the session. ')
                browser.close()
                return
            adapter = FDEBrowser(page)
            active = None
            with connection(app.config['DATABASE']) as conn:
                recover_interrupted(conn)
                print('FDE worker started. Live submit: ' + ('per-order approval required' if args.enable_submit else 'disabled'))
                try:
                    while True:
                        heartbeat(conn, args.enable_submit)
                        if active is not None:
                            job = snapshot(conn, active)
                            if job['state'] == 'approved':
                                submit_one(conn, active, adapter, args.enable_submit)
                            elif job['state'] == 'succeeded' or job['state'] == 'queued':
                                active = None
                            # Keep current page visible for review or manual reconciliation.
                        else:
                            active = claim(conn)
                            if active is not None:
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
