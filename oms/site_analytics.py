"""Anonymous browser presence; no IP addresses, customer identities or query strings."""
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

PAGES={'/','/products','/about','/terms','/warranty','/compare','/contact','/custom-print','/cart','/checkout','/success','/wishlist','/account','/other'}


def migrate(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS site_visitors (
      visitor TEXT PRIMARY KEY, first_seen INTEGER NOT NULL,last_seen INTEGER NOT NULL,
      page TEXT NOT NULL,device TEXT NOT NULL,source TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS site_views (
      event TEXT PRIMARY KEY,visitor TEXT NOT NULL,seen INTEGER NOT NULL,page TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS site_views_seen ON site_views(seen);
      CREATE INDEX IF NOT EXISTS site_visitors_seen ON site_visitors(last_seen);
      CREATE TABLE IF NOT EXISTS site_analytics_meta (id INTEGER PRIMARY KEY CHECK(id=1),started INTEGER NOT NULL,cleaned INTEGER NOT NULL);
    ''')
    c.execute('INSERT OR IGNORE INTO site_analytics_meta VALUES(1,?,?)',(int(time.time()),0))
    c.commit()


def ingest(c,data):
    if not isinstance(data,dict):raise ValueError('Invalid event')
    visitor,event=data.get('visitor'),data.get('event')
    page,device,source=data.get('page'),data.get('device'),data.get('source')
    if not isinstance(visitor,str) or not re.fullmatch(r'[a-f0-9-]{36}',visitor):raise ValueError('Invalid visitor')
    if event is not None and (not isinstance(event,str) or not re.fullmatch(r'[a-f0-9-]{36}',event)):raise ValueError('Invalid event')
    if not isinstance(page,str) or (page not in PAGES and not re.fullmatch(r'/products/\d{1,8}',page)):raise ValueError('Invalid page')
    if device not in ('mobile','tablet','desktop'):raise ValueError('Invalid device')
    if not isinstance(source,str) or len(source)>100 or not re.fullmatch(r'[a-z0-9.-]+',source):raise ValueError('Invalid source')
    now=int(time.time())
    with c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('''INSERT INTO site_visitors VALUES(?,?,?,?,?,?) ON CONFLICT(visitor) DO UPDATE SET
          last_seen=excluded.last_seen,page=excluded.page,device=excluded.device''',(visitor,now,now,page,device,source))
        if event:c.execute('INSERT OR IGNORE INTO site_views VALUES(?,?,?,?)',(event,visitor,now,page))
        if c.execute('SELECT cleaned FROM site_analytics_meta WHERE id=1').fetchone()[0]<now-3600:
            c.execute('DELETE FROM site_visitors WHERE last_seen<?',(now-30*86400,))
            c.execute('DELETE FROM site_views WHERE seen<?',(now-30*86400,))
            c.execute('UPDATE site_analytics_meta SET cleaned=? WHERE id=1',(now,))


def overview(c):
    now=int(time.time())
    today=datetime.fromtimestamp(now,ZoneInfo('Asia/Colombo')).replace(hour=0,minute=0,second=0,microsecond=0)
    since=int(today.timestamp())
    scalar=lambda sql,args=():c.execute(sql,args).fetchone()[0]
    web=c.execute('''SELECT l.id,l.name,l.product,l.quantity,l.status,l.created_at,w.payment,w.total_cents,
      o.id AS order_id,o.status AS order_status,o.tracking,f.status AS courier_status,f.observed_at
      FROM website_orders w JOIN leads l ON l.id=w.lead_id LEFT JOIN orders o ON o.lead_id=l.id
      LEFT JOIN fde_observations f ON f.tracking=replace(upper(o.tracking),'CCP','') ORDER BY l.id DESC LIMIT 50''').fetchall()
    return dict(now=now,started=scalar('SELECT started FROM site_analytics_meta WHERE id=1'),
      active=scalar('SELECT count(*) FROM site_visitors WHERE last_seen>=?',(now-300,)),
      today=scalar('SELECT count(*) FROM site_visitors WHERE last_seen>=?',(since,)),
      views=scalar('SELECT count(*) FROM site_views WHERE seen>=?',(since,)),
      pages=c.execute('SELECT page,count(*) AS count FROM site_views WHERE seen>=? GROUP BY page ORDER BY count DESC LIMIT 10',(since,)).fetchall(),
      sources=c.execute('SELECT source,count(*) AS count FROM site_visitors WHERE last_seen>=? GROUP BY source ORDER BY count DESC LIMIT 10',(since,)).fetchall(),
      devices=c.execute('SELECT device,count(*) AS count FROM site_visitors WHERE last_seen>=? GROUP BY device ORDER BY count DESC',(since,)).fetchall(),
      current=c.execute('SELECT page,count(*) AS count FROM site_visitors WHERE last_seen>=? GROUP BY page ORDER BY count DESC',(now-300,)).fetchall(),
      orders=web,order_count=scalar('SELECT count(*) FROM website_orders'),
      orders_today=scalar("SELECT count(*) FROM website_orders w JOIN leads l ON l.id=w.lead_id WHERE date(l.created_at,'+330 minutes')=?",(today.date().isoformat(),)),
      order_value=scalar('SELECT coalesce(sum(total_cents),0) FROM website_orders'),
      review=scalar("SELECT count(*) FROM website_orders w JOIN leads l ON l.id=w.lead_id WHERE l.status='new'"),
      parcels=c.execute('''SELECT coalesce(f.status,'unknown') AS status,count(*) AS count FROM orders o
        LEFT JOIN fde_observations f ON f.tracking=replace(upper(o.tracking),'CCP','')
        WHERE o.tracking IS NOT NULL AND o.tracking!='' GROUP BY coalesce(f.status,'unknown') ORDER BY count DESC''').fetchall())
