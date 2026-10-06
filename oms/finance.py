"""Estimated operating result; courier observations are not settlement receipts."""
import re
import secrets
from datetime import datetime
from decimal import Decimal,InvalidOperation
from zoneinfo import ZoneInfo


def today():return datetime.now(ZoneInfo('Asia/Colombo')).date().isoformat()

def date(value):
    try:return datetime.strptime(value,'%Y-%m-%d').date().isoformat()
    except (ValueError,TypeError):raise ValueError('Choose a valid date.')

def cents(value):
    try:
        n=Decimal(str(value))
        if not n.is_finite() or n<0 or n>10000000 or n!=n.quantize(Decimal('.01')):raise ValueError()
        return int(n*100)
    except (InvalidOperation,ValueError):raise ValueError('Enter a valid amount with up to two decimal places.')

def migrate(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS finance_expenses(id INTEGER PRIMARY KEY,spent_on TEXT NOT NULL,
      category TEXT NOT NULL,amount_cents INTEGER NOT NULL,note TEXT NOT NULL,actor TEXT NOT NULL,
      request_key TEXT NOT NULL UNIQUE,voided INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS finance_deliveries(order_id INTEGER PRIMARY KEY REFERENCES orders(id),
      delivered_on TEXT NOT NULL,observed_at INTEGER NOT NULL,date_source TEXT NOT NULL DEFAULT 'FDE first observed');
    CREATE TABLE IF NOT EXISTS finance_shipping(order_id INTEGER PRIMARY KEY REFERENCES orders(id),
      shipped_on TEXT NOT NULL,cost_cents INTEGER NOT NULL,date_source TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS parcel_returns(order_id INTEGER PRIMARY KEY REFERENCES orders(id),
      returned_on TEXT NOT NULL,actor TEXT NOT NULL,inbound_cents INTEGER NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    ''')
    capture(c)
    c.commit()

def outbound(c,oid,on=None,source='Packing handover'):
    c.execute('INSERT OR IGNORE INTO finance_shipping VALUES(?,?,40000,?)',(oid,on or today(),source))

def capture(c):
    # Existing snapshot dates are retained; never fabricate an actual FDE delivery date.
    for r in c.execute('''SELECT o.id,f.status,f.observed_at FROM orders o JOIN leads l ON l.id=o.lead_id
      JOIN fde_observations f ON f.tracking=replace(upper(o.tracking),'CCP','')
      WHERE lower(l.product) NOT LIKE '%test only%' AND f.status IN
      ('pickup','processing','dispatched','delivered','rearranged','rescheduled','return_pending','return_complete','transferred','hold')''').fetchall():
        on=datetime.fromtimestamp(r['observed_at'],ZoneInfo('Asia/Colombo')).date().isoformat()
        outbound(c,r['id'],on,'FDE first observed; date estimated')
        if r['status']=='delivered' and not c.execute('SELECT 1 FROM parcel_returns WHERE order_id=?',(r['id'],)).fetchone():
            c.execute('INSERT OR IGNORE INTO finance_deliveries(order_id,delivered_on,observed_at) VALUES(?,?,?)',(r['id'],on,r['observed_at']))
    for r in c.execute("SELECT order_id,date(created_at,'+330 minutes') AS day FROM parcel_handovers").fetchall():
        outbound(c,r['order_id'],r['day'])
        c.execute("UPDATE finance_shipping SET shipped_on=?,date_source='Packing handover' WHERE order_id=? AND date_source LIKE 'FDE%'",(r['day'],r['order_id']))

def receive_return(c,code,actor):
    code=str(code).strip().upper()
    with c:
        c.execute('BEGIN IMMEDIATE')
        if re.fullmatch(r'PP3D-\d{1,9}',code):
            row=c.execute('SELECT * FROM orders WHERE id=?',(int(code[5:]),)).fetchone()
        elif re.fullmatch(r'(?:CCP)?\d{4,20}',code):
            row=c.execute("SELECT * FROM orders WHERE replace(upper(tracking),'CCP','')=?",(code.removeprefix('CCP') if hasattr(code,'removeprefix') else code.replace('CCP',''),)).fetchone()
        else:raise ValueError('Scan a PP3D order barcode or the FDE tracking sticker.')
        if not row or not row['tracking'] or row['status'] not in ('booked','packed','dispatched'):
            raise ValueError('No booked parcel matches this barcode. Ask the owner to check it.')
        oid=row['id'];existing=c.execute('SELECT 1 FROM parcel_returns WHERE order_id=?',(oid,)).fetchone()
        if not existing:
            outbound(c,oid,source='Return received; outgoing date estimated')
            c.execute('INSERT INTO parcel_returns(order_id,returned_on,actor,inbound_cents) VALUES(?,?,?,40000)',(oid,today(),actor))
            c.execute("UPDATE whatsapp_outbox SET state='cancelled',detail='Parcel returned before dispatch notification was sent.' WHERE order_id=? AND state IN ('queued','awaiting_handover','blocked')",(oid,))
            c.execute('INSERT INTO events(order_id,actor,action) VALUES(?,?,?)',(oid,actor,'Returned parcel received; return courier cost recorded once'))
        customer=c.execute('SELECT name,cod_cents FROM leads WHERE id=?',(row['lead_id'],)).fetchone()
        return dict(reference=f'PP3D-{oid:06d}',name=customer['name'],cod_cents=customer['cod_cents'],duplicate=bool(existing),
          today_count=c.execute('SELECT count(*) FROM parcel_returns WHERE returned_on=?',(today(),)).fetchone()[0],
          total_count=c.execute('SELECT count(*) FROM parcel_returns').fetchone()[0])

def overview(c,month=None):
    month=month or today()[:7]
    if month!='all' and (not re.fullmatch(r'\d{4}-\d{2}',month) or not 1<=int(month[5:])<=12):raise ValueError('Choose a valid month.')
    matches=lambda d:month=='all' or d.startswith(month)
    deliveries=[];revenue=0;reversed_value=0;unverified=0
    for r in c.execute('''SELECT d.*,l.name,l.cod_cents,o.tracking,w.payment,w.payment_verified,w.total_cents,
      pr.returned_on FROM finance_deliveries d JOIN orders o ON o.id=d.order_id JOIN leads l ON l.id=o.lead_id
      LEFT JOIN website_orders w ON w.lead_id=l.id LEFT JOIN parcel_returns pr ON pr.order_id=o.id ORDER BY delivered_on DESC'''):
        amount=(r['total_cents'] if r['payment_verified'] else 0) if r['payment']=='bank' else r['cod_cents']
        if matches(r['delivered_on']):
            deliveries.append(dict(r,amount_cents=amount));revenue+=amount
            unverified+=int(r['payment']=='bank' and not r['payment_verified'])
        if r['returned_on'] and matches(r['returned_on']):reversed_value+=amount
    expenses=[dict(r) for r in c.execute('SELECT * FROM finance_expenses WHERE voided=0 ORDER BY spent_on DESC,id DESC') if matches(r['spent_on'])]
    shipping=[dict(r) for r in c.execute('SELECT * FROM finance_shipping') if matches(r['shipped_on'])]
    returns=[dict(r) for r in c.execute('''SELECT pr.*,l.name,o.tracking,s.cost_cents AS outbound_cents FROM parcel_returns pr
      JOIN orders o ON o.id=pr.order_id JOIN leads l ON l.id=o.lead_id LEFT JOIN finance_shipping s ON s.order_id=o.id
      ORDER BY returned_on DESC,pr.order_id DESC''') if matches(r['returned_on'])]
    outbound_cost=sum(r['cost_cents'] for r in shipping);inbound=sum(r['inbound_cents'] for r in returns);spend=sum(r['amount_cents'] for r in expenses)
    return dict(month=month,today=today(),deliveries=deliveries,revenue=revenue,reversed_value=reversed_value,
      outbound=outbound_cost,inbound=inbound,expenses_total=spend,expenses=expenses,returns=returns,
      profit=revenue-reversed_value-outbound_cost-inbound-spend,unverified=unverified,
      request_key=secrets.token_hex(16),shipping=shipping,
      unknown=c.execute("SELECT count(*) FROM orders o LEFT JOIN fde_observations f ON f.tracking=replace(upper(o.tracking),'CCP','') WHERE o.tracking IS NOT NULL AND f.tracking IS NULL").fetchone()[0],
      delivered_report=c.execute("SELECT * FROM fde_report_totals WHERE status='delivered'").fetchone())
