"""PRINTPRO3D order management: one application, one SQLite database."""
import csv
import io
import os
import re
import secrets
import time
import hashlib
from urllib.parse import quote
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
from functools import wraps
from werkzeug.security import check_password_hash

from flask import Flask, abort, g, redirect, render_template, request, session, url_for, Response, send_file, jsonify
from . import automation, labels, sms, whatsapp, confirmations, dashboard, fde_reports, remote, website, handover, courier_followup, site_analytics


SCHEMA = '''
CREATE TABLE IF NOT EXISTS leads (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL,
 address TEXT NOT NULL DEFAULT '', city TEXT NOT NULL DEFAULT '',
 product TEXT NOT NULL DEFAULT '', quantity INTEGER NOT NULL DEFAULT 1,
 cod_cents INTEGER NOT NULL DEFAULT 0, weight_g INTEGER NOT NULL DEFAULT 0,
 notes TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'new',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS orders (
 id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL UNIQUE REFERENCES leads(id),
 status TEXT NOT NULL DEFAULT 'awaiting_booking', tracking TEXT UNIQUE,
 waybill TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS booking_jobs (
 order_id INTEGER PRIMARY KEY REFERENCES orders(id),
 state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
 reference TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id),
 actor TEXT NOT NULL, action TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
'''


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True, instance_path=os.environ.get('OMS_INSTANCE_PATH'))
    app.config.update(CLOUD_MODE=os.environ.get('OMS_CLOUD') == '1', SECRET_KEY=os.environ.get('OMS_SECRET') or secrets.token_hex(32),
                      DATABASE=str(Path(app.instance_path) / 'oms.sqlite3'),
                      ADMIN_PASSWORD=os.environ.get('OMS_ADMIN_PASSWORD'),
                      PACKER_PASSWORD=os.environ.get('OMS_PACKER_PASSWORD'),
                      ENABLE_LIVE_BOOKING=os.environ.get('OMS_ENABLE_LIVE_BOOKING') == '1',
                      MAX_CONTENT_LENGTH=5 * 1024 * 1024,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict',
                      SESSION_COOKIE_SECURE=os.environ.get('OMS_HTTPS') == '1')
    if config:
        app.config.update(config)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    if not os.environ.get('OMS_SECRET') and not app.config.get('TESTING'):
        secret_file = Path(app.instance_path)/'session-secret'
        try:
            fd = os.open(secret_file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd,'w') as handle:
                handle.write(secrets.token_hex(32))
        app.config['SECRET_KEY'] = secret_file.read_text().strip()

    def db():
        if 'db' not in g:
            g.db = sqlite3.connect(app.config['DATABASE'], timeout=10)
            g.db.row_factory = sqlite3.Row
            g.db.execute('PRAGMA foreign_keys=ON')
        return g.db

    @app.teardown_appcontext
    def close_db(error):
        conn = g.pop('db', None)
        if conn:
            conn.close()

    with app.app_context():
        db().executescript(SCHEMA)
        db().execute('PRAGMA journal_mode=WAL')
        automation.migrate(db())
        labels.migrate(db())
        sms.migrate(db())
        whatsapp.migrate(db())
        confirmations.migrate(db())
        dashboard.migrate(db())
        fde_reports.migrate(db())
        courier_followup.migrate(db())
        remote.migrate(db())
        handover.migrate(db())
        db().execute('CREATE TABLE IF NOT EXISTS login_limits (bucket TEXT PRIMARY KEY, started INTEGER NOT NULL, attempts INTEGER NOT NULL)')
        db().commit()

    remote.register(app,db)
    website.register(app,db)

    @app.get('/healthz')
    def healthz():
        db().execute('SELECT 1')
        return jsonify(ok=True)

    @app.context_processor
    def automation_context():
        return {'job_labels': automation.STATE_LABELS, 'worker': automation.worker_status(db()),
                'print_state':lambda oid:db().execute('SELECT * FROM print_jobs WHERE order_id=?',(oid,)).fetchone(), 'named_users':has_users(), 'new_intake_key':lambda:secrets.token_urlsafe(24)}

    def has_users():
        return db().execute('SELECT 1 FROM users LIMIT 1').fetchone() is not None

    def event(order_id, action):
        db().execute('INSERT INTO events(order_id,actor,action) VALUES(?,?,?)',
                     (order_id, session.get('username',session.get('role', 'local-demo')), action))

    def role_required(admin=False):
        def decorate(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                if app.config['ADMIN_PASSWORD'] or has_users():
                    if has_users():
                        user = db().execute('SELECT role,active FROM users WHERE username=?',(session.get('username'),)).fetchone()
                        if not user or not user['active']:
                            session.pop('role',None)
                        else:
                            session['role']=user['role']
                    if not session.get('role'):
                        return redirect(url_for('login'))
                    if admin and session['role'] not in ('admin','caller'):
                        abort(403)
                return fn(*args, **kwargs)
            return wrapped
        return decorate

    @app.before_request
    def guard():
        if request.endpoint=='healthz':return
        if request.blueprint in ('station','website'):return  # Bearer authentication; no cookie authority.
        if app.config['CLOUD_MODE'] and not has_users():abort(503,'Owner account must be configured before use.')
        # Unconfigured demo must remain loopback-only, including against DNS rebinding.
        if not app.config['ADMIN_PASSWORD'] and not has_users() and request.host.split(':')[0] not in ('localhost', '127.0.0.1'):
            abort(403)
        if session.get('username'):
            account=db().execute('SELECT active,packing_only FROM users WHERE username=?',(session['username'],)).fetchone()
            if not account or not account['active']:
                for key in ('username','role','packing_only'):session.pop(key,None)
                if request.endpoint not in ('login','static'):return redirect('/login')
            else:
                session['packing_only']=bool(account['packing_only'])
                if account['packing_only']:
                    if request.path=='/':return redirect('/packing')
                    if request.endpoint not in ('login','logout','static','packing','packing_handover'):abort(403)
        session.setdefault('csrf', secrets.token_hex(24))
        if request.method == 'POST' and not secrets.compare_digest(request.form.get('csrf', ''), session['csrf']):
            abort(400, 'Form expired. Reload and try again.')

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self' 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; object-src 'none'"
        return response

    @app.errorhandler(400)
    @app.errorhandler(409)
    def invalid(error):
        return render_template('error.html', message=error.description), error.code

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            username = request.form.get('username','').strip().lower()
            if app.config['CLOUD_MODE']:
                # Per account throttling is independent of proxy header trust.
                now=int(time.time())
                bucket=hashlib.sha256(username.encode()).hexdigest()
                with db():
                    db().execute('BEGIN IMMEDIATE')
                    db().execute('DELETE FROM login_limits WHERE started<?',(now-900,))
                    limit=db().execute('SELECT attempts FROM login_limits WHERE bucket=?',(bucket,)).fetchone()
                    if limit and limit[0]>=10:abort(429,'Too many sign-in attempts. Try again in 15 minutes.')
                    db().execute('INSERT INTO login_limits VALUES(?,?,1) ON CONFLICT(bucket) DO UPDATE SET attempts=attempts+1',(bucket,now))
            if has_users():
                user = db().execute('SELECT * FROM users WHERE username=? AND active=1',(username,)).fetchone()
                if not user or not check_password_hash(user['password_hash'],request.form.get('password','')):
                    abort(400,'Invalid sign-in.')
                role=user['role']
            else:
                role = request.form.get('role')
                expected = app.config.get('ADMIN_PASSWORD' if role == 'admin' else 'PACKER_PASSWORD')
                if role not in ('admin', 'packer') or not expected or not secrets.compare_digest(request.form.get('password', ''), expected):
                    abort(400, 'Invalid sign-in.')
            if app.config['CLOUD_MODE']:
                with db():db().execute('DELETE FROM login_limits WHERE bucket=?',(bucket,))
            session.clear()
            session.update(role=role, csrf=secrets.token_hex(24), packing_only=bool(user['packing_only']) if has_users() else False)
            if username and has_users():
                session['username']=username
            return redirect('/packing' if role == 'packer' else '/')
        return render_template('login.html')

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect('/login')

    @app.route('/station',methods=['GET','POST'])
    @role_required(admin=True)
    def station_settings():
        if not app.config['CLOUD_MODE']:abort(404)
        if session.get('role')!='admin':abort(403)
        token=None
        if request.method=='POST':
            if request.form.get('action')=='revoke':
                with db():db().execute('UPDATE home_station SET enabled=0 WHERE id=1')
            elif request.form.get('action')=='pair':
                try:token=remote.issue_token(db())
                except ValueError as exc:abort(409,str(exc))
            else:abort(400)
        return render_template('station.html',now=int(time.time()),health={r['kind']:dict(r) for r in db().execute('SELECT * FROM station_health')},station=db().execute('SELECT enabled,heartbeat,detail FROM home_station WHERE id=1').fetchone(),token=token)

    @app.get('/website-overview')
    @role_required(admin=True)
    def website_overview():
        from datetime import datetime
        from zoneinfo import ZoneInfo
        stamp=lambda value: datetime.fromtimestamp(value,ZoneInfo('Asia/Colombo')).strftime('%d %b, %I:%M %p') if value else 'Not synced'
        return render_template('website_overview.html',data=site_analytics.overview(db()),reports=fde_reports.REPORTS,stamp=stamp)

    @app.get('/dashboard')
    @role_required(admin=True)
    def dashboard_page():
        from datetime import datetime
        from zoneinfo import ZoneInfo
        stamp=lambda value: datetime.fromtimestamp(value,ZoneInfo('Asia/Colombo')).strftime('%d %b %Y, %I:%M %p') if value else 'Not synced yet'
        return render_template('dashboard.html',data=dashboard.overview(db()),
            totals={r['status']:dict(r) for r in db().execute('SELECT * FROM fde_report_totals')},
            callbacks=courier_followup.rows(db()),now=int(time.time()),reports=fde_reports.REPORTS,sync=db().execute('SELECT * FROM fde_report_sync WHERE id=1').fetchone(),stamp=stamp)

    @app.post('/dashboard/callbacks/<int:order_id>/contacted')
    @role_required(admin=True)
    def callback_contacted(order_id):
        if not db().execute('SELECT 1 FROM orders WHERE id=?',(order_id,)).fetchone():abort(404)
        with db():
            db().execute("""INSERT INTO courier_followups(order_id,contacted_at,contacted_by) VALUES(?,?,?)
              ON CONFLICT(order_id) DO UPDATE SET contacted_at=excluded.contacted_at,contacted_by=excluded.contacted_by""",
              (order_id,int(time.time()),session.get('username','staff')))
        return redirect(url_for('dashboard_page')+'#callbacks')

    @app.post('/dashboard/rack-costs')
    @role_required(admin=True)
    def rack_costs():
        if has_users() and session.get('role')!='admin':abort(403)
        try:dashboard.save_wear(db(),request.form.get('wear'))
        except ValueError as exc:abort(400,str(exc))
        return redirect(url_for('dashboard_page'))

    @app.post('/dashboard/refresh-courier')
    @role_required(admin=True)
    def dashboard_refresh():
        fde_reports.request_sync(db())
        return redirect(url_for('dashboard_page'))

    @app.post('/dashboard/orders/<int:order_id>/racks')
    @role_required(admin=True)
    def dashboard_racks(order_id):
        get_order(order_id)
        try:
            counts=[int(request.form.get(k,'')) for k in dashboard.COLORS]
            if any(n<0 or n>1000 for n in counts):raise ValueError()
        except ValueError:
            abort(400,'Enter whole rack counts between 0 and 1000.')
        with db():
            db().execute('INSERT OR REPLACE INTO rack_counts VALUES(?,?,?,?,?)',
              (order_id,*counts,'Confirmed by caller in dashboard'))
            event(order_id,'Dashboard rack counts corrected: black %d, white %d, gray %d'%tuple(counts))
        return redirect(url_for('dashboard_page'))

    @app.get('/')
    @role_required(admin=True)
    def index():
        query=request.args.get('q','').strip()[:100]
        match='%'+query+'%'
        return render_template('index.html',q=query,
            leads=db().execute("SELECT leads.*, (SELECT 'WEB-' || printf('%06d',lead_id) FROM website_orders WHERE lead_id=leads.id) AS website_reference FROM leads WHERE status IN ('new','callback') AND (name LIKE ? OR phone LIKE ?) ORDER BY id DESC",(match,match)).fetchall(),
            orders=db().execute('''SELECT o.*,l.name,l.product,l.quantity,l.cod_cents FROM orders o
            JOIN leads l ON l.id=o.lead_id WHERE l.name LIKE ? OR l.phone LIKE ? OR o.tracking LIKE ? OR
            printf('PP3D-%06d',o.id) LIKE ? ORDER BY o.id DESC''',(match,match,match,match)).fetchall())

    def fields():
        data = {k: request.form.get(k, '').strip() for k in ('name','phone','address','city','product','notes')}
        if not data['name'] or len(data['name']) > 150:
            abort(400, 'Enter a customer name (up to 150 characters).')
        phone = re.sub(r'[\s()-]', '', data['phone'])
        if phone.startswith('+94'):
            phone = '0' + phone[3:]
        if not re.fullmatch(r'0\d{9}', phone):
            abort(400, 'Enter a Sri Lankan phone number: 07XXXXXXXX or +94XXXXXXXXX.')
        data['phone'] = phone
        try:
            amount = Decimal(request.form.get('cod', '0'))
            if not amount.is_finite() or amount < 0 or amount > 10000000 or amount != amount.quantize(Decimal('.01')):
                raise ValueError()
            data.update(cod_cents=int(amount*100), quantity=int(request.form.get('quantity','1')), weight_g=int(request.form.get('weight_g','0')))
            if not 1 <= data['quantity'] <= 1000 or not 0 <= data['weight_g'] <= 100000:
                raise ValueError()
        except (ValueError, InvalidOperation):
            abort(400, 'Check COD, quantity and weight. COD allows two decimal places.')
        if any(len(v) > 2000 for v in data.values() if isinstance(v, str)):
            abort(400, 'A field is too long.')
        return data

    @app.post('/leads')
    @role_required(admin=True)
    def add_lead():
        data = fields()
        confirm = request.form.get('action')=='confirm'
        key=request.form.get('intake_key','')
        if confirm:
            if not re.fullmatch(r'[A-Za-z0-9_-]{20,80}',key):
                abort(400,'Reload the order form before saving.')
            if not all(data[k] for k in ('address','city','product')) or data['weight_g']<=0:
                abort(400,'Confirm address, city, product and packed weight before saving the order.')
            data.update(status='qualified',intake_key=key)
        with db():
            db().execute('BEGIN IMMEDIATE')
            if confirm:
                existing=db().execute('SELECT o.id FROM orders o JOIN leads l ON l.id=o.lead_id WHERE l.intake_key=?',(key,)).fetchone()
                if existing:
                    return redirect(url_for('index',saved=existing['id']) if request.form.get('return_to')=='desk' else url_for('order',order_id=existing['id']))
            cur = db().execute('INSERT INTO leads('+','.join(data)+') VALUES('+','.join('?' for _ in data)+')', tuple(data.values()))
            if confirm:
                order_id=db().execute('INSERT INTO orders(lead_id) VALUES(?)',(cur.lastrowid,)).lastrowid
                db().execute('INSERT INTO booking_jobs(order_id,reference) VALUES(?,?)',(order_id,f'PP3D-{order_id:06d}'))
                labels.enqueue(db(),order_id)
                sms.queue(db(),order_id,'processing')
                event(order_id,'caller saved confirmed Meta order; label ready for batch printing')
                return redirect(url_for('index',saved=order_id) if request.form.get('return_to')=='desk' else url_for('order',order_id=order_id))
        return redirect(url_for('lead', lead_id=cur.lastrowid))

    @app.route('/leads/<int:lead_id>', methods=['GET','POST'])
    @role_required(admin=True)
    def lead(lead_id):
        row = db().execute('SELECT * FROM leads WHERE id=?',(lead_id,)).fetchone()
        if not row:
            abort(404)
        website_order=db().execute('SELECT * FROM website_orders WHERE lead_id=?',(lead_id,)).fetchone()
        if request.method == 'POST':
            data = fields()
            action = request.form.get('action','save')
            if website_order and website_order['payment']=='bank':
                data['cod_cents']=0
                if action=='qualify' and not website_order['payment_verified'] and request.form.get('payment_verified')!='yes':
                    abort(400,'Verify the bank payment slip before confirming this order. COD remains zero.')
            if action not in ('save','qualify','reject','callback'):
                abort(400, 'Unknown action.')
            if action == 'qualify' and (not all(data[k] for k in ('address','city','product')) or data['weight_g'] <= 0):
                abort(400, 'Confirm address, city, product and parcel weight before qualifying.')
            with db():
                db().execute('BEGIN IMMEDIATE')
                if website_order and website_order['payment']=='bank' and request.form.get('payment_verified')=='yes':
                    db().execute('UPDATE website_orders SET payment_verified=1 WHERE lead_id=?',(lead_id,))
                current = db().execute('SELECT status FROM leads WHERE id=?',(lead_id,)).fetchone()
                if current['status'] == 'qualified':
                    return redirect('/')  # A double-click cannot create another order.
                db().execute('UPDATE leads SET '+','.join(k+'=?' for k in data)+' WHERE id=?',(*data.values(),lead_id))
                status = {'qualify':'qualified','reject':'rejected','callback':'callback'}.get(action,'new')
                db().execute('UPDATE leads SET status=? WHERE id=?',(status,lead_id))
                if action == 'qualify':
                    order_id = db().execute('INSERT INTO orders(lead_id) VALUES(?)',(lead_id,)).lastrowid
                    db().execute('INSERT INTO booking_jobs(order_id,reference) VALUES(?,?)',(order_id,f'PP3D-{order_id:06d}'))
                    labels.enqueue(db(),order_id)
                    sms.queue(db(),order_id,'processing')
                    event(order_id,'qualified; label ready for batch printing')
            return redirect('/')
        duplicate = db().execute('SELECT id FROM leads WHERE phone=? AND id!=?', (row['phone'],lead_id)).fetchall()
        return render_template('lead.html', lead=row, duplicates=duplicate,website_order=website_order)

    @app.route('/customer-returns',methods=['GET','POST'])
    @role_required(admin=True)
    def customer_returns():
        if request.method=='POST':
            state=request.form.get('status','')
            if state not in ('requested','reviewing','approved','declined','resolved'):abort(400,'Choose a valid status.')
            with db():db().execute('UPDATE customer_returns SET status=? WHERE id=?',(state,request.form.get('id')))
            return redirect(url_for('customer_returns'))
        rows=db().execute('SELECT r.*,l.name,l.phone,l.product FROM customer_returns r JOIN leads l ON l.id=r.lead_id ORDER BY r.id DESC').fetchall()
        return render_template('customer_returns.html',returns=rows)

    @app.get('/orders/<int:order_id>')
    @role_required(admin=True)
    def order(order_id):
        row = get_order(order_id)
        return render_template('order.html', order=row,
                               job=db().execute('SELECT * FROM booking_jobs WHERE order_id=?',(order_id,)).fetchone(),
                               events=db().execute('SELECT * FROM events WHERE order_id=? ORDER BY id',(order_id,)).fetchall())

    @app.get('/orders/<int:order_id>/whatsapp')
    @role_required()
    def whatsapp_update(order_id):
        row=get_order(order_id)
        try:phone=sms.mobile_number(row['phone'])
        except ValueError:abort(400,'Check the customer mobile number before opening WhatsApp.')
        ref=f'PP3D-{order_id:06d}'
        if row['order_status']=='dispatched':
            message=f"Hi {row['name']}, your PRINTPRO3D order {ref} has been handed to FDE courier. Tracking ID: {row['tracking']}. Thank you!"
        elif row['tracking']:
            message=whatsapp.tracking_message(row['name'],order_id,row['tracking'])
        else:
            message=f"Hi {row['name']}, your PRINTPRO3D order {ref} is confirmed and processing. We will share the tracking number when ready. Thank you!"
        response=redirect('https://wa.me/'+phone+'?text='+quote(message,safe=''))
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Cache-Control']='no-store'
        return response

    @app.route('/confirmations',methods=['GET','POST'])
    @role_required(admin=True)
    def confirmation_desk():
        error=None
        if request.method=='POST':
            try:
                mid=confirmations.queue(db(),request.form.get('name',''),request.form.get('phone',''),request.form.get('request_key',''))
                return redirect(url_for('confirmation_desk',sent=mid))
            except ValueError as exc:
                error=str(exc)
        return render_template('confirmations.html',error=error,sent=request.args.get('sent'),
            preview=confirmations.message('Customer'),
            messages=db().execute('SELECT * FROM whatsapp_confirmations ORDER BY id DESC LIMIT 100').fetchall()),400 if error else 200

    @app.post('/confirmations/<int:message_id>/retry')
    @role_required(admin=True)
    def confirmation_retry(message_id):
        with db():
            changed=db().execute("UPDATE whatsapp_confirmations SET state='queued',detail='' WHERE id=? AND state='blocked'",(message_id,)).rowcount
        if not changed:
            abort(409,'Only messages blocked before sending can be retried.')
        return redirect(url_for('confirmation_desk'))

    @app.get('/whatsapp')
    @role_required(admin=True)
    def whatsapp_queue():
        import time
        worker = db().execute('SELECT * FROM whatsapp_worker WHERE id=1').fetchone()
        online = bool(worker and time.time() - worker['heartbeat'] < 90)
        return render_template('whatsapp.html', messages=db().execute(
            'SELECT * FROM whatsapp_outbox ORDER BY id DESC LIMIT 200').fetchall(),
            whatsapp_online=online, whatsapp_status=worker['status'] if online else 'Worker offline')

    @app.post('/whatsapp/<int:message_id>/retry')
    @role_required(admin=True)
    def whatsapp_retry(message_id):
        with db():
            changed = db().execute("UPDATE whatsapp_outbox SET state='queued',detail='' WHERE id=? AND state='blocked'", (message_id,)).rowcount
        if not changed:
            abort(409, 'Only messages blocked before sending can be retried.')
        return redirect(url_for('whatsapp_queue'))

    @app.get('/courier')
    @role_required(admin=True)
    def courier_queue():
        jobs = db().execute('''SELECT j.*,l.name,l.city,l.product,l.quantity,o.status AS order_status
          FROM booking_jobs j JOIN orders o ON o.id=j.order_id JOIN leads l ON l.id=o.lead_id
          ORDER BY CASE WHEN j.state='succeeded' THEN 1 ELSE 0 END,j.order_id''').fetchall()
        return render_template('courier.html',jobs=jobs)

    @app.get('/help')
    @role_required()
    def help_page():
        return render_template('help.html')

    @app.route('/labels',methods=['GET','POST'])
    @role_required()
    def label_batches():
        error=None
        if request.method=='POST':
            try:
                ids=[int(value) for value in request.form.getlist('orders')]
                labels.queue_batch(db(),ids)
                return redirect(url_for('label_batches',queued=len(set(ids))))
            except ValueError as exc:error=str(exc)
        rows=db().execute("""SELECT p.*,l.name,l.product,l.quantity,o.created_at FROM print_jobs p
          JOIN orders o ON o.id=p.order_id JOIN leads l ON l.id=o.lead_id
          ORDER BY CASE WHEN p.state='ready' THEN 0 ELSE 1 END,o.id DESC""").fetchall()
        return render_template('labels.html',orders=rows,error=error,queued=request.args.get('queued')),400 if error else 200

    @app.get('/scan/status')
    @role_required()
    def scan_status():
        rows=db().execute("""SELECT j.order_id,j.assigned_waybill,j.state,j.message,l.name FROM booking_jobs j
          JOIN orders o ON o.id=j.order_id JOIN leads l ON l.id=o.lead_id
          WHERE j.assigned_waybill IS NOT NULL ORDER BY j.updated_at DESC LIMIT 20""").fetchall()
        return jsonify([dict(r) for r in rows])

    @app.route('/scan', methods=['GET','POST'])
    @role_required()
    def scan():
        if request.method == 'POST':
            reference=request.form.get('reference','').strip().upper()
            if not re.fullmatch(r'PP3D-[0-9]{6,}',reference):
                abort(400,'Scan the OMS order barcode first (PP3D-000001).')
            order_id=int(reference.split('-')[1])
            row=get_order(order_id)
            printed=db().execute("SELECT state,marked_printed FROM print_jobs WHERE order_id=?",(order_id,)).fetchone()
            if not printed or not (printed['marked_printed'] or printed['state']=='spooled'):
                abort(409,'Print this order label first, then scan its order barcode and courier sticker.')
            try:
                automation.reserve(db(),order_id,request.form.get('waybill_number',''),
                    (row['weight_g']+999)//1000,session.get('username',session.get('role','local-demo')),packing_confirmed=True)
                with db():event(order_id,'Printed label and courier sticker scanned; automatic FDE submission authorized')
            except automation.Conflict as error:abort(409,str(error))
            except ValueError as error:abort(400,str(error))
            if request.headers.get('Accept')=='application/json':
                return jsonify(order_id=order_id,name=row['name'],message='Queued for FDE booking')
            return redirect(url_for('scan',sent=order_id))
        rows=db().execute("""SELECT o.id,l.name,l.product,p.state,p.message,p.marked_printed FROM orders o
          JOIN leads l ON l.id=o.lead_id JOIN print_jobs p ON p.order_id=o.id
          JOIN booking_jobs j ON j.order_id=o.id WHERE j.state='pending' ORDER BY o.id""").fetchall()
        return render_template('scan.html',orders=rows,sent=request.args.get('sent'))

    @app.get('/orders/<int:order_id>/label')
    @role_required()
    def parcel_label(order_id):
        order=get_order(order_id)
        path=Path(app.instance_path)/'labels'/f'{order_id}.pdf'
        if path.exists():
            return send_file(path,mimetype='application/pdf')
        try:
            preview=labels.preview_label(dict(order),app.instance_path)
        except (OSError,ValueError,KeyError):
            abort(422,'Cannot prepare the label preview. Check sender settings, text length and unsupported characters. No print was queued.')
        return send_file(preview,mimetype='application/pdf',download_name=f'PP3D-{order_id:06d}-preview.pdf',max_age=0)

    @app.post('/orders/<int:order_id>/print-label')
    @role_required()
    def print_label(order_id):
        get_order(order_id)
        with db():
            db().execute('BEGIN IMMEDIATE')
            row=db().execute('SELECT state,marked_printed FROM print_jobs WHERE order_id=?',(order_id,)).fetchone()
            if row:
                if row['state'] in ('queued','rendering','sending'):abort(409,'Print is already pending.')
                if row['state']!='ready' and request.form.get('checked')!='yes':abort(400,'Check the printer queue and confirm you need another copy.')
                db().execute("UPDATE print_jobs SET state='ready',message='Ready for a new print batch',spool_id=NULL,batch_id=NULL WHERE order_id=?",(order_id,))
            else:labels.enqueue(db(),order_id)
            event(order_id,'Parcel label print requested')
        return redirect(url_for('label_batches'))

    @app.post('/orders/<int:order_id>/confirm-packing')
    @role_required()
    def confirm_packing(order_id):
        get_order(order_id)
        try:
            automation.confirm_packing(db(),order_id,request.form.get('waybill_number',''),
                request.form.get('weight_kg',''),session.get('username',session.get('role','local-demo')))
        except automation.Conflict as error:
            abort(409,str(error))
        except ValueError as error:
            abort(400,str(error))
        return redirect('/packing')

    @app.post('/orders/<int:order_id>/prepare')
    @role_required()
    def prepare(order_id):
        get_order(order_id)
        try:
            automation.reserve(db(),order_id,request.form.get('waybill_number',''),
                               request.form.get('weight_kg',''),session.get('username',session.get('role','local-demo')))
        except automation.Conflict as error:
            abort(409,str(error))
        except ValueError as error:
            abort(400,str(error))
        return redirect('/packing' if session.get('role')=='packer' else url_for('order',order_id=order_id))

    @app.post('/orders/<int:order_id>/approve-submit')
    @role_required(admin=True)
    def approve_submit(order_id):
        if not app.config['ENABLE_LIVE_BOOKING'] or not automation.worker_status(db())['submit_enabled']:
            abort(409,'Live submission is disabled or the browser worker is offline.')
        if request.form.get('reviewed') != 'yes':
            abort(400,'Review the exact FDE form and confirm before sending.')
        try:
            automation.transition(db(),order_id,'prepared','approved','Caller approved one submission of the reviewed FDE form',session.get('username',session.get('role','local-demo')))
        except automation.Conflict as error:
            abort(409,str(error))
        return redirect(url_for('order',order_id=order_id))

    @app.post('/orders/<int:order_id>/retry-prepare')
    @role_required(admin=True)
    def retry_prepare(order_id):
        if request.form.get('not_created') != 'yes':
            abort(400,'First check FDE and confirm this waybill/order has not been booked.')
        with db():
            changed = db().execute("""UPDATE booking_jobs SET state='queued',message='Requeued after operator verified no FDE booking.'
              WHERE order_id=? AND state IN ('blocked','needs_review') AND assigned_waybill IS NOT NULL""",(order_id,)).rowcount
            if not changed:
                abort(409,'This job cannot be retried in its current state.')
            event(order_id,'operator checked FDE: no parcel created; preparation requeued')
        return redirect(url_for('order',order_id=order_id))

    def get_order(order_id):
        row = db().execute('SELECT l.*,o.id AS order_id,o.status AS order_status,o.tracking,o.waybill FROM orders o JOIN leads l ON l.id=o.lead_id WHERE o.id=?',(order_id,)).fetchone()
        if not row:
            abort(404)
        return row

    @app.post('/orders/<int:order_id>/booking')
    @role_required(admin=True)
    def booking(order_id):
        get_order(order_id)
        if request.form.get('record_checked') != 'yes':
            abort(400,'Confirm that the parcel is already booked in FDE. To fill FDE, use automatic form fill instead.')
        tracking = request.form.get('tracking','').strip()
        try:
            automation.confirm_booking(db(),order_id,tracking,session.get('username',session.get('role','local-demo')))
        except automation.Conflict as error:
            abort(409,str(error))
        except ValueError as error:
            abort(400,str(error))
        except sqlite3.IntegrityError:
            abort(409, 'That tracking number belongs to another order.')
        return redirect(url_for('order',order_id=order_id))

    @app.post('/orders/<int:order_id>/waybill')
    @role_required(admin=True)
    def upload_waybill(order_id):
        row = get_order(order_id)
        if not row['tracking']:
            abort(409,'Record the FDE tracking number first.')
        upload = request.files.get('waybill')
        content = upload.read() if upload else b''
        if not content.startswith(b'%PDF-'):
            abort(400,'Upload the official FDE waybill PDF.')
        folder = Path(app.instance_path)/'waybills'
        folder.mkdir(exist_ok=True)
        filename = f'{order_id}-{secrets.token_hex(8)}.pdf'
        (folder/filename).write_bytes(content)
        with db():
            db().execute('UPDATE orders SET waybill=? WHERE id=?',(filename,order_id))
            event(order_id,'official waybill attached')
        return redirect(url_for('order',order_id=order_id))

    @app.get('/orders/<int:order_id>/waybill')
    @role_required()
    def waybill(order_id):
        row = get_order(order_id)
        if not row['waybill']:
            abort(404)
        return send_file(Path(app.instance_path)/'waybills'/row['waybill'], mimetype='application/pdf', download_name=f'PP3D-{order_id}-waybill.pdf')

    @app.get('/packing')
    @role_required()
    def packing():
        if session.get('packing_only'):return render_template('handover.html',data=handover.report(db()),scanner=True)
        status=request.args.get('status','active')
        if status not in ('active','packed','dispatched','all'):
            status='active'
        query=request.args.get('q','').strip()[:100]
        rows = db().execute('''SELECT o.*,l.name,l.product,l.quantity,l.notes,l.weight_g,
          j.state AS job_state,j.assigned_waybill,j.weight_kg,j.message,j.packing_confirmed FROM orders o
          JOIN leads l ON l.id=o.lead_id JOIN booking_jobs j ON j.order_id=o.id ORDER BY o.id''').fetchall()
        rows=[r for r in rows if (status=='all' or (status=='active' and r['status'] not in ('packed','dispatched')) or r['status']==status) and
              query.lower() in ' '.join(str(r[k] or '') for k in ('id','name','product','tracking','assigned_waybill')).lower()]
        return render_template('packing.html',orders=rows,q=query,selected_status=status)

    @app.post('/orders/<int:order_id>/pack')
    @role_required()
    def pack(order_id):
        with db():
            changed = db().execute("UPDATE orders SET status='packed' WHERE id=? AND status='booked' AND (waybill IS NOT NULL OR EXISTS(SELECT 1 FROM print_jobs p WHERE p.order_id=orders.id AND (p.marked_printed=1 OR p.state='spooled')))",(order_id,)).rowcount
            if not changed:
                abort(409,'Packing requires a booked order and a printed parcel label.')
            event(order_id,'packed')
        return redirect('/packing')

    @app.post('/orders/<int:order_id>/dispatch')
    @role_required()
    def dispatch(order_id):
        try:handover.record(db(),'PP3D-%06d'%order_id,session.get('username','local-demo'),scan=False)
        except ValueError as exc:abort(409,str(exc))
        return redirect('/packing?status=packed')

    @app.post('/packing/handover')
    @role_required()
    def packing_handover():
        try:
            result=handover.record(db(),request.form.get('barcode',''),session.get('username','local-demo'))
        except ValueError as exc:return jsonify(error=str(exc)),409
        stats=handover.report(db())
        return jsonify(**result,today_count=stats['count'],total_count=stats['total'])

    @app.get('/handovers')
    @role_required(admin=True)
    def handover_report():
        try:data=handover.report(db(),request.args.get('date'))
        except ValueError as exc:abort(400,str(exc))
        return render_template('handover.html',data=data,scanner=False)

    @app.get('/sms')
    @role_required(admin=True)
    def sms_queue():
        rows=db().execute('SELECT * FROM sms_outbox ORDER BY id DESC LIMIT 100').fetchall()
        return render_template('sms.html',messages=rows,sms_enabled=bool(sms.settings(app.instance_path).get('enabled')))

    @app.get('/orders.csv')
    @role_required(admin=True)
    def export():
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(['order_reference','name','phone','address','city','product','quantity','cod_lkr','weight_g','tracking','status'])
        def safe(value):
            value = str(value or '')
            return "'"+value if value.lstrip().startswith(('=','+','-','@')) else value
        for row in db().execute('SELECT o.id,l.name,l.phone,l.address,l.city,l.product,l.quantity,l.cod_cents,l.weight_g,o.tracking,o.status FROM orders o JOIN leads l ON l.id=o.lead_id ORDER BY o.id'):
            values = list(row)
            values[0] = f'PP3D-{row[0]:06d}'
            values[7] = f'{row[7]/100:.2f}'
            writer.writerow([safe(v) for v in values])
        return Response(out.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=printpro3d-orders.csv'})

    return app
