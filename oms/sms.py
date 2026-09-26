"""Transactional customer message outbox. Provider setup is deliberately separate."""
import re


def migrate(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS sms_outbox (
      id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
      kind TEXT NOT NULL CHECK(kind IN ('processing','dispatched')),
      phone TEXT NOT NULL, body TEXT NOT NULL,
      state TEXT NOT NULL DEFAULT 'awaiting_setup',
      provider_id TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(order_id,kind))''')
    conn.commit()


def mobile_number(value):
    value=re.sub(r'[\s()-]','',value)
    if value.startswith('+'):value=value[1:]
    if value.startswith('0'):value='94'+value[1:]
    if not re.fullmatch(r'947\d{8}',value):
        raise ValueError('Customer needs a valid Sri Lankan mobile number for SMS.')
    return value


def queue(conn,order_id,kind):
    row=conn.execute('SELECT l.phone,o.tracking,o.status FROM orders o JOIN leads l ON l.id=o.lead_id WHERE o.id=?',(order_id,)).fetchone()
    ref=f'PP3D-{order_id:06d}'
    if kind=='processing':
        body=f'PRINTPRO3D: Your order {ref} is confirmed and processing. We will send your tracking number when it is dispatched. Thank you!'
    elif kind=='dispatched' and row['status']=='dispatched' and row['tracking']:
        body=f'PRINTPRO3D: Order {ref} dispatched via FDE. Tracking ID: {row["tracking"]}.'
    else:raise ValueError('Dispatch SMS requires an actual courier handover and tracking number.')
    try:phone=mobile_number(row['phone']);state='awaiting_setup'
    except ValueError:phone=row['phone'];state='invalid_phone'
    conn.execute('INSERT OR IGNORE INTO sms_outbox(order_id,kind,phone,body,state) VALUES(?,?,?,?,?)',(order_id,kind,phone,body,state))


def settings(root):
    import json
    from pathlib import Path
    try:
        return json.loads((Path(root)/'textlk.json').read_text())
    except (OSError,ValueError):
        return {}


def send_textlk(config, row):
    """One documented HTTPS request. Never resend after a timeout."""
    import json
    import urllib.request
    import urllib.error
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    payload={'recipient':row['phone'],'sender_id':config['sender_id'],'type':'plain','message':row['body']}
    req=urllib.request.Request('https://app.text.lk/api/v3/sms/send',data=json.dumps(payload).encode(),method='POST',headers={
        'Authorization':'Bearer '+config['token'],'Content-Type':'application/json','Accept':'application/json'})
    with urllib.request.build_opener(NoRedirect).open(req,timeout=20) as response:
        result=json.load(response)
    if result.get('status')=='error':return 'rejected',None
    data=result.get('data')
    if result.get('status')!='success' or not isinstance(data,dict):return 'needs_review',None
    if not data.get('uid') or str(data.get('to'))!=row['phone']:return 'needs_review',None
    status='delivered' if str(data.get('status','')).lower()=='delivered' else 'accepted'
    return status,str(data['uid'])


def send_one(conn,root,sender=send_textlk):
    config=settings(root)
    if not config.get('enabled') or not config.get('token') or not config.get('sender_id'):
        return False
    if config['sender_id'].lower()=='textlkdemo':return False
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute("""SELECT s.*,o.status AS order_status FROM sms_outbox s JOIN orders o ON o.id=s.order_id
          WHERE s.state='awaiting_setup' AND s.id>=? ORDER BY s.id LIMIT 1""",(config.get('first_message_id',2147483647),)).fetchone()
        if not row:return False
        if (row['kind']=='processing' and row['order_status']=='dispatched') or conn.execute("SELECT julianday('now')-julianday(?)>1",(row['created_at'],)).fetchone()[0]:
            conn.execute("UPDATE sms_outbox SET state='stale' WHERE id=?",(row['id'],));return True
        conn.execute("UPDATE sms_outbox SET state='sending' WHERE id=?",(row['id'],))
    try:
        state,uid=sender(config,dict(row))
        if state not in ('delivered','accepted','rejected','needs_review'):state,uid='needs_review',None
    except Exception:
        # Do not store exception text: it may include tokens, phone numbers or message bodies.
        state,uid='needs_review',None
    with conn:conn.execute('UPDATE sms_outbox SET state=?,provider_id=? WHERE id=?',(state,uid,row['id']))
    return True
