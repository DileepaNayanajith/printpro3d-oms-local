"""Caller-requested product details, independent from courier bookings."""
import re
import time
from .sms import mobile_number


def migrate(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS whatsapp_confirmations (
      id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL,
      body TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued',
      detail TEXT NOT NULL DEFAULT '', request_key TEXT NOT NULL UNIQUE,
      created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
      reply_status TEXT NOT NULL DEFAULT 'awaiting_reply'
    )''')
    conn.commit()


def message(name):
    return (f'Hi {name},\n\n'
            'Thank you for your interest in *PRINTPRO3D Hot Wheels racks*!\n\n'
            '*10-slot display rack*\n'
            '• 1 or 2 racks: *Rs. 1,850 each*\n'
            '• 3 or more racks: *Rs. 1,750 each*\n\n'
            'The racks connect together, so you can keep adding more as your collection grows.\n\n'
            'We would like to confirm your order.\n'
            'Please reply *YES* to confirm, and tell us how many racks you would like.\n\n'
            'Thank you!\n*PRINTPRO3D*')


def queue(conn, name, phone, key):
    name=' '.join(name.split())
    if not name or len(name)>100:
        raise ValueError('Enter a customer name of 1–100 characters.')
    phone=mobile_number(phone)
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,100}',key):
        raise ValueError('Form expired. Refresh and try again.')
    now=int(time.time())
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        existing=conn.execute('SELECT id FROM whatsapp_confirmations WHERE request_key=?',(key,)).fetchone()
        if existing:return existing[0]
        existing=conn.execute("SELECT id FROM whatsapp_confirmations WHERE phone=? AND (state IN ('queued','sending','needs_review','blocked') OR created_at>?) ORDER BY id DESC LIMIT 1",(phone,now-86400)).fetchone()
        if existing:
            raise ValueError('This number already has a recent or pending message. Check the list before sending again.')
        cursor=conn.execute('''INSERT INTO whatsapp_confirmations
          (name,phone,body,request_key,created_at,updated_at) VALUES(?,?,?,?,?,?)''',
          (name,phone,message(name),key,now,now))
        return cursor.lastrowid
