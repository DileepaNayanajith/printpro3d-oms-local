"""Read-only FDE report snapshots. Booking writes never use this browser tab."""
import re
import json
import time

REPORTS={
 'waiting':('Waiting','waiting_parcel.php'),
 'pickup':('Picked up','pickup_parcel.php'),
 'processing':('Processing','processing_parcel.php'),
 'dispatched':('Dispatched','dispatched_parcel.php'),
 'rearranged':('Rearranged','rearranged_parcel.php'),
 'rescheduled':('Rescheduled','rescheduled_parcel.php'),
 'delivered':('Delivered','delivered_parcel.php'),
 'return_pending':('Returning','return_pending_parcel.php'),
 'return_complete':('Returned','return_complete_parcel.php'),
 'transferred':('Transferred','transferred_parcel.php'),
 'hold':('On hold','hold_parcel.php'),
}

class FDELoginRequired(RuntimeError):
    pass


def migrate(c):
    c.execute('''CREATE TABLE IF NOT EXISTS fde_report_sync (
      id INTEGER PRIMARY KEY CHECK(id=1),state TEXT NOT NULL DEFAULT 'idle',
      requested_at INTEGER,finished_at INTEGER,detail TEXT NOT NULL DEFAULT '')''')
    c.execute("INSERT OR IGNORE INTO fde_report_sync(id) VALUES(1)")
    c.execute('''CREATE TABLE IF NOT EXISTS fde_report_totals (
      status TEXT PRIMARY KEY,total INTEGER NOT NULL,sampled INTEGER NOT NULL,
      observed_at INTEGER NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS fde_observations (
      tracking TEXT PRIMARY KEY,status TEXT NOT NULL,reference TEXT NOT NULL,
      observed_at INTEGER NOT NULL)''')
    c.commit()


def request_sync(c):
    with c:
        return c.execute("UPDATE fde_report_sync SET state='requested',requested_at=?,detail='Waiting for the FDE worker to finish any booking.' WHERE id=1 AND state NOT IN ('requested','running')",(int(time.time()),)).rowcount


def read_report(page,status,heartbeat=lambda: None):
    heartbeat()
    page.goto('https://www.fdedomestic.com/client/'+REPORTS[status][1],wait_until='domcontentloaded',timeout=30000)
    if 'signIn' in page.url:raise FDELoginRequired('Sign in to FDE, then refresh courier data.')
    page.get_by_text(re.compile(r'(?:Total\s+)?Parcel Count\s*-\s*[\d,]+|Sorry!\s*No Records')).first.wait_for(timeout=20000)
    text=page.locator('body').inner_text()
    found=re.search(r'(?:Total\s+)?Parcel Count\s*-\s*([\d,]+)',text)
    if found:total=int(found[1].replace(',',''))
    elif re.search(r'Sorry!\s*No Records',text):total=0
    else:raise RuntimeError('FDE report count could not be read.')
    result={};last=None
    # Read bounded history as well as exception queues for delivered-order reconciliation.
    limit=20 if status in ('waiting','rearranged','rescheduled','return_pending','return_complete','delivered','hold') else 1
    for index in range(limit):
        heartbeat()
        rows=page.locator('table tr').evaluate_all('(rows)=>rows.map(r=>Array.from(r.querySelectorAll("td")).map(c=>c.innerText))')
        fingerprint=str(rows)
        if fingerprint==last:raise RuntimeError('FDE pagination did not advance.')
        last=fingerprint
        for cells in rows:
            if not cells:continue
            m=re.match(r'\s*(\d{4,20})\b',cells[0])
            if not m:continue
            ref=re.search(r'PP3D-\d+',cells[0])
            result[m[1]]=ref[0] if ref else ''
        if len(result)>=total or index+1>=limit:break
        next_link=page.get_by_role('link',name='Next',exact=True)
        if not next_link.count() or not next_link.is_visible():break
        next_link.click()
        page.wait_for_function('''(old)=>{const rows=Array.from(document.querySelectorAll("table tr")).map(r=>Array.from(r.querySelectorAll("td")).map(c=>c.innerText));return rows.some(r=>/^\\s*\\d{4,20}\\b/.test(r[0]||"")) && JSON.stringify(rows)!==old}''',arg=json.dumps(rows,separators=(',',':')),timeout=15000)
        page.get_by_text(re.compile(r'(?:Total\s+)?Parcel Count\s*-')).first.wait_for(timeout=15000)
    return total,result


def run_requested(c,page,heartbeat):
    with c:
        claimed=c.execute("UPDATE fde_report_sync SET state='running',detail='Reading FDE parcel reports…' WHERE id=1 AND state='requested'").rowcount
    if not claimed:return False
    failures=[]
    for status in REPORTS:
        heartbeat()
        try:
            total,rows=read_report(page,status,heartbeat)
            now=int(time.time())
            with c:
                c.execute('INSERT OR REPLACE INTO fde_report_totals VALUES(?,?,?,?)',(status,total,len(rows),now))
                # Clear observations from this category only when all rows were observed.
                if len(rows)==total:c.execute('DELETE FROM fde_observations WHERE status=?',(status,))
                for tracking,ref in rows.items():
                    c.execute('INSERT OR REPLACE INTO fde_observations VALUES(?,?,?,?)',(tracking,status,ref,now))
        except FDELoginRequired:
            with c:
                c.execute("UPDATE fde_report_sync SET state='login_required',finished_at=?,detail='Sign in to the FDE browser, then click Refresh FDE data. Previous counts remain unchanged.' WHERE id=1",(int(time.time()),))
            return True
        except Exception as exc:
            print("FDE report",status,type(exc).__name__,str(exc)[:500],flush=True)
            failures.append(REPORTS[status][0])
    with c:
        c.execute('UPDATE fde_report_sync SET state=?,finished_at=?,detail=? WHERE id=1',
          ('partial' if failures else 'complete',int(time.time()),
           'Could not refresh: '+', '.join(failures)+'. Check FDE login and try again.' if failures else 'Courier report refresh complete.'))
    return True
