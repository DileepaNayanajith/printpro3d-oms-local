"""Customer-only identities. Independent from staff accounts and sessions."""
import hashlib
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path
from flask import request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash


def migrate(c):
    c.executescript("""
      CREATE TABLE IF NOT EXISTS customers(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT, google_sub TEXT UNIQUE, name TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS customer_sessions(token_hash TEXT PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id), expires INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS customer_limits(bucket TEXT PRIMARY KEY, started INTEGER NOT NULL, attempts INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS customer_returns(id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL UNIQUE REFERENCES leads(id), customer_id INTEGER NOT NULL REFERENCES customers(id), reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'requested', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    """)
    columns={r[1] for r in c.execute('PRAGMA table_info(website_orders)')}
    for name,definition in [('customer_id','INTEGER REFERENCES customers(id)'),('payment',"TEXT NOT NULL DEFAULT 'cod'"),('total_cents','INTEGER NOT NULL DEFAULT 0'),('payment_verified','INTEGER NOT NULL DEFAULT 0')]:
        if name not in columns:c.execute('ALTER TABLE website_orders ADD COLUMN '+name+' '+definition)
    if 'payment' not in columns:
        c.execute('UPDATE website_orders SET total_cents=(SELECT cod_cents FROM leads WHERE id=lead_id)')
        c.execute("UPDATE website_orders SET payment='bank' WHERE lead_id IN (SELECT id FROM leads WHERE notes LIKE 'Website order | BANK PAYMENT%')")
        c.execute("UPDATE leads SET cod_cents=0 WHERE status='new' AND id IN (SELECT lead_id FROM website_orders WHERE payment='bank')")
    c.commit()


def identity(c):
    token=request.headers.get('X-Customer-Session','')
    if not token:return None
    return c.execute('SELECT c.* FROM customers c JOIN customer_sessions s ON s.customer_id=c.id WHERE s.token_hash=? AND s.expires>?',(hashlib.sha256(token.encode()).hexdigest(),int(time.time()))).fetchone()


def google_client(app):
    value=app.config.get('GOOGLE_CLIENT_ID') or os.environ.get('OMS_GOOGLE_CLIENT_ID','')
    path=Path(app.instance_path)/'google-client-id'
    if not value and not app.config.get('TESTING') and path.exists():value=path.read_text().strip()
    return value


def register(bp,app,db):
    def throttle(bucket):
        now=int(time.time())
        with db():
            db().execute('INSERT INTO customer_limits VALUES(?,?,1) ON CONFLICT(bucket) DO UPDATE SET attempts=CASE WHEN started<? THEN 1 ELSE attempts+1 END,started=CASE WHEN started<? THEN excluded.started ELSE started END',(bucket,now,now-900,now-900))
        return db().execute('SELECT attempts FROM customer_limits WHERE bucket=?',(bucket,)).fetchone()[0]>15

    def session_for(customer):
        token=secrets.token_urlsafe(32)
        with db():
            db().execute('DELETE FROM customer_sessions WHERE expires<?',(int(time.time()),))
            db().execute('INSERT INTO customer_sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),customer['id'],int(time.time())+7*86400))
        return jsonify(token=token,customer={'name':customer['name']})

    @bp.get('/api/website/account/config')
    def config():return jsonify(google_client_id=google_client(app))

    @bp.post('/api/website/account/<action>')
    def auth(action):
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict):return jsonify(error='Invalid request.'),400
        if action=='logout':
            with db():db().execute('DELETE FROM customer_sessions WHERE token_hash=?',(hashlib.sha256(request.headers.get('X-Customer-Session','').encode()).hexdigest(),))
            return jsonify(ok=True)
        if action not in ('register','login','google'):return jsonify(error='Not found.'),404
        client=request.headers.get('X-Store-Client','unknown')[:100]
        username=str(data.get('username','')).strip().lower()
        if throttle('client:'+client) or (username and throttle('user:'+username)):
            return jsonify(error='Too many attempts. Please try again in 15 minutes.'),429
        if action=='google':
            audience=google_client(app)
            if not audience:return jsonify(error='Google sign-in setup is pending. Please use username and password.'),503
            try:
                from google.oauth2 import id_token
                from google.auth.transport.requests import Request
                claims=id_token.verify_oauth2_token(str(data.get('credential','')),Request(),audience)
                if not claims.get('sub') or not claims.get('email_verified'):raise ValueError()
            except Exception:
                return jsonify(error='Google sign-in could not be verified. Try again.'),401
            with db():
                db().execute('INSERT OR IGNORE INTO customers(google_sub,name) VALUES(?,?)',(claims['sub'],str(claims.get('name','Customer'))[:150]))
            return session_for(db().execute('SELECT * FROM customers WHERE google_sub=?',(claims['sub'],)).fetchone())
        password=data.get('password','')
        if not re.fullmatch(r'[a-z0-9_.-]{3,40}',username) or not isinstance(password,str) or not 10<=len(password)<=128:
            return jsonify(error='Use a username with 3–40 letters/numbers and a password of 10–128 characters.'),400
        if action=='register':
            name=str(data.get('name','')).strip()
            if not 1<=len(name)<=150:return jsonify(error='Enter your name.'),400
            try:
                with db():db().execute('INSERT INTO customers(username,password_hash,name) VALUES(?,?,?)',(username,generate_password_hash(password,method="pbkdf2:sha256:1000000"),name))
            except sqlite3.IntegrityError:return jsonify(error='That username is unavailable.'),409
        customer=db().execute('SELECT * FROM customers WHERE username=?',(username,)).fetchone()
        if not customer or not customer['password_hash'] or not check_password_hash(customer['password_hash'],password):
            return jsonify(error='Username or password is incorrect.'),401
        return session_for(customer)

    @bp.get('/api/website/account/orders')
    def orders():
        customer=identity(db())
        if not customer:return jsonify(error='Please sign in.'),401
        rows=db().execute("""SELECT w.*,l.product,l.status AS lead_status,o.id AS order_id,o.status,o.tracking,
          f.status AS courier_status,f.observed_at,r.status AS return_status
          FROM website_orders w JOIN leads l ON l.id=w.lead_id
          LEFT JOIN orders o ON o.lead_id=l.id
          LEFT JOIN fde_observations f ON f.tracking=REPLACE(COALESCE(o.tracking,''),'CCP','')
          LEFT JOIN customer_returns r ON r.lead_id=l.id WHERE w.customer_id=? ORDER BY l.id DESC""",(customer['id'],)).fetchall()
        return jsonify(customer={'name':customer['name']},orders=[dict(reference='WEB-%06d'%r['lead_id'],order_reference='PP3D-%06d'%r['order_id'] if r['order_id'] else None,product=r['product'],total_cents=r['total_cents'],payment=r['payment'],payment_verified=bool(r['payment_verified']),status=r['status'] or ('cancelled' if r['lead_status']=='rejected' else 'awaiting_confirmation'),tracking=r['tracking'],courier_status=r['courier_status'],observed_at=r['observed_at'],return_status=r['return_status']) for r in rows])

    @bp.post('/api/website/account/returns')
    def returns():
        customer=identity(db())
        if not customer:return jsonify(error='Please sign in.'),401
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict):return jsonify(error='Invalid request.'),400
        reference=str(data.get('reference',''))
        reason=str(data.get('reason','')).strip()
        if not re.fullmatch(r'WEB-\d{6,}',reference) or not 10<=len(reason)<=2000:return jsonify(error='Enter a return reason (10–2000 characters).'),400
        lead_id=int(reference[4:])
        if not db().execute('SELECT 1 FROM website_orders WHERE lead_id=? AND customer_id=?',(lead_id,customer['id'])).fetchone():return jsonify(error='Order not found.'),404
        with db():
            db().execute('INSERT OR IGNORE INTO customer_returns(lead_id,customer_id,reason) VALUES(?,?,?)',(lead_id,customer['id'],reason))
        return jsonify(ok=True,status='requested')
