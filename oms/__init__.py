"""PRINTPRO3D order management: one application, one SQLite database."""
import csv
import io
import os
import re
import secrets
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
from functools import wraps

from flask import Flask, abort, g, redirect, render_template, request, session, url_for, Response, send_file


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
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(SECRET_KEY=os.environ.get('OMS_SECRET') or secrets.token_hex(32),
                      DATABASE=str(Path(app.instance_path) / 'oms.sqlite3'),
                      ADMIN_PASSWORD=os.environ.get('OMS_ADMIN_PASSWORD'),
                      PACKER_PASSWORD=os.environ.get('OMS_PACKER_PASSWORD'),
                      MAX_CONTENT_LENGTH=5 * 1024 * 1024,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict',
                      SESSION_COOKIE_SECURE=os.environ.get('OMS_HTTPS') == '1')
    if config:
        app.config.update(config)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

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

    def event(order_id, action):
        db().execute('INSERT INTO events(order_id,actor,action) VALUES(?,?,?)',
                     (order_id, session.get('role', 'local-demo'), action))

    def role_required(admin=False):
        def decorate(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                if app.config['ADMIN_PASSWORD']:
                    if not session.get('role'):
                        return redirect(url_for('login'))
                    if admin and session['role'] != 'admin':
                        abort(403)
                return fn(*args, **kwargs)
            return wrapped
        return decorate

    @app.before_request
    def guard():
        # Unconfigured demo must remain loopback-only, including against DNS rebinding.
        if not app.config['ADMIN_PASSWORD'] and request.host.split(':')[0] not in ('localhost', '127.0.0.1'):
            abort(403)
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
            role = request.form.get('role')
            expected = app.config.get('ADMIN_PASSWORD' if role == 'admin' else 'PACKER_PASSWORD')
            if role not in ('admin', 'packer') or not expected or not secrets.compare_digest(request.form.get('password', ''), expected):
                abort(400, 'Invalid sign-in.')
            session.clear()
            session.update(role=role, csrf=secrets.token_hex(24))
            return redirect('/packing' if role == 'packer' else '/')
        return render_template('login.html')

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect('/login')

    @app.get('/')
    @role_required(admin=True)
    def index():
        return render_template('index.html', leads=db().execute("SELECT * FROM leads WHERE status != 'qualified' ORDER BY id DESC").fetchall(),
                               orders=db().execute('SELECT o.*, l.name,l.product,l.quantity,l.cod_cents FROM orders o JOIN leads l ON l.id=o.lead_id ORDER BY o.id DESC').fetchall())

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
        with db():
            cur = db().execute('INSERT INTO leads('+','.join(data)+') VALUES('+','.join('?' for _ in data)+')', tuple(data.values()))
        return redirect(url_for('lead', lead_id=cur.lastrowid))

    @app.route('/leads/<int:lead_id>', methods=['GET','POST'])
    @role_required(admin=True)
    def lead(lead_id):
        row = db().execute('SELECT * FROM leads WHERE id=?',(lead_id,)).fetchone()
        if not row:
            abort(404)
        if request.method == 'POST':
            data = fields()
            action = request.form.get('action','save')
            if action not in ('save','qualify','reject','callback'):
                abort(400, 'Unknown action.')
            if action == 'qualify' and (not all(data[k] for k in ('address','city','product')) or data['weight_g'] <= 0):
                abort(400, 'Confirm address, city, product and parcel weight before qualifying.')
            with db():
                db().execute('BEGIN IMMEDIATE')
                current = db().execute('SELECT status FROM leads WHERE id=?',(lead_id,)).fetchone()
                if current['status'] == 'qualified':
                    return redirect('/')  # A double-click cannot create another order.
                db().execute('UPDATE leads SET '+','.join(k+'=?' for k in data)+' WHERE id=?',(*data.values(),lead_id))
                status = {'qualify':'qualified','reject':'rejected','callback':'callback'}.get(action,'new')
                db().execute('UPDATE leads SET status=? WHERE id=?',(status,lead_id))
                if action == 'qualify':
                    order_id = db().execute('INSERT INTO orders(lead_id) VALUES(?)',(lead_id,)).lastrowid
                    db().execute('INSERT INTO booking_jobs(order_id,reference) VALUES(?,?)',(order_id,f'PP3D-{order_id:06d}'))
                    event(order_id,'qualified; booking queued')
            return redirect('/')
        duplicate = db().execute('SELECT id FROM leads WHERE phone=? AND id!=?', (row['phone'],lead_id)).fetchall()
        return render_template('lead.html', lead=row, duplicates=duplicate)

    @app.get('/orders/<int:order_id>')
    @role_required(admin=True)
    def order(order_id):
        row = get_order(order_id)
        return render_template('order.html', order=row, events=db().execute('SELECT * FROM events WHERE order_id=? ORDER BY id',(order_id,)).fetchall())

    def get_order(order_id):
        row = db().execute('SELECT l.*,o.id AS order_id,o.status AS order_status,o.tracking,o.waybill FROM orders o JOIN leads l ON l.id=o.lead_id WHERE o.id=?',(order_id,)).fetchone()
        if not row:
            abort(404)
        return row

    @app.post('/orders/<int:order_id>/booking')
    @role_required(admin=True)
    def booking(order_id):
        get_order(order_id)
        tracking = request.form.get('tracking','').strip()
        if not re.fullmatch(r'[A-Za-z0-9-]{4,64}', tracking):
            abort(400, 'Enter the tracking number confirmed by FDE.')
        try:
            with db():
                changed = db().execute("UPDATE orders SET tracking=?,status='booked' WHERE id=? AND status='awaiting_booking'",(tracking,order_id)).rowcount
                if not changed:
                    abort(409, 'This order is already booked. Refresh the page.')
                db().execute("UPDATE booking_jobs SET state='succeeded' WHERE order_id=?",(order_id,))
                event(order_id,'FDE booking manually reconciled')
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
        rows = db().execute("SELECT o.*, l.name,l.product,l.quantity,l.notes FROM orders o JOIN leads l ON l.id=o.lead_id WHERE o.status IN ('booked','packed') ORDER BY o.id").fetchall()
        return render_template('packing.html',orders=rows)

    @app.post('/orders/<int:order_id>/pack')
    @role_required()
    def pack(order_id):
        with db():
            changed = db().execute("UPDATE orders SET status='packed' WHERE id=? AND status='booked' AND waybill IS NOT NULL",(order_id,)).rowcount
            if not changed:
                abort(409,'Packing requires a booked order and an attached FDE waybill.')
            event(order_id,'packed')
        return redirect('/packing')

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
