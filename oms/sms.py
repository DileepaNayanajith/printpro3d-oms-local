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
        body=f'PRINTPRO3D: Your order {ref} has been handed to FDE courier. Tracking ID: {row["tracking"]}. Thank you!'
    else:raise ValueError('Dispatch SMS requires an actual courier handover and tracking number.')
    try:phone=mobile_number(row['phone']);state='awaiting_setup'
    except ValueError:phone=row['phone'];state='invalid_phone'
    conn.execute('INSERT OR IGNORE INTO sms_outbox(order_id,kind,phone,body,state) VALUES(?,?,?,?,?)',(order_id,kind,phone,body,state))
