"""Durable tracking notifications, created only after physical courier handover."""
import time
from .sms import mobile_number


def migrate(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS whatsapp_outbox (
      id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL UNIQUE REFERENCES orders(id),
      phone TEXT NOT NULL, body TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued',
      detail TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS whatsapp_worker (
      id INTEGER PRIMARY KEY CHECK(id=1), heartbeat INTEGER NOT NULL,
      status TEXT NOT NULL
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS whatsapp_booking_events (
      order_id INTEGER PRIMARY KEY REFERENCES orders(id)
    )''')
    # Preserve the legacy event table for existing workers, but change its trigger.
    old=conn.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='whatsapp_booking_confirmed'").fetchone()
    if old:
        conn.execute('DROP TRIGGER whatsapp_booking_confirmed')
        conn.execute('DELETE FROM whatsapp_booking_events')
    conn.execute("""CREATE TRIGGER IF NOT EXISTS whatsapp_handover_confirmed
      AFTER UPDATE OF status ON orders
      WHEN NEW.status='dispatched' AND OLD.status!='dispatched'
      BEGIN INSERT OR IGNORE INTO whatsapp_booking_events(order_id) VALUES(NEW.id); END""")
    hold_unhanded(conn)
    conn.commit()


def ingest(conn):
    # Capture dispatch events without backfilling historical orders.
    with conn:
        for row in conn.execute('SELECT order_id FROM whatsapp_booking_events').fetchall():
            queue(conn, row[0])
            conn.execute('DELETE FROM whatsapp_booking_events WHERE order_id=?', (row[0],))


def tracking_message(name, order_id, tracking, dispatched=False):
    return (f'Hi {name}, 👋\n\n'
            f'Thank you for choosing *PRINTPRO3D*!\n'
            f"{'Your parcel has been handed to FDE Domestic for delivery.' if dispatched else 'Your order is being prepared for courier handover and has been registered with FDE Domestic.'}\n\n"
            f'📦 *Order:* PP3D-{order_id:06d}\n'
            f'🚚 *Tracking ID:* {tracking}\n\n'
            'Track your parcel at:\nhttps://www.fdedomestic.com\n'
            'Enter the tracking ID above. Tracking updates may appear after the courier scans your parcel.\n\n'
            'Thank you!\n*PRINTPRO3D*')


def queue(conn, order_id):
    row = conn.execute('''SELECT o.tracking,l.name,l.phone FROM orders o
      JOIN leads l ON l.id=o.lead_id
      WHERE o.id=? AND o.status='dispatched' AND o.tracking IS NOT NULL AND NOT EXISTS(SELECT 1 FROM parcel_returns WHERE order_id=o.id)''', (order_id,)).fetchone()
    if not row:
        return
    tracking, name, raw_phone = row
    try:
        phone, state = mobile_number(raw_phone), 'queued'
    except ValueError:
        phone, state = '', 'invalid_phone'
    now = int(time.time())
    conn.execute('''INSERT OR IGNORE INTO whatsapp_outbox
      (order_id,phone,body,state,created_at,updated_at) VALUES(?,?,?,?,?,?)
      ON CONFLICT(order_id) DO UPDATE SET phone=excluded.phone,body=excluded.body,state=excluded.state,
      detail='',created_at=excluded.created_at,updated_at=excluded.updated_at
      WHERE whatsapp_outbox.state='awaiting_handover' ''',
      (order_id, phone, tracking_message(name, order_id, tracking,dispatched=True), state, now, now))


def hold_unhanded(conn):
    conn.execute("""UPDATE whatsapp_outbox SET state='awaiting_handover',
      detail='Waiting for packing to scan this parcel OUT.'
      WHERE state IN ('queued','blocked','stale') AND order_id IN
      (SELECT id FROM orders WHERE status!='dispatched')""")


def recover(conn):
    with conn:
        conn.execute("UPDATE whatsapp_confirmations SET state='needs_review',detail='Worker stopped during send. Check WhatsApp before resending.' WHERE state='sending'")
        conn.execute("UPDATE whatsapp_outbox SET state='needs_review',detail='Worker stopped during send. Check WhatsApp before any manual resend.' WHERE state='sending'")


def send_one(conn, browser, table='whatsapp_outbox'):
    if table not in ('whatsapp_outbox','whatsapp_confirmations'):
        raise ValueError('Unknown message queue.')
    """Preparation is retryable; once sending is committed, never retry automatically."""
    if table=='whatsapp_outbox':
        with conn:hold_unhanded(conn)
    row = conn.execute(f"SELECT * FROM {table} WHERE state='queued' ORDER BY id LIMIT 1").fetchone()
    if not row:
        return False
    if time.time() - row['created_at'] > 86400:
        with conn:
            conn.execute(f"UPDATE {table} SET state='stale',detail='Older than 24 hours; send manually if still relevant.' WHERE id=?", (row['id'],))
        return True
    # Prepare verifies the recipient and complete draft without sending.
    photo = table=='whatsapp_confirmations' and row['include_photo']
    if photo:
        from pathlib import Path
        browser.prepare_photo(row['phone'], row['body'], Path(__file__).parent/'static/products/hot-wheels-rack.png')
    else:
        browser.prepare(row['phone'], row['body'])
    with conn:
        claimed = conn.execute(f"UPDATE {table} SET state='sending',updated_at=? WHERE id=? AND state='queued'", (int(time.time()), row['id'])).rowcount
    if not claimed:
        return False
    try:
        if photo:
            browser.send_photo(row['phone'], row['body'])
        else:
            browser.send(row['phone'], row['body'])
        state, detail = 'sent', 'WhatsApp displayed a sent check mark. Delivery/read not confirmed.'
    except Exception:
        state, detail = 'needs_review', 'Send result uncertain. Check the customer chat; automatic retry is disabled.'
    with conn:
        conn.execute(f'UPDATE {table} SET state=?,detail=?,updated_at=? WHERE id=?', (state, detail, int(time.time()), row['id']))
    return True
