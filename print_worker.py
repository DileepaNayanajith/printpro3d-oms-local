"""Main-computer print queue; never automatically retry an uncertain print."""
import fcntl
import time
from pathlib import Path
from oms import create_app
from oms.automation import connection
from oms.labels import print_one

if __name__=='__main__':
    app=create_app();root=Path(app.instance_path)
    with (root/'print-worker.lock').open('w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('Print worker already running.')
        with connection(app.config['DATABASE']) as conn:
            with conn:
                conn.execute("UPDATE print_jobs SET state='queued' WHERE state='rendering'")
                conn.execute("UPDATE print_jobs SET state='needs_review',message='Printer worker stopped during sending; check printer queue before reprinting.' WHERE state='sending'")
            while True:
                print_one(conn,root)
                time.sleep(2)
