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
    if 'include_photo' not in {r[1] for r in conn.execute('PRAGMA table_info(whatsapp_confirmations)')}:
        conn.execute('ALTER TABLE whatsapp_confirmations ADD COLUMN include_photo INTEGER NOT NULL DEFAULT 0')
    conn.commit()


def message(name):
    return (f'Hi {name}, ආයුබෝවන්! வணக்கம்!\n\n'
            '*PRINTPRO3D — Display Racks*\n\n'
            '*Hot Wheels 1:64 — 10 slots*\n'
            '• 1 or 2 racks: *Rs. 1,850 each*\n'
            '• 3 or more racks: *Rs. 1,750 each*\n'
            'https://printpro3d.lk/products/8\n\n'
            '*1:32 Model Car Rack — 4 slots*\n'
            'https://printpro3d.lk/products/1024\n\n'
            '*සිංහල*\n'
            'ඔබේ වාහන එකතුව ලස්සනට තබන්න! ඉහත links වලින් rack දෙකේම විස්තර බලලා website එකෙන්ම order කරන්න පුළුවන්. '
            'WhatsApp හරහා order කරන්න නම් *YES* කියලා rack වර්ගය, පාට සහ ප්‍රමාණය එවන්න.\n\n'
            '*English*\n'
            'Display your collection in style! View both racks using the links above and order directly on our website. '
            'To order through WhatsApp, reply *YES* with the rack type, colour and quantity.\n\n'
            '*தமிழ்*\n'
            'உங்கள் கார் சேகரிப்பை அழகாகக் காட்சிப்படுத்துங்கள்! மேலுள்ள இணைப்புகளில் இரண்டு ரேக்குகளின் விவரங்களையும் பார்த்து, எங்கள் இணையதளத்திலேயே ஆர்டர் செய்யலாம். '
            'WhatsApp மூலம் ஆர்டர் செய்ய, *YES* எனப் பதிலளித்து ரேக் வகை, நிறம் மற்றும் எண்ணிக்கையை அனுப்புங்கள்.\n\n'
            'Thank you! ස්තූතියි! நன்றி!\n*PRINTPRO3D*')


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
          (name,phone,body,request_key,created_at,updated_at,include_photo) VALUES(?,?,?,?,?,?,1)''',
          (name,phone,message(name),key,now,now))
        return cursor.lastrowid
