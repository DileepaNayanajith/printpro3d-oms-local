import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from oms import create_app,site_analytics

class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=create_app({'TESTING':True,'DATABASE':str(Path(self.temp.name)/'db'),'SECRET_KEY':'test','ADMIN_PASSWORD':None,'WEBSITE_TOKEN':'fixture-token'})
        self.c=sqlite3.connect(self.app.config['DATABASE']);self.c.row_factory=sqlite3.Row
        self.client=self.app.test_client()
        self.data=dict(visitor=str(uuid.uuid4()),event=str(uuid.uuid4()),page='/products/8',device='mobile',source='facebook.com')
    def tearDown(self):self.c.close();self.temp.cleanup()
    def post(self,data=None,auth=True):
        return self.client.post('/api/website/visit',json=self.data if data is None else data,headers={'Authorization':'Bearer fixture-token'} if auth else {})
    def test_authenticated_heartbeat_does_not_inflate_views(self):
        self.assertEqual(self.post(auth=False).status_code,401)
        self.assertEqual(self.post().status_code,204)
        self.assertEqual(self.post().status_code,204)
        self.assertEqual(self.post(dict(self.data,event=None)).status_code,204)
        result=site_analytics.overview(self.c)
        self.assertEqual((result['active'],result['today'],result['views']),(1,1,1))
        self.assertEqual(result['sources'][0]['source'],'facebook.com')
    def test_sensitive_urls_and_malformed_events_rejected(self):
        for change in [dict(page='/account?email=x'),dict(source='https://example.com/path'),dict(visitor='bad'),dict(device='raw user agent')]:
            self.assertEqual(self.post(dict(self.data,**change)).status_code,400)
        self.assertEqual(self.c.execute('SELECT count(*) FROM site_visitors').fetchone()[0],0)
    def test_presence_expires_without_deleting_daily_count(self):
        self.post()
        with self.c:self.c.execute('UPDATE site_visitors SET last_seen=last_seen-301')
        self.assertEqual(site_analytics.overview(self.c)['active'],0)
    def test_retention_and_day_boundary(self):
        self.post()
        with self.c:
            self.c.execute('UPDATE site_visitors SET last_seen=0')
            self.c.execute('UPDATE site_views SET seen=0')
            self.c.execute('UPDATE site_analytics_meta SET cleaned=0')
        self.post(dict(self.data,visitor=str(uuid.uuid4()),event=str(uuid.uuid4())))
        self.assertEqual(self.c.execute('SELECT count(*) FROM site_visitors').fetchone()[0],1)
        self.assertEqual(self.c.execute('SELECT count(*) FROM site_views').fetchone()[0],1)
    def test_overview_private_and_empty_state_renders(self):
        self.assertEqual(self.client.get('/website-overview').status_code,200)
        from manage import add_user
        add_user(self.c,'packing-test','packer','fixture-password')
        with self.client.session_transaction() as session:session['username']='packing-test';session['role']='packer'
        self.assertEqual(self.client.get('/website-overview').status_code,403)
    def test_sri_lanka_midnight_counts(self):
        # Oct 1 18:30 UTC = Oct 2 midnight in Sri Lanka.
        from datetime import datetime,timezone
        midnight=int(datetime(2026,10,1,18,30,tzinfo=timezone.utc).timestamp())
        with patch('oms.site_analytics.time.time',return_value=midnight-1):self.post()
        with patch('oms.site_analytics.time.time',return_value=midnight+1):
            self.assertEqual(site_analytics.overview(self.c)['today'],0)
            self.assertEqual(site_analytics.overview(self.c)['views'],0)
    def test_website_order_value_and_review_visible(self):
        data=dict(request_id='fixture-website-order-123',name='Sample buyer',phone='0771234567',address='Test address',city='Colombo',product='Black rack',quantity=1,total_cents=185000,payment='bank')
        response=self.client.post('/api/website/orders',json=data,headers={'Authorization':'Bearer fixture-token'})
        self.assertEqual(response.status_code,201)
        result=site_analytics.overview(self.c)
        self.assertEqual((result['order_count'],result['review'],result['order_value']),(1,1,185000))
        page=self.client.get('/website-overview')
        self.assertEqual(page.status_code,200)
        self.assertIn(b'Sample buyer',page.data)
        self.assertIn(b'1,850.00',page.data)
