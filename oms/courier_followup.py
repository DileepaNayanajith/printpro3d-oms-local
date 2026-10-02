"""Fresh courier exception callbacks, using the existing station message transport."""
import time
from .sms import mobile_number

EXCEPTIONS=('rescheduled','rearranged')


def migrate(c):
    c.execute('''CREATE TABLE IF NOT EXISTS courier_followups (
      order_id INTEGER PRIMARY KEY REFERENCES orders(id),
      message_id INTEGER UNIQUE REFERENCES whatsapp_confirmations(id),
      contacted_at INTEGER, contacted_by TEXT)''')
    c.commit()


def rows(c):
    return c.execute('''SELECT f.tracking,f.status,f.observed_at,o.id,l.name,l.phone,l.cod_cents,
      w.state AS message_state,cf.contacted_at FROM fde_observations f
      LEFT JOIN orders o ON replace(upper(o.tracking),'CCP','')=f.tracking
      LEFT JOIN leads l ON l.id=o.lead_id
      LEFT JOIN courier_followups cf ON cf.order_id=o.id
      LEFT JOIN whatsapp_confirmations w ON w.id=cf.message_id
      WHERE f.status IN ('rescheduled','rearranged') ORDER BY f.observed_at DESC,f.tracking''').fetchall()


def eligible(c,order_id,now):
    return c.execute('''SELECT 1 FROM orders o JOIN fde_observations f
      ON replace(upper(o.tracking),'CCP','')=f.tracking
      JOIN fde_report_totals t ON t.status=f.status
      WHERE o.id=? AND f.status IN ('rescheduled','rearranged') AND f.observed_at>=?
      AND t.observed_at=f.observed_at AND t.sampled=t.total''',(order_id,now-900)).fetchone() is not None


def reconcile(c):
    now=int(time.time())
    for r in c.execute('''SELECT cf.order_id,w.id FROM courier_followups cf JOIN whatsapp_confirmations w
      ON w.id=cf.message_id WHERE w.state IN ('queued','preparing')''').fetchall():
        if not eligible(c,r['order_id'],now):
            c.execute("UPDATE whatsapp_confirmations SET state='cancelled',detail='Courier exception no longer confirmed by a fresh complete report.' WHERE id=?",(r['id'],))


def queue_fresh(c):
    now=int(time.time())
    reconcile(c)
    for r in rows(c):
        if not r['id'] or not eligible(c,r['id'],now):continue
        if c.execute('SELECT 1 FROM courier_followups WHERE order_id=? AND message_id IS NOT NULL',(r['id'],)).fetchone():continue
        try:phone=mobile_number(r['phone'])
        except ValueError:continue
        body=(f"Hi {r['name']},\n\nFDE currently shows your PRINTPRO3D parcel as {r['status']}. "
              "Please reply with a convenient time to contact you so we can help with the next delivery attempt. "
              "If you have already received it, please let us know.\n\n"
              f"Order: PP3D-{r['id']:06d}\nTracking ID: {r['tracking']}\n"
              "Track: https://www.fdedomestic.com\n\nThank you!\nPRINTPRO3D")
        mid=c.execute('''INSERT INTO whatsapp_confirmations
          (name,phone,body,request_key,created_at,updated_at,include_photo)
          VALUES(?,?,?,?,?,?,0)''',(r['name'],phone,body,f"courier-followup-{r['id']}",now,now)).lastrowid
        c.execute('''INSERT INTO courier_followups(order_id,message_id) VALUES(?,?)
          ON CONFLICT(order_id) DO UPDATE SET message_id=excluded.message_id''',(r['id'],mid))
