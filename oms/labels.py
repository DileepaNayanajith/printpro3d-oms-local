"""A5 parcel label on the left half of landscape A4; durable local print queue."""
import json
import re
import subprocess
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
    conn.commit()


def enqueue(conn, order_id):
    conn.execute('INSERT OR IGNORE INTO print_jobs(order_id) VALUES(?)',(order_id,))


def render_label(order, sender, target):
    c=canvas.Canvas(str(target),pagesize=landscape(A4))
    c.setTitle('PRINTPRO3D parcel label')
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
    c.setDash(3,3);c.line(148.5*mm,5*mm,148.5*mm,205*mm)
    text('Cut here - A5 parcel label',155*mm,10*mm,9)
    c.showPage();c.save()


def print_one(conn, root, runner=subprocess.run):
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute("SELECT order_id FROM print_jobs WHERE state='queued' ORDER BY order_id LIMIT 1").fetchone()
        if not row:return False
        order_id=row['order_id']
        conn.execute("UPDATE print_jobs SET state='rendering',message='Preparing parcel label' WHERE order_id=?",(order_id,))
    try:
        settings=json.loads((Path(root)/'printing.json').read_text())
        order=dict(conn.execute('SELECT l.*,o.id AS order_id FROM orders o JOIN leads l ON l.id=o.lead_id WHERE o.id=?',(order_id,)).fetchone())
        folder=Path(root)/'labels';folder.mkdir(exist_ok=True)
        target=folder/f'{order_id}.pdf'
        render_label(order,settings['sender'],target)
    except Exception:
        with conn:conn.execute("UPDATE print_jobs SET state='failed',message='Label could not be prepared. Check sender settings and text length.' WHERE order_id=?",(order_id,))
        return True
    with conn:conn.execute("UPDATE print_jobs SET state='sending',message='Sending once to printer' WHERE order_id=?",(order_id,))
    try:
        result=runner(['/usr/bin/lp','-d',settings['printer'],'-n','1','-o','media=A4','-o','sides=one-sided',str(target)],capture_output=True,text=True,timeout=25)
        match=re.search(r'request id is (\S+)',result.stdout)
        if result.returncode or not match:raise RuntimeError('Unknown print response')
    except Exception:
        with conn:conn.execute("UPDATE print_jobs SET state='needs_review',message='Print result uncertain. Check printer queue before requesting another copy.' WHERE order_id=?",(order_id,))
    else:
        with conn:conn.execute("UPDATE print_jobs SET state='spooled',spool_id=?,message='Sent to printer. Check the printed sheet before scanning.' WHERE order_id=?",(match.group(1),order_id))
    return True
