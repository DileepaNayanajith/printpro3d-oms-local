"""Windows home station. Cloud owns orders; this PC owns printers and browser logins."""
import argparse
import json
import os
import signal
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from oms.station_client import API, execute, recover
from oms import labels, fde_reports


def station_root():
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'PRINTPRO3D-station'


@contextmanager
def lock(path):
    with path.open('a+b') as f:
        f.seek(0);f.write(b'0');f.flush();f.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except (OSError,BlockingIOError):raise SystemExit('This station worker is already open.')
        yield


def printer_command(settings,pdf):
    executable=Path(settings['sumatra'])
    if not executable.is_file():raise ValueError('Install SumatraPDF and run station setup again.')
    if not settings.get('printer'):raise ValueError('Choose the HP printer in station setup.')
    return [str(executable),'-print-to',settings['printer'],'-print-settings','paper=A4,landscape,fit,simplex','-silent',str(pdf)]


def run(kind,root,settings):
    api=API(settings['url'],settings['token'])
    journal=root/(kind+'-attempt.json')
    stop=False
    def stopping(*args):
        nonlocal stop
        stop=True
    signal.signal(signal.SIGINT,stopping);signal.signal(signal.SIGTERM,stopping)
    from playwright.sync_api import sync_playwright
    from oms.fde_browser import FDEBrowser,PORTAL_URL
    from oms.whatsapp_browser import WhatsAppBrowser
    with lock(root/(kind+'.lock')), sync_playwright() as p:
        browser=None;adapter=None;report_page=None
        if kind in ('fde','whatsapp'):
            browser=p.chromium.launch_persistent_context(str(root/(kind+'-profile')),headless=False)
            page=browser.pages[0] if browser.pages else browser.new_page()
            page.goto(PORTAL_URL if kind=='fde' else 'https://web.whatsapp.com/')
            adapter=FDEBrowser(page) if kind=='fde' else WhatsAppBrowser(page)
            if kind=='fde':report_page=browser.new_page();page.bring_to_front()
        print('Home station running. Keep this window open. Sign in to browser windows if requested.',flush=True)
        try:
            while not stop:
                try:
                    recover(api,journal)
                    kinds=('fde','reports') if kind=='fde' else ('whatsapp','confirmation') if kind=='whatsapp' else ('print',)
                    for queue in kinds:
                        ready=kind=='print' or adapter.signed_in()
                        task=api.post('poll',{'kind':queue,'ready':ready})['task']
                        if not task:continue
                        def prepare(task):
                            payload=task['payload']
                            if queue=='fde':adapter.prepare(payload);adapter.verify(payload)
                            elif queue in ('whatsapp','confirmation'):
                                if queue=='confirmation' and payload.get('include_photo'):
                                    adapter.prepare_photo(payload['phone'],payload['body'],Path(__file__).parent/'oms/static/products/hot-wheels-rack.png')
                                else:adapter.prepare(payload['phone'],payload['body'])
                            elif queue=='print':
                                pdf=root/(task['id']+'.pdf')
                                labels.render_batch(payload['orders'],payload['sender'],pdf)
                                return printer_command(settings,pdf)
                        def perform(task,context):
                            payload=task['payload']
                            if queue=='fde':
                                adapter.verify(payload)
                                if adapter.submit() is not True:raise RuntimeError('No success receipt')
                            elif queue in ('whatsapp','confirmation'):
                                if queue=='confirmation' and payload.get('include_photo'):adapter.send_photo(payload['phone'],payload['body'])
                                else:adapter.send(payload['phone'],payload['body'])
                            elif queue=='print':
                                result=subprocess.run(context,timeout=90,capture_output=True)
                                if result.returncode:raise RuntimeError('Printer result uncertain')
                            elif queue=='reports':
                                reports={}
                                for status in fde_reports.REPORTS:
                                    try:
                                        total,rows=fde_reports.read_report(report_page,status,lambda:api.post(task['id']+'/touch',{}))
                                        reports[status]={'total':total,'rows':rows}
                                    except fde_reports.FDELoginRequired:break
                                    except Exception:continue
                                if not reports:raise RuntimeError('No reports available')
                                return {'reports':reports}
                        execute(api,task,journal,prepare,perform)
                        if queue=='print':(root/(task['id']+'.pdf')).unlink(missing_ok=True)
                        # Give booking jobs priority over reports until next poll.
                        break
                except Exception as exc:
                    # Do not log URLs, response bodies, tokens or customer details.
                    print('Connection/job needs attention ('+type(exc).__name__+'). Will retry cloud acknowledgement only.',flush=True)
                if browser:page.wait_for_timeout(4000)
                else:time.sleep(4)
        finally:
            if browser:browser.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--kind',choices=['print','fde','whatsapp'],required=True)
    args=parser.parse_args();root=station_root();root.mkdir(parents=True,exist_ok=True)
    settings=json.loads((root/'settings.json').read_text(encoding='utf-8'))
    run(args.kind,root,settings)
