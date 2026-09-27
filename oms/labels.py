"""A5 parcel label on the left half of landscape A4; durable local print queue."""
import json
import io
import re
import subprocess
import uuid
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.graphics.barcode import code128
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle


def migrate(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS print_jobs (
      order_id INTEGER PRIMARY KEY REFERENCES orders(id),
      state TEXT NOT NULL DEFAULT 'queued', spool_id TEXT, message TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    if 'batch_id' not in {r[1] for r in conn.execute('PRAGMA table_info(print_jobs)')}:
        conn.execute('ALTER TABLE print_jobs ADD COLUMN batch_id TEXT')
        conn.execute("UPDATE print_jobs SET state='ready',message='Ready for batch printing' WHERE state='queued'")
    if 'marked_printed' not in {r[1] for r in conn.execute('PRAGMA table_info(print_jobs)')}:
        conn.execute('ALTER TABLE print_jobs ADD COLUMN marked_printed INTEGER NOT NULL DEFAULT 0')
        conn.execute("UPDATE print_jobs SET marked_printed=1 WHERE batch_id IS NOT NULL OR state='spooled'")
    conn.commit()


def enqueue(conn, order_id):
    conn.execute("INSERT OR IGNORE INTO print_jobs(order_id,state,message) VALUES(?,'ready','Ready for batch printing')",(order_id,))


def draw_label(c, order, sender):
    left=10*mm; width=128*mm
    c.setLineWidth(1.4)
    c.rect(6*mm,7*mm,136*mm,196*mm)
    def text(value,x,y,size=11,bold=False):
        c.setFont('Helvetica-Bold' if bold else 'Helvetica',size)
        c.drawString(x,y,str(value))
    def block(value,x,y,w,h,size=11):
        # Fail visibly rather than silently replacing unsupported glyphs.
        str(value).encode('cp1252')
        style=ParagraphStyle('label',fontName='Helvetica',fontSize=size,leading=size*1.3)
        p=Paragraph(escape(str(value)).replace('\n','<br/>'),style)
        _,used=p.wrap(w,h)
        if used>h: raise ValueError('Text is too long for the label; shorten the address or item description.')
        p.drawOn(c,x,y-used)
    c.rect(left,180*mm,width,17*mm,fill=1)
    c.setFillColorRGB(1,1,1)
    text('PRINTPRO3D',left+3*mm,186*mm,21,True)
    text('PARCEL',110*mm,190*mm,9,True)
    text('WAYBILL',110*mm,185*mm,9,True)
    c.setFillColorRGB(0,0,0)
    c.rect(left,85*mm,width,89*mm)
    c.line(74*mm,85*mm,74*mm,174*mm)
    for x,title in [(13*mm,'FROM / SENDER'),(77*mm,'TO / RECIPIENT')]:
        c.rect(x,163*mm,58*mm,7*mm,fill=1)
        c.setFillColorRGB(1,1,1);text(title,x+2*mm,165*mm,10,True);c.setFillColorRGB(0,0,0)
    block(sender['name']+'\n'+sender['address']+'\n\nTEL: '+sender['phone'],13*mm,157*mm,57*mm,66*mm,11)
    block(order['name']+'\n\n'+order['address']+'\n'+order['city']+'\n\nTEL: '+order['phone'],77*mm,157*mm,57*mm,66*mm,11)
    c.rect(left,62*mm,width,18*mm)
    c.rect(left,62*mm,28*mm,18*mm,fill=1)
    c.setFillColorRGB(1,1,1);text('COD',left+5*mm,68*mm,18,True);c.setFillColorRGB(0,0,0)
    text('Rs. '+format(order['cod_cents']/100,'.2f'),43*mm,68*mm,19,True)
    block(str(order['quantity'])+' x '+order['product'],left,59*mm,width,9*mm,9)
    c.rect(left,28*mm,width,21*mm)
    text('COURIER TRACKING STICKER',left+3*mm,44*mm,9)
    ref='PP3D-%06d'%order['order_id']
    barcode=code128.Code128(ref,barHeight=10*mm,barWidth=0.32*mm,humanReadable=True)
    barcode.drawOn(c,left+10*mm,14*mm)


def render_batch(orders, sender, target):
    c=canvas.Canvas(target if hasattr(target,'write') else str(target),pagesize=landscape(A4))
    c.setTitle('PRINTPRO3D paired parcel labels')
    for index,order in enumerate(orders):
        c.saveState()
        c.translate((index%2)*148.5*mm,0)
        draw_label(c,order,sender)
        c.restoreState()
        if index%2==1 or index==len(orders)-1:
            c.saveState();c.setDash(3,3)
            c.line(148.5*mm,5*mm,148.5*mm,205*mm)
            c.restoreState();c.showPage()
    c.save()


def render_label(order,sender,target):
    render_batch([order],sender,target)


def load_settings(root):
    return json.loads((Path(root)/'printing.json').read_text())


def preview_label(order, root):
    output=io.BytesIO()
    render_label(order,load_settings(root)['sender'],output)
    output.seek(0)
    return output


def queue_batch(conn, order_ids):
    ids=sorted(set(order_ids))
    if not ids or len(ids)>200:
        raise ValueError('Select between 1 and 200 labels.')
    marks=','.join('?' for _ in ids)
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        rows=conn.execute(f'SELECT order_id,state FROM print_jobs WHERE order_id IN ({marks})',ids).fetchall()
        if len(rows)!=len(ids) or any(row['state'] not in ('ready','spooled','failed','needs_review') for row in rows):
            raise ValueError('Some selected labels are still being sent to the printer. Refresh and try again.')
        batch=uuid.uuid4().hex
        conn.execute(f"UPDATE print_jobs SET batch_id=?,state='queued',spool_id=NULL,marked_printed=1,message='Batch queued for HP printing' WHERE order_id IN ({marks})",[batch]+ids)
        return batch


def print_one(conn, root, runner=subprocess.run):
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        first=conn.execute("SELECT order_id,batch_id FROM print_jobs WHERE state='queued' ORDER BY created_at,order_id LIMIT 1").fetchone()
        if not first:return False
        batch=first['batch_id'] or uuid.uuid4().hex
        if first['batch_id']:
            rows=conn.execute("SELECT order_id FROM print_jobs WHERE batch_id=? AND state='queued' ORDER BY order_id",(batch,)).fetchall()
            ids=[r['order_id'] for r in rows]
        else:ids=[first['order_id']]
        marks=','.join('?' for _ in ids)
        conn.execute(f"UPDATE print_jobs SET state='rendering',batch_id=?,message='Preparing paired A4 labels' WHERE order_id IN ({marks})",[batch]+ids)
    def status(state,message,spool=None):
        with conn:conn.execute(f'UPDATE print_jobs SET state=?,message=?,spool_id=? WHERE order_id IN ({marks})',[state,message,spool]+ids)
    try:
        settings=json.loads((Path(root)/'printing.json').read_text())
        orders=[dict(conn.execute('SELECT l.*,o.id AS order_id FROM orders o JOIN leads l ON l.id=o.lead_id WHERE o.id=?',(oid,)).fetchone()) for oid in ids]
        folder=Path(root)/'labels';folder.mkdir(exist_ok=True)
        target=folder/f'batch-{batch}.pdf'
        render_batch(orders,settings['sender'],target)
        for order in orders:render_label(order,settings['sender'],folder/f"{order['order_id']}.pdf")
    except Exception:
        status('failed','Batch could not be prepared. Check sender settings, unsupported characters and text length.')
        return True
    status('sending','Sending batch once to printer')
    try:
        result=runner(['/usr/bin/lp','-d',settings['printer'],'-n','1','-o','media=A4','-o','sides=one-sided',str(target)],capture_output=True,text=True,timeout=25)
        match=re.search(r'request id is (\S+)',result.stdout)
        if result.returncode or not match:raise RuntimeError('Unknown print response')
    except Exception:
        status('needs_review','Print result uncertain. Check printer queue before requesting another copy.')
    else:
        status('spooled','Sent to HP printer. Check paper output before scanning.',match.group(1))
    return True
