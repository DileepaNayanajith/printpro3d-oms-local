"""Consent-aware website Purchase outbox. Never sends customer contact details."""
import json
import os
import re
import sqlite3
import threading
import time
import urllib.request

PIXEL_ID = '1770603234189018'


def migrate(c):
    c.executescript('''
      CREATE TABLE IF NOT EXISTS meta_attribution (
        lead_id INTEGER PRIMARY KEY REFERENCES leads(id), payload TEXT NOT NULL, created INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS meta_purchase_outbox (
        order_id INTEGER PRIMARY KEY REFERENCES orders(id), payload TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt INTEGER NOT NULL DEFAULT 0, created INTEGER NOT NULL, sent INTEGER);
    ''')
    c.commit()


def validate(data, total_cents):
    if not isinstance(data, dict) or data.get('consent') is not True:
        return None
    # Meta cookies are captured only after the customer's separate advertising opt-in.
    user = {}
    for key in ('fbp', 'fbc'):
        value = data.get(key)
        pattern = r'fb\.\d\.\d{10,16}\.[A-Za-z0-9_-]{1,500}'
        if isinstance(value, str) and re.fullmatch(pattern, value):
            user[key] = value
    if not user:
        return None
    agent = data.get('client_user_agent')
    if isinstance(agent, str) and 1 <= len(agent) <= 512 and all(32 <= ord(char) <= 126 for char in agent):
        user['client_user_agent'] = agent
    items = data.get('contents')
    if not isinstance(items, list) or not 1 <= len(items) <= 50:
        return None
    clean = []
    for item in items:
        if not isinstance(item, dict): return None
        sku, qty, price = item.get('id'), item.get('quantity'), item.get('item_price')
        if not isinstance(sku, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', sku): return None
        if type(qty) is not int or not 1 <= qty <= 99: return None
        if type(price) not in (int, float) or not 0 <= price <= 1000000: return None
        clean.append(dict(id=sku, quantity=qty, item_price=price))
    value = round(sum(i['quantity'] * i['item_price'] for i in clean), 2)
    shipping = data.get('shipping')
    if type(shipping) not in (int, float) or shipping not in (0, 400): return None
    if round((value + shipping) * 100) != total_cents: return None
    return dict(user_data=user, custom_data=dict(currency='LKR', value=value, contents=clean,
                content_ids=[i['id'] for i in clean], content_type='product',
                num_items=sum(i['quantity'] for i in clean)), total_cents=total_cents)


def remember(c, lead_id, data, total_cents):
    valid = validate(data, total_cents)
    if valid:
        c.execute('INSERT OR IGNORE INTO meta_attribution(lead_id,payload,created) VALUES(?,?,?)',
                  (lead_id, json.dumps(valid), int(time.time())))


def enqueue(c, order_id):
    row = c.execute('''SELECT o.status,w.payment,w.payment_verified,w.total_cents,a.payload,a.created,
                       l.cod_cents FROM orders o JOIN leads l ON l.id=o.lead_id
                       JOIN website_orders w ON w.lead_id=o.lead_id
                       JOIN meta_attribution a ON a.lead_id=o.lead_id WHERE o.id=?''', (order_id,)).fetchone()
    if not row or row['status'] not in ('awaiting_booking','booked','packed','dispatched','delivered'):
        return
    if row['payment'] == 'bank' and not row['payment_verified']: return
    if row['payment'] == 'cod' and row['cod_cents'] != row['total_cents']: return
    now = int(time.time())
    if now - row['created'] > 30 * 86400: return
    saved = json.loads(row['payload'])
    if saved['total_cents'] != row['total_cents']: return
    event = dict(event_name='Purchase', event_time=now, event_id=f'purchase-PP3D-{order_id:06d}',
                 action_source='website', event_source_url='https://printpro3d.lk/checkout',
                 user_data=saved['user_data'], custom_data=saved['custom_data'])
    c.execute('INSERT OR IGNORE INTO meta_purchase_outbox(order_id,payload,created) VALUES(?,?,?)',
              (order_id, json.dumps(event), now))


def deliver(c, token, send=None, now=None):
    now = int(time.time()) if now is None else now
    with c:
        c.execute('DELETE FROM meta_attribution WHERE created<?',(now-30*86400,))
    if not token: return 0
    count = 0
    # Atomic leases prevent two web workers from sending the same row concurrently.
    for _ in range(20):
        with c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute("SELECT * FROM meta_purchase_outbox WHERE state='pending' AND next_attempt<=? ORDER BY created LIMIT 1", (now,)).fetchone()
            if not row: break
            c.execute('UPDATE meta_purchase_outbox SET next_attempt=?,attempts=attempts+1 WHERE order_id=?', (now+120,row['order_id']))
        event = json.loads(row['payload'])
        if now - event['event_time'] > 6*86400:
            with c: c.execute("UPDATE meta_purchase_outbox SET state='expired' WHERE order_id=?", (row['order_id'],))
            continue
        # Cancellations before dispatch of the conversion must not become purchases.
        current = c.execute('SELECT status FROM orders WHERE id=?', (row['order_id'],)).fetchone()
        if not current or current['status'] not in ('awaiting_booking','booked','packed','dispatched','delivered'):
            with c: c.execute("UPDATE meta_purchase_outbox SET state='cancelled' WHERE order_id=?", (row['order_id'],))
            continue
        try:
            if send:
                result = send(event, token)
            else:
                body = json.dumps(dict(data=[event], access_token=token)).encode()
                req = urllib.request.Request(f'https://graph.facebook.com/v25.0/{PIXEL_ID}/events',data=body,headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(req,timeout=10) as response: result = json.load(response)
            if result.get('events_received') != 1: raise ValueError('Event not accepted')
            with c: c.execute("UPDATE meta_purchase_outbox SET state='sent',sent=?,payload='{}' WHERE order_id=?",(now,row['order_id']))
            count += 1
        except Exception:
            # No response bodies, access tokens or user identifiers are logged.
            delay = min(3600, 30 * 2**min(row['attempts'],7))
            with c: c.execute('UPDATE meta_purchase_outbox SET next_attempt=? WHERE order_id=?',(now+delay,row['order_id']))
    with c:
        c.execute('DELETE FROM meta_attribution WHERE created<?',(now-30*86400,))
        c.execute("UPDATE meta_purchase_outbox SET payload='{}' WHERE state IN ('cancelled','expired')")
    return count


def start_worker(app):
    token = os.environ.get('META_CAPI_ACCESS_TOKEN','').strip()
    if app.config.get('TESTING'): return
    def run():
        while True:
            try:
                c = sqlite3.connect(app.config['DATABASE'], timeout=10)
                c.row_factory = sqlite3.Row
                try: deliver(c, token)
                finally: c.close()
            except Exception: pass
            time.sleep(30)
    threading.Thread(target=run, name='meta-purchase-outbox', daemon=True).start()
