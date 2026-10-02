"""Atomic, once-per-order physical courier handover records."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from . import sms, whatsapp


def migrate(c):
    if 'packing_only' not in {r[1] for r in c.execute('PRAGMA table_info(users)')}:
        c.execute('ALTER TABLE users ADD COLUMN packing_only INTEGER NOT NULL DEFAULT 0')
    c.execute('''CREATE TABLE IF NOT EXISTS parcel_handovers (
      order_id INTEGER PRIMARY KEY REFERENCES orders(id), actor TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    c.commit()


def record(c, barcode, actor, scan=True):
    match=re.fullmatch(r'PP3D-(\d{1,9})',str(barcode).strip().upper())
    if not match:raise ValueError('Scan the PP3D order barcode on the label, not the courier sticker.')
    oid=int(match[1])
    with c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('''SELECT o.id,o.status,o.tracking,l.name,l.cod_cents FROM orders o
          JOIN leads l ON l.id=o.lead_id WHERE o.id=?''',(oid,)).fetchone()
        if not row:raise ValueError('Order not found. Check the label.')
        result=dict(order_id=oid,reference='PP3D-%06d'%oid,name=row['name'],cod_cents=row['cod_cents'])
        if row['status']=='dispatched':
            if scan:return dict(result,duplicate=True)
            raise ValueError('This parcel is already dispatched.')
        if not scan and row['status']!='packed':raise ValueError('Pack this parcel before courier handover.')
        if row['status'] not in ('booked','packed') or not row['tracking']:
            raise ValueError('This parcel has no confirmed courier booking. Ask the owner to check it.')
        printed=c.execute('''SELECT 1 FROM orders o WHERE o.id=? AND
          (o.waybill IS NOT NULL OR EXISTS(SELECT 1 FROM print_jobs p WHERE p.order_id=o.id AND (p.marked_printed=1 OR p.state='spooled')))''',(oid,)).fetchone()
        if scan and not printed:raise ValueError('Print and attach this order label before courier handover.')
        c.execute('INSERT INTO parcel_handovers(order_id,actor) VALUES(?,?)',(oid,actor))
        c.execute("UPDATE orders SET status='dispatched' WHERE id=?",(oid,))
        sms.queue(c,oid,'dispatched')
        whatsapp.queue(c,oid)
        c.execute('INSERT INTO events(order_id,actor,action) VALUES(?,?,?)',(oid,actor,'Parcel scanned out of store and handed to courier'))
        return dict(result,duplicate=False)


def report(c,day=None):
    today=datetime.now(ZoneInfo('Asia/Colombo')).date().isoformat()
    day=day or today
    try:datetime.strptime(day,'%Y-%m-%d')
    except ValueError:raise ValueError('Choose a valid date.')
    rows=c.execute('''SELECT h.order_id,h.actor,datetime(h.created_at,'+330 minutes') AS local_time,
      l.name,l.cod_cents FROM parcel_handovers h JOIN orders o ON o.id=h.order_id
      JOIN leads l ON l.id=o.lead_id WHERE date(h.created_at,'+330 minutes')=?
      ORDER BY h.created_at DESC,h.order_id DESC''',(day,)).fetchall()
    return dict(day=day,today=today,count=len(rows),total=c.execute("SELECT COUNT(*) FROM orders WHERE status='dispatched'").fetchone()[0],rows=rows)
