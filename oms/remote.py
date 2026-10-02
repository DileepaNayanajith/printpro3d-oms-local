"""Authenticated home-station queue. A lost write acknowledgement is never replayed."""
import hashlib
import json
import secrets
import time
import uuid
from flask import Blueprint, abort, current_app, jsonify, request
from . import automation, whatsapp, fde_reports, labels, courier_followup

KINDS=('print','fde','whatsapp','confirmation','reports')
TABLES={'whatsapp':'whatsapp_outbox','confirmation':'whatsapp_confirmations'}
LEASE_SECONDS=600


def migrate(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS home_station (
      id INTEGER PRIMARY KEY CHECK(id=1), token_hash TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
      heartbeat INTEGER, detail TEXT NOT NULL DEFAULT 'Not connected');
    CREATE TABLE IF NOT EXISTS station_health (
      kind TEXT PRIMARY KEY, heartbeat INTEGER NOT NULL, ready INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS station_tasks (
      id TEXT PRIMARY KEY, kind TEXT NOT NULL, source TEXT NOT NULL,
      payload TEXT NOT NULL, state TEXT NOT NULL, updated_at INTEGER NOT NULL,
      result TEXT, UNIQUE(kind,source));
    ''')
    c.commit()


def issue_token(c):
    with c:expire(c)
    if c.execute("SELECT 1 FROM station_tasks WHERE state IN ('prepared','executing')").fetchone():
        raise ValueError('Finish or reconcile active station jobs before changing its key.')
    token=secrets.token_urlsafe(40)
    with c:
        c.execute('DELETE FROM station_health')
        c.execute('INSERT OR REPLACE INTO home_station(id,token_hash) VALUES(1,?)',
                  (hashlib.sha256(token.encode()).hexdigest(),))
    return token


def source_state(c,task,state,detail):
    kind=task['kind']
    if kind=='print':
        c.execute('UPDATE print_jobs SET state=?,message=? WHERE batch_id=?',(state,detail,task['source']))
    elif kind=='fde':
        c.execute('UPDATE booking_jobs SET state=?,message=?,updated_at=? WHERE order_id=?',
                  (state,detail,int(time.time()),int(task['source'].split(':')[0])))
    elif kind in TABLES:
        c.execute(f'UPDATE {TABLES[kind]} SET state=?,detail=?,updated_at=? WHERE id=?',
                  (state,detail,int(time.time()),int(task['source'].split(':')[0])))
    elif kind=='reports':
        c.execute('UPDATE fde_report_sync SET state=?,detail=? WHERE id=1',(state,detail))


def expire(c):
    """Stop uncertain jobs for review. Never return an expired claim for execution."""
    for task in c.execute("SELECT * FROM station_tasks WHERE state IN ('prepared','executing') AND updated_at<?",(int(time.time())-LEASE_SECONDS,)).fetchall():
        source_state(c,task,'partial' if task['kind']=='reports' else 'needs_review',
                     'Home PC disconnected during this job. Check the result before retrying.')
        c.execute("UPDATE station_tasks SET state='expired' WHERE id=?",(task['id'],))


def claim(c,kind):
    now=int(time.time())
    with c:
        c.execute('BEGIN IMMEDIATE')
        expire(c)
        # One home station and one outstanding task per capability.
        if c.execute("SELECT 1 FROM station_tasks WHERE kind=? AND state IN ('prepared','executing')",(kind,)).fetchone():return None
        payload=None;source=None
        if kind=='fde':
            r=c.execute("SELECT order_id FROM booking_jobs WHERE state='queued' AND packing_confirmed=1 ORDER BY order_id LIMIT 1").fetchone()
            if r:
                payload=automation.snapshot(c,r[0]);source=str(r[0])
                c.execute("UPDATE booking_jobs SET state='preparing',attempts=attempts+1,updated_at=? WHERE order_id=?",(now,r[0]))
        elif kind=='print':
            r=c.execute("SELECT batch_id FROM print_jobs WHERE state='queued' AND batch_id IS NOT NULL ORDER BY created_at LIMIT 1").fetchone()
            if r:
                source=r[0]
                orders=[dict(o) for o in c.execute('''SELECT l.name,l.address,l.city,l.phone,l.product,l.quantity,l.cod_cents,o.id AS order_id
                  FROM print_jobs p JOIN orders o ON o.id=p.order_id JOIN leads l ON l.id=o.lead_id
                  WHERE p.batch_id=? AND p.state='queued' ORDER BY o.id''',(source,))]
                payload={'orders':orders,'sender':labels.load_settings(current_app.instance_path)['sender']}
                c.execute("UPDATE print_jobs SET state='rendering',message='Home PC preparing A4 labels' WHERE batch_id=?",(source,))
        elif kind in TABLES:
            table=TABLES[kind]
            if kind=='confirmation':courier_followup.reconcile(c)
            c.execute(f"UPDATE {table} SET state='stale',detail='Older than 24 hours; check before sending.' WHERE state='queued' AND created_at<?",(now-86400,))
            r=c.execute(f"SELECT * FROM {table} WHERE state='queued' ORDER BY id LIMIT 1").fetchone()
            if r:
                payload=dict(r);source=str(r['id'])+':'+uuid.uuid4().hex
                c.execute(f"UPDATE {table} SET state='preparing',updated_at=? WHERE id=?",(now,r['id']))
        elif kind=='reports':
            c.execute("""UPDATE fde_report_sync SET state='requested',requested_at=?,detail='Scheduled refresh waiting for home PC'
              WHERE id=1 AND state NOT IN ('requested','running')
              AND max(coalesce(finished_at,0),coalesce(requested_at,0))<=?""",(now,now-300))
            r=c.execute("SELECT * FROM fde_report_sync WHERE state='requested'").fetchone()
            if r:
                source=uuid.uuid4().hex;payload={}
                c.execute("UPDATE fde_report_sync SET state='running',detail='Home PC reading FDE reports' WHERE id=1")
        if payload is None:return None
        # Every explicit retry is a new attempt; old task IDs remain immutable.
        if kind=='fde':source+=':'+uuid.uuid4().hex
        task={'id':uuid.uuid4().hex,'kind':kind,'source':source,'payload':payload}
        c.execute('INSERT INTO station_tasks VALUES(?,?,?,?,?,?,NULL)',
                  (task['id'],kind,source,json.dumps(payload),'prepared',now))
        return task


def arm(c,task_id):
    with c:
        c.execute('BEGIN IMMEDIATE');expire(c)
        task=c.execute('SELECT * FROM station_tasks WHERE id=?',(task_id,)).fetchone()
        if not task or task['state']!='prepared':abort(409,'Job is no longer safe to start.')
        if task['kind']=='confirmation':
            follow=c.execute('SELECT order_id FROM courier_followups WHERE message_id=?',(int(task['source'].split(':')[0]),)).fetchone()
            if follow and not courier_followup.eligible(c,follow[0],int(time.time())):abort(409,'Courier status changed or expired; do not send.')
        state={'fde':'submitting','print':'sending','whatsapp':'sending','confirmation':'sending','reports':'running'}[task['kind']]
        source_state(c,task,state,'Home PC started one attempt')
        c.execute("UPDATE station_tasks SET state='executing',updated_at=? WHERE id=?",(int(time.time()),task_id))


def complete(c,task_id,result):
    outcome=result.get('outcome')
    if outcome not in ('success','blocked','login_required','uncertain'):abort(400,'Invalid result.')
    with c:
        c.execute('BEGIN IMMEDIATE')
        task=c.execute('SELECT * FROM station_tasks WHERE id=?',(task_id,)).fetchone()
        if not task:abort(404)
        encoded=json.dumps(result,sort_keys=True)
        if task['state']=='done':
            if task['result']!=encoded:abort(409,'Different result already recorded.')
            return
        if task['state'] not in ('prepared','executing'):abort(409,'Expired job requires manual review.')
        if outcome=='success' and task['state']!='executing':abort(409,'Job was not started.')
        if task['state']=='executing' and outcome in ('blocked','login_required'):abort(409,'An attempted write must be reviewed.')
        kind=task['kind'];payload=json.loads(task['payload']);now=int(time.time())
        if outcome!='success':
            state='needs_review' if outcome=='uncertain' else ('login_required' if outcome=='login_required' and kind=='fde' else 'blocked')
            if kind=='print' and outcome=='blocked':state='failed'
            if kind=='reports':state='login_required' if outcome=='login_required' else 'partial'
            source_state(c,task,state,{'uncertain':'Result uncertain. Check before retrying.', 'blocked':'Preparation failed. Check the home PC before retrying.', 'login_required':'Sign in on the home PC, then retry.'}[outcome])
        elif kind=='fde':
            oid=payload['order_id'];tracking=payload['assigned_waybill']
            job=c.execute('SELECT * FROM booking_jobs WHERE order_id=?',(oid,)).fetchone()
            if job['state']!='submitting' or job['assigned_waybill']!=tracking:abort(409,'Booking state changed.')
            if c.execute("UPDATE orders SET tracking=?,status='booked' WHERE id=? AND status='awaiting_booking'",(tracking,oid)).rowcount!=1:abort(409)
            source_state(c,task,'succeeded','Home PC observed fresh FDE success receipt')
            whatsapp.queue(c,oid)
            automation.log(c,oid,'home-station','FDE booking confirmed by home PC')
        elif kind=='print':
            source_state(c,task,'spooled','Sent to the home printer; check paper output.')
        elif kind in TABLES:
            source_state(c,task,'sent','WhatsApp sent check mark observed on home PC; delivery/read not confirmed.')
        elif kind=='reports':
            reports=result.get('reports',{})
            if not isinstance(reports,dict) or not reports or set(reports)-set(fde_reports.REPORTS):abort(400)
            for status,report in reports.items():
                if not isinstance(report,dict):abort(400)
                total=report.get('total');rows=report.get('rows')
                if type(total)!=int or total<0 or not isinstance(rows,dict) or len(rows)>2000 or len(rows)>total:abort(400)
                for tracking,reference in rows.items():
                    if not isinstance(tracking,str) or not tracking.isdigit() or not 4<=len(tracking)<=20 or not isinstance(reference,str) or len(reference)>100:abort(400)
                c.execute('INSERT OR REPLACE INTO fde_report_totals VALUES(?,?,?,?)',(status,total,len(rows),now))
                if len(rows)==total:c.execute('DELETE FROM fde_observations WHERE status=?',(status,))
                for tracking,reference in rows.items():c.execute('INSERT OR REPLACE INTO fde_observations VALUES(?,?,?,?)',(tracking,status,reference,now))
            all_done=len(reports)==len(fde_reports.REPORTS)
            courier_followup.queue_fresh(c)
            c.execute('UPDATE fde_report_sync SET state=?,finished_at=?,detail=? WHERE id=1',('complete' if all_done else 'partial',now,'Home PC refreshed courier reports.' if all_done else 'Some reports could not be read; older counts retained.'))
        c.execute("UPDATE station_tasks SET state='done',result=?,updated_at=? WHERE id=?",(encoded,now,task_id))


def register(app,db):
    bp=Blueprint('station',__name__,url_prefix='/api/station')
    @bp.before_request
    def authenticate():
        if not current_app.config.get('CLOUD_MODE'):abort(404)
        header=request.headers.get('Authorization','')
        if not header.startswith('Bearer '):abort(401)
        token=header[7:]
        row=db().execute('SELECT * FROM home_station WHERE id=1 AND enabled=1').fetchone()
        if not row or not secrets.compare_digest(row['token_hash'],hashlib.sha256(token.encode()).hexdigest()):abort(401)
        if request.method!='POST' or not request.is_json or not isinstance(request.get_json(),dict):abort(400)
    @bp.post('/poll')
    def poll():
        data=request.get_json();kind=data.get('kind')
        if kind not in KINDS:abort(400)
        c=db();now=int(time.time())
        with c:
            c.execute('INSERT OR REPLACE INTO station_health VALUES(?,?,?)',(kind,now,int(data.get('ready') is True)))
            c.execute('UPDATE home_station SET heartbeat=?,detail=? WHERE id=1',(now,'Connected'))
            if kind=='fde':automation.heartbeat(c,True)
            if kind=='whatsapp':c.execute('INSERT OR REPLACE INTO whatsapp_worker VALUES(1,?,?)',(now,'Home PC connected' if data.get('ready') is True else 'Login required on home PC'))
            if kind=='fde' and data.get('ready') is True:
                c.execute("UPDATE booking_jobs SET state='queued' WHERE state='login_required' AND packing_confirmed=1")
        whatsapp.ingest(c)
        if data.get('ready') is not True:return jsonify(task=None)
        return jsonify(task=claim(c,kind))
    @bp.post('/<task_id>/status')
    def status(task_id):
        with db():expire(db())
        task=db().execute('SELECT state FROM station_tasks WHERE id=?',(task_id,)).fetchone()
        if not task:abort(404)
        return jsonify(state=task['state'])
    @bp.post('/<task_id>/touch')
    def touch(task_id):
        with db():
            changed=db().execute("UPDATE station_tasks SET updated_at=? WHERE id=? AND state IN ('prepared','executing') AND updated_at>=?",(int(time.time()),task_id,int(time.time())-LEASE_SECONDS)).rowcount
        if not changed:abort(409)
        return jsonify(ok=True)
    @bp.post('/<task_id>/start')
    def start(task_id):arm(db(),task_id);return jsonify(ok=True)
    @bp.post('/<task_id>/result')
    def result(task_id):complete(db(),task_id,request.get_json());return jsonify(ok=True)
    app.register_blueprint(bp)
