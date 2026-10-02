"""Authenticated storefront intake. Unverified customer orders enter caller review."""
import hashlib
import json
import os
import re
import secrets
from pathlib import Path
from flask import Blueprint, request, jsonify
from . import customers, site_analytics


def register(app, db):
    with app.app_context():
        db().execute("CREATE TABLE IF NOT EXISTS website_orders (request_id TEXT PRIMARY KEY, digest TEXT NOT NULL, lead_id INTEGER NOT NULL REFERENCES leads(id))")
        db().commit()
        customers.migrate(db())
        site_analytics.migrate(db())
    bp = Blueprint('website', __name__)

    @bp.before_request
    def authenticate_bridge():
        token = app.config.get('WEBSITE_TOKEN')
        if token is None and not app.config.get('TESTING'):
            path = Path(app.instance_path)/'website-token'
            token = os.environ.get('OMS_WEBSITE_TOKEN', '').strip() or (path.read_text().strip() if path.exists() else '')
        if not token or not secrets.compare_digest(request.headers.get('Authorization', ''), 'Bearer '+token):
            return jsonify(error='Unauthorized'), 401

    @bp.post('/api/website/visit')
    def visit():
        if request.content_length is None or request.content_length>2048:
            return jsonify(error='Invalid event'),400
        try:site_analytics.ingest(db(),request.get_json(silent=True))
        except ValueError:return jsonify(error='Invalid event'),400
        return '',204

    @bp.post('/api/website/orders')
    def intake():
        customer=customers.identity(db())
        if request.headers.get('X-Customer-Session') and not customer:
            return jsonify(error='Your session expired. Sign in again before ordering.'),401
        data = request.get_json(silent=True)
        try:
            if not isinstance(data, dict): raise ValueError()
            key = data['request_id']
            if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{20,80}', key): raise ValueError()
            fields = {k: str(data.get(k, '')).strip() for k in ('name','phone','address','city','product','notes')}
            if any(not fields[k] for k in ('name','phone','address','city','product')): raise ValueError()
            if any(len(v)>2000 for v in fields.values()) or len(fields['name'])>150: raise ValueError()
            phone = re.sub(r'[\s()-]', '', fields['phone'])
            if phone.startswith('+94'): phone = '0'+phone[3:]
            if not re.fullmatch(r'0\d{9}', phone): raise ValueError()
            fields['phone'] = phone
            quantity, amount = data['quantity'], data['total_cents']
            if type(quantity) is not int or not 1 <= quantity <= 1000: raise ValueError()
            if type(amount) is not int or not 0 <= amount <= 1000000000: raise ValueError()
            payment = data['payment']
            if payment not in ('cod', 'bank'): raise ValueError()
        except (KeyError, TypeError, ValueError):
            return jsonify(error='Check customer details and order items.'), 400
        digest = hashlib.sha256(json.dumps({'data':data,'customer_id':customer['id'] if customer else None}, sort_keys=True).encode()).hexdigest()
        with db():
            db().execute('BEGIN IMMEDIATE')
            old = db().execute('SELECT * FROM website_orders WHERE request_id=?', (key,)).fetchone()
            if old:
                if old['digest'] != digest: return jsonify(error='This checkout was already saved with different details.'), 409
                return jsonify(reference='WEB-%06d'%old['lead_id'], status='received'), 200
            fields['notes'] = ('Website order | '+('Cash on delivery' if payment=='cod' else 'BANK PAYMENT UNVERIFIED — confirm payment before dispatch')+' | Total Rs. %.2f\n'%(amount/100)+fields['notes'])
            # Full amount remains visible for review; never assume a bank payment was received.
            fields.update(quantity=quantity,cod_cents=0 if payment=='bank' else amount,weight_g=0,status='new')
            cur=db().execute('INSERT INTO leads('+','.join(fields)+') VALUES('+','.join('?' for _ in fields)+')',tuple(fields.values()))
            db().execute('INSERT INTO website_orders(request_id,digest,lead_id,customer_id,payment,total_cents) VALUES(?,?,?,?,?,?)',(key,digest,cur.lastrowid,customer['id'] if customer else None,payment,amount))
            return jsonify(reference='WEB-%06d'%cur.lastrowid, status='received'), 201
    customers.register(bp,app,db)
    app.register_blueprint(bp)
