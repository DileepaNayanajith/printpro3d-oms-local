"""Automatic tracking notifications through a dedicated, locally linked Chrome."""
import argparse
import fcntl
import os
import signal
import time
from pathlib import Path
from oms import create_app, whatsapp
from oms.automation import connection
from oms.whatsapp_browser import WhatsAppBrowser, LoginRequired


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-number', help='Send one setup test to an explicitly authorized number')
    args = parser.parse_args()
    app = create_app()
    root = Path(app.instance_path)
    profile = root / 'whatsapp-browser-profile'
    profile.mkdir(mode=0o700, exist_ok=True)
    os.chmod(profile, 0o700)
    def stop(*_):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, stop)
    from playwright.sync_api import sync_playwright
    with (root / 'whatsapp-worker.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('WhatsApp worker is already running.')
        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(str(profile), channel='chrome', headless=False)
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.set_default_timeout(10000)
            page.goto('https://web.whatsapp.com/')
            adapter = WhatsAppBrowser(page)
            print('PRINTPRO3D WhatsApp: keep this dedicated Chrome window signed in.', flush=True)
            with connection(app.config['DATABASE']) as conn:
                whatsapp.recover(conn)
                try:
                    if args.test_number:
                        from oms.sms import mobile_number
                        phone = mobile_number(args.test_number)
                        # An exclusive persistent marker prevents a test being resent after a crash.
                        marker = root / ('whatsapp-test-' + phone + '.txt')
                        if marker.exists():
                            raise SystemExit('Test was already attempted. Check WhatsApp and the local result file.')
                        page.get_by_role('button', name='New chat', exact=True).wait_for(timeout=120000)
                        body = ('PRINTPRO3D WhatsApp setup test\n\n'
                                'Automatic tracking notifications are being tested. This is not a real shipment.\n\n'
                                'For future orders, your tracking ID and this link will appear here:\n'
                                'https://www.fdedomestic.com\n\nThank you!\nPRINTPRO3D')
                        adapter.prepare(phone, body)
                        with marker.open('x') as f:
                            f.write('sending; do not retry automatically')
                        try:
                            adapter.send(phone, body)
                        except Exception as error:
                            marker.write_text('needs_review; send may have occurred; ' + type(error).__name__)
                            raise
                        marker.write_text('sent: WhatsApp check mark observed')
                        print('Test sent; WhatsApp check mark observed.', flush=True)
                    while True:
                        whatsapp.ingest(conn)
                        status = 'Connected — automatic tracking messages enabled' if adapter.signed_in() else 'Login required — link WhatsApp in Chrome'
                        with conn:
                            conn.execute('INSERT OR REPLACE INTO whatsapp_worker VALUES(1,?,?)', (int(time.time()), status))
                        if adapter.signed_in():
                            for table in ('whatsapp_outbox','whatsapp_confirmations'):
                                try:
                                    whatsapp.send_one(conn, adapter, table)
                                except LoginRequired:
                                    break
                                except Exception:
                                    with conn:
                                        conn.execute(f"UPDATE {table} SET state='blocked',detail='Could not verify the recipient or draft. Check WhatsApp before retrying.' WHERE id=(SELECT id FROM {table} WHERE state='queued' ORDER BY id LIMIT 1)")
                        page.wait_for_timeout(3000)
                except KeyboardInterrupt:
                    pass
                finally:
                    with conn:
                        conn.execute('DELETE FROM whatsapp_worker WHERE id=1')
                    whatsapp.recover(conn)
                    browser.close()


if __name__ == '__main__':
    main()
