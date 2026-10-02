"""Read-only business totals; explicit overrides for ambiguous product descriptions."""
import re
from collections import Counter

COLORS=('black','white','gray')
ALIASES={'black':'black','blk':'black','white':'white','gray':'gray','grey':'gray'}

def migrate(c):
    c.execute('''CREATE TABLE IF NOT EXISTS rack_counts (
      order_id INTEGER PRIMARY KEY REFERENCES orders(id),black INTEGER NOT NULL,
      white INTEGER NOT NULL,gray INTEGER NOT NULL,note TEXT NOT NULL DEFAULT '')''')
    c.commit()


def rack_breakdown(product,quantity):
    text=product.lower()
    if not re.search(r'\b(hw|hot\s*wheels?|racks?)\b',text):
        return {},'Not identified as a rack product'
    matches=list(re.finditer(r'\b(black|blk|white|gray|grey)\b(?:\s*[:x-]?\s*(\d+))?',text))
    if not matches:return {},'Colour missing'
    if len(matches)==1:
        m=matches[0]
        if m[2] and int(m[2])!=quantity:return {},'Product description and quantity disagree'
        return {ALIASES[m[1]]:quantity},''
    if any(not m[2] for m in matches):return {},'Mixed colours need individual counts'
    result=Counter()
    for m in matches:result[ALIASES[m[1]]]+=int(m[2])
    if sum(result.values())!=quantity:return {},'Colour counts do not match quantity'
    return dict(result),''


def overview(c):
    rows=c.execute('''SELECT o.id,o.status,o.tracking,o.created_at,l.name,l.product,l.quantity,l.cod_cents,
      j.state AS booking_state,r.black,r.white,r.gray,r.note,
      f.status AS courier_status,f.observed_at
      FROM orders o JOIN leads l ON l.id=o.lead_id LEFT JOIN booking_jobs j ON j.order_id=o.id
      LEFT JOIN rack_counts r ON r.order_id=o.id LEFT JOIN fde_observations f ON f.tracking=replace(upper(o.tracking),'CCP','')
      ORDER BY o.id DESC''').fetchall()
    orders=[];excluded=0;colours=Counter();all_colours=Counter();stages=Counter();issues=[]
    handed={'pickup','transferred','processing','dispatched','delivered','rearranged','rescheduled','date_changed','return_pending','return_complete','return_transferred','damaged','hold'}
    for row in rows:
        d=dict(row)
        if 'test only' in d['product'].lower():excluded+=1;continue
        counts,warning=rack_breakdown(d['product'],d['quantity'])
        if d['black'] is not None:counts={k:d[k] for k in COLORS};warning=''
        d['racks']=sum(counts.values());d['colours']=counts;d['warning']=warning
        d['to_send']=d['status']!='dispatched' and d['courier_status'] not in handed
        all_colours.update(counts)
        if d['to_send']:colours.update(counts)
        stages[d['status']]+=1
        if warning:issues.append(d)
        orders.append(d)
    money=sum(d['cod_cents'] for d in orders)
    return dict(orders=orders,excluded=excluded,colours=colours,all_colours=all_colours,
      total_racks=sum(all_colours.values()),pending_racks=sum(colours.values()),issues=issues,
      total_value=money,stages=stages,to_pack=sum(d['to_send'] and d['status']!='packed' for d in orders),
      ready=sum(d['to_send'] and d['status']=='packed' for d in orders),
      to_book=sum(d['status']=='awaiting_booking' for d in orders),
      courier_unknown=sum(bool(d['tracking']) and not d['courier_status'] for d in orders),
      delivered_value=sum(d['cod_cents'] for d in orders if d['courier_status']=='delivered'))
