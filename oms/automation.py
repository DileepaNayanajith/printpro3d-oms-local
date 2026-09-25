"""Durable, single-worker CCP preparation queue. Never silently retry a write."""
import re
import sqlite3
import time
from contextlib import contextmanager
from .fde_browser import SignInRequired


class Conflict(ValueError):
    pass


STATE_LABELS = {
    'pending': 'Add a waybill', 'queued': 'Waiting for browser',
    'preparing': 'Filling FDE form', 'prepared': 'Ready to review',
    'approved': 'Approved for one submission', 'submitting': 'Submitting once',
    'needs_review': 'Check FDE before continuing', 'blocked': 'Needs attention',
    'succeeded': 'Booking confirmed',
    'login_required': 'Sign into the worker browser',
}


def migrate(conn):
    """Additive migration: existing leads, PDFs and confirmed bookings survive."""
    columns = {r[1] for r in conn.execute('PRAGMA table_info(booking_jobs)')}
    for name, kind in {
        'assigned_waybill': 'TEXT', 'weight_kg': 'INTEGER',
        'message': "TEXT NOT NULL DEFAULT ''", 'updated_at': 'INTEGER',
    }.items():
        if name not in columns:
            conn.execute(f'ALTER TABLE booking_jobs ADD COLUMN {name} {kind}')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS assigned_waybill_unique ON booking_jobs(assigned_waybill)')
    lead_columns = {r[1] for r in conn.execute('PRAGMA table_info(leads)')}
    if 'intake_key' not in lead_columns:
        conn.execute('ALTER TABLE leads ADD COLUMN intake_key TEXT')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS intake_key_unique ON leads(intake_key)')
    conn.execute('''CREATE TABLE IF NOT EXISTS users (
      username TEXT PRIMARY KEY, password_hash TEXT NOT NULL,
      role TEXT NOT NULL CHECK(role IN ('admin','caller','packer')),
      active INTEGER NOT NULL DEFAULT 1
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS browser_worker (
        id INTEGER PRIMARY KEY CHECK(id=1), heartbeat INTEGER NOT NULL,
        submit_enabled INTEGER NOT NULL DEFAULT 0
    )''')
    conn.commit()


def normalize_waybill(value):
    value = value.strip().upper()
    if value.startswith('CCP'):
        value = value[3:]
    if not re.fullmatch(r'\d{4,20}', value):
        raise ValueError('Enter the CCP sticker digits, optionally prefixed with CCP.')
    return value  # Preserve leading zeros.


def tracking_key(value):
    try:
        return normalize_waybill(value)
    except ValueError:
        return value.strip().upper()


@contextmanager
def connection(path):
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        yield conn
    finally:
        conn.close()


def log(conn, order_id, actor, action):
    conn.execute('INSERT INTO events(order_id,actor,action) VALUES(?,?,?)', (order_id, actor, action))


def reserve(conn, order_id, number, weight, actor):
    number = normalize_waybill(number)
    try:
        weight = int(weight)
    except (ValueError, TypeError):
        raise ValueError('Choose the FDE weight band.')
    if not 1 <= weight <= 100:
        raise ValueError('FDE weight band must be 1–100 kg for this pilot.')
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        job = conn.execute('''SELECT j.*,o.status,l.weight_g FROM booking_jobs j
          JOIN orders o ON o.id=j.order_id JOIN leads l ON l.id=o.lead_id WHERE j.order_id=?''', (order_id,)).fetchone()
        if not job or job['status'] != 'awaiting_booking' or job['state'] != 'pending':
            raise Conflict('This order is already queued or booked. Refresh to see its status.')
        if weight * 1000 < job['weight_g']:
            raise ValueError('The selected FDE weight band is below the saved packed weight.')
        for booked in conn.execute('SELECT id,tracking FROM orders WHERE tracking IS NOT NULL'):
            if tracking_key(booked['tracking']) == number:
                raise Conflict('That waybill is already attached to a confirmed order.')
        try:
            conn.execute("""UPDATE booking_jobs SET assigned_waybill=?,weight_kg=?,state='queued',
              message='Waiting for the local FDE browser worker.',updated_at=? WHERE order_id=?""",
                         (number, weight, int(time.time()), order_id))
        except sqlite3.IntegrityError:
            raise Conflict('That waybill is reserved for another order.')
        log(conn, order_id, actor, 'CCP waybill reserved; form preparation queued')


def heartbeat(conn, enabled=False):
    with conn:
        conn.execute('INSERT OR REPLACE INTO browser_worker VALUES(1,?,?)', (int(time.time()), int(enabled)))


def worker_status(conn):
    row = conn.execute('SELECT * FROM browser_worker WHERE id=1').fetchone()
    online = bool(row and time.time() - row['heartbeat'] < 20)
    return {'online': online, 'submit_enabled': bool(online and row['submit_enabled'])}


def recover_interrupted(conn):
    # Called only after obtaining the process-wide worker lock.
    with conn:
        rows = conn.execute("SELECT order_id FROM booking_jobs WHERE state IN ('preparing','prepared','approved','submitting')").fetchall()
        for row in rows:
            conn.execute("""UPDATE booking_jobs SET state='needs_review',message=?,updated_at=? WHERE order_id=?""",
                         ('Browser stopped. Check FDE by waybill and order reference before retrying.', int(time.time()), row['order_id']))
            log(conn, row['order_id'], 'browser-worker', 'interrupted browser job requires reconciliation')


def claim(conn):
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute("SELECT order_id FROM booking_jobs WHERE state='queued' ORDER BY order_id LIMIT 1").fetchone()
        if not row:
            return None
        conn.execute("UPDATE booking_jobs SET state='preparing',attempts=attempts+1,updated_at=? WHERE order_id=?", (int(time.time()), row['order_id']))
        log(conn, row['order_id'], 'browser-worker', 'form preparation started')
        return row['order_id']


def transition(conn, order_id, expected, target, message, actor='browser-worker'):
    with conn:
        changed = conn.execute('UPDATE booking_jobs SET state=?,message=?,updated_at=? WHERE order_id=? AND state=?',
                               (target, message, int(time.time()), order_id, expected)).rowcount
        if not changed:
            raise Conflict('Job state changed. Browser action stopped.')
        log(conn, order_id, actor, message)


def snapshot(conn, order_id):
    row = conn.execute('''SELECT j.*,l.name,l.phone,l.address,l.city,l.product,l.quantity,l.cod_cents,l.weight_g
      FROM booking_jobs j JOIN orders o ON o.id=j.order_id JOIN leads l ON l.id=o.lead_id
      WHERE j.order_id=?''', (order_id,)).fetchone()
    return dict(row) if row else None


def prepare_one(conn, order_id, browser):
    job = snapshot(conn, order_id)
    try:
        browser.prepare(job)
    except SignInRequired:
        transition(conn, order_id, 'preparing', 'login_required',
                   'Sign into the open worker browser. Preparation resumes after login; nothing has been submitted.')
        return False
    except Exception:
        # Never persist raw browser errors: they can contain customer data or cookies.
        transition(conn, order_id, 'preparing', 'blocked',
                   'Could not verify the form. Check browser login, waybill, exact city and page layout.')
        return False
    transition(conn, order_id, 'preparing', 'prepared',
               'Form filled and checked. Review the dedicated FDE browser; booking is not yet confirmed.')
    return True


def submit_one(conn, order_id, browser, enabled=False):
    if not enabled:
        raise Conflict('Live submission is disabled for this worker.')
    job = snapshot(conn, order_id)
    if job['state'] != 'approved':
        raise Conflict('This order has no current submission approval.')
    try:
        browser.verify(job)
    except Exception:
        transition(conn, order_id, 'approved', 'needs_review', 'Form changed or session expired. No automated submit was attempted.')
        return
    # Commit BEFORE clicking. A crash/timeout cannot make this eligible for auto-retry.
    transition(conn, order_id, 'approved', 'submitting', 'One FDE submission attempt started')
    try:
        browser.submit()
    except Exception:
        message = 'Submission response uncertain. Search FDE before any retry; it may already be booked.'
    else:
        message = 'Submit clicked once. Confirm the FDE parcel record and tracking; automatic receipt detection is not commissioned.'
    transition(conn, order_id, 'submitting', 'needs_review', message)


def confirm_booking(conn, order_id, tracking, actor):
    if not re.fullmatch(r'[A-Za-z0-9-]{4,64}', tracking):
        raise ValueError('Enter the tracking number confirmed by FDE.')
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        job = conn.execute('SELECT * FROM booking_jobs WHERE order_id=?', (order_id,)).fetchone()
        if not job or job['state'] in ('preparing','approved','submitting'):
            raise Conflict('Wait for the browser action to finish before confirming.')
        key = tracking_key(tracking)
        if job['assigned_waybill'] and key != job['assigned_waybill']:
            raise Conflict('Tracking must match this order’s assigned CCP waybill.')
        if conn.execute('SELECT 1 FROM booking_jobs WHERE assigned_waybill=? AND order_id!=?', (key, order_id)).fetchone():
            raise Conflict('That waybill belongs to another order.')
        for row in conn.execute('SELECT id,tracking FROM orders WHERE tracking IS NOT NULL'):
            if tracking_key(row['tracking']) == key:
                raise Conflict('That tracking number is already confirmed.')
        changed = conn.execute("UPDATE orders SET tracking=?,status='booked' WHERE id=? AND status='awaiting_booking'", (tracking, order_id)).rowcount
        if not changed:
            raise Conflict('This order is already booked.')
        conn.execute("UPDATE booking_jobs SET state='succeeded',message='FDE record manually verified.',updated_at=? WHERE order_id=?", (int(time.time()), order_id))
        log(conn, order_id, actor, 'FDE parcel and tracking manually reconciled')
