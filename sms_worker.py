"""Text.lk sender. Startup recovery never retries uncertain sends."""
import fcntl
import time
from pathlib import Path
from oms import create_app,sms
from oms.automation import connection

if __name__=='__main__':
    app=create_app();root=Path(app.instance_path)
    with (root/'sms-worker.lock').open('w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('SMS worker is already running.')
        with connection(app.config['DATABASE']) as conn:
            with conn:conn.execute("UPDATE sms_outbox SET state='needs_review' WHERE state='sending'")
            while True:
                sms.send_one(conn,root)
                time.sleep(2)
