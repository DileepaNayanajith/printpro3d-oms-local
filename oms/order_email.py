"""Website order status mail. Durable event IDs; ambiguous sends are not replayed."""
import os,re,time,sqlite3,smtplib,ssl,threading
from email.message import EmailMessage
from email.utils import formatdate
from flask import render_template,session,abort

STATUSES={'received':'Order received','awaiting_booking':'Order confirmed','booked':'Courier booking confirmed','packed':'Order packed','dispatched':'Parcel handed to courier'}
def address(value):
 value=str(value or '').strip()
 return value if len(value)<=254 and re.fullmatch(r'[^\s@<>\r\n]+@[^\s@<>\r\n]+\.[^\s@<>\r\n]+',value) else ''
def from_data(data):
 value=address(data.get('email'))
 if value:return value
 match=re.search(r'(?:^|\n)\s*(?:customer\s+)?email\s*:\s*([^\s]+)',str(data.get('notes','')),re.I)
 return address(match[1]) if match else ''
def migrate(c):
 c.executescript('''
 CREATE TABLE IF NOT EXISTS order_email_contacts(lead_id INTEGER PRIMARY KEY REFERENCES leads(id),email TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS order_email_outbox(id INTEGER PRIMARY KEY,lead_id INTEGER NOT NULL,order_id INTEGER,status TEXT NOT NULL,tracking TEXT,email TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'queued',detail TEXT NOT NULL DEFAULT '',created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),UNIQUE(lead_id,status));
 CREATE TRIGGER IF NOT EXISTS email_order_insert AFTER INSERT ON orders
 BEGIN INSERT OR IGNORE INTO order_email_outbox(lead_id,order_id,status,tracking,email) SELECT NEW.lead_id,NEW.id,NEW.status,NEW.tracking,email FROM order_email_contacts WHERE lead_id=NEW.lead_id; END;
 CREATE TRIGGER IF NOT EXISTS email_order_update AFTER UPDATE OF status ON orders WHEN OLD.status!=NEW.status
 BEGIN INSERT OR IGNORE INTO order_email_outbox(lead_id,order_id,status,tracking,email) SELECT NEW.lead_id,NEW.id,NEW.status,NEW.tracking,email FROM order_email_contacts WHERE lead_id=NEW.lead_id AND NEW.status IN ('awaiting_booking','booked','packed','dispatched'); END;
 ''')
 # Retain explicit checkout email for future updates only; no historical mailing.
 for row in c.execute('SELECT w.lead_id,l.notes FROM website_orders w JOIN leads l ON l.id=w.lead_id').fetchall():
  email=from_data({'notes':row['notes']})
  if email:c.execute('INSERT OR IGNORE INTO order_email_contacts VALUES(?,?)',(row['lead_id'],email))
 c.commit()
def remember(c,lead_id,data):
 email=from_data(data)
 if email:
  c.execute('INSERT OR IGNORE INTO order_email_contacts VALUES(?,?)',(lead_id,email))
  c.execute("INSERT OR IGNORE INTO order_email_outbox(lead_id,status,email) VALUES(?,'received',?)",(lead_id,email))
def configured():
 return all(os.environ.get(k) for k in ('OMS_SMTP_HOST','OMS_SMTP_USER','OMS_SMTP_PASSWORD','OMS_EMAIL_FROM')) and bool(address(os.environ.get('OMS_EMAIL_FROM')))
def message(row):
 m=EmailMessage();m['From']=os.environ['OMS_EMAIL_FROM'];m['To']=row['email'];ref=('PP3D-%06d'%row['order_id']) if row['order_id'] else ('WEB-%06d'%row['lead_id'])
 m['Subject']=f"PRINTPRO3D · {STATUSES[row['status']]} · {ref}"
 m['Message-ID']=f"<oms-status-{row['id']}@{os.environ['OMS_EMAIL_FROM'].split('@')[-1]}>";m['Date']=formatdate(localtime=False)
 body=f"Hi {row['name']},\n\n{STATUSES[row['status']]}.\nOrder: {ref}\n"
 if row['status']=='booked':body+='Your parcel is registered with FDE and is being prepared for handover.\n'
 if row['tracking']:body+=f"Tracking ID: {row['tracking']}\nTrack at https://www.fdedomestic.com\n"
 body+='\nThank you for choosing PRINTPRO3D!'
 m.set_content(body);return m

def send_one(c,transport=None):
 if not configured():return False
 with c:
  c.execute('BEGIN IMMEDIATE')
  c.execute("UPDATE order_email_outbox SET state='stale',detail='Older than 24 hours; not sent automatically.' WHERE state='queued' AND created_at<?",(int(time.time())-86400,))
  row=c.execute("SELECT e.*,l.name FROM order_email_outbox e JOIN leads l ON l.id=e.lead_id WHERE e.state='queued' ORDER BY e.id LIMIT 1").fetchone()
  if not row:return False
  c.execute("UPDATE order_email_outbox SET state='sending' WHERE id=?",(row['id'],))
 try:
  mail=message(row)
  if transport:transport(mail)
  else:
   host=os.environ['OMS_SMTP_HOST'];port=int(os.environ.get('OMS_SMTP_PORT','587'));context=ssl.create_default_context()
   with smtplib.SMTP(host,port,timeout=25) as smtp:
    smtp.ehlo();smtp.starttls(context=context);smtp.ehlo();smtp.login(os.environ['OMS_SMTP_USER'],os.environ['OMS_SMTP_PASSWORD']);smtp.send_message(mail)
  state,detail='sent','SMTP server accepted message; delivery is not confirmed.'
 except Exception:state,detail='needs_review','Mail attempt failed or result uncertain. Review before resending.'
 with c:c.execute('UPDATE order_email_outbox SET state=?,detail=? WHERE id=?',(state,detail,row['id']))
 return True

def start(app):
 if not configured():return
 def work():
  while True:
   try:
    with sqlite3.connect(app.config['DATABASE'],timeout=10) as c:
     c.row_factory=sqlite3.Row;send_one(c)
   except Exception:app.logger.warning('Order email worker needs attention')
   time.sleep(5)
 threading.Thread(target=work,daemon=True,name='order-email').start()
def register(app,db):
 with app.app_context():migrate(db())
 @app.get('/email-updates')
 def email_updates():
  if session.get('role')!='admin':abort(403)
  return render_template('email_updates.html',configured=configured(),rows=db().execute('SELECT * FROM order_email_outbox ORDER BY id DESC LIMIT 100').fetchall())
