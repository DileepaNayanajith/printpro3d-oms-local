import sqlite3,tempfile,unittest,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from oms import create_app,finance,handover
from manage import add_user

class FinanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=str(Path(self.temp.name)/'db')
        self.app=create_app({'TESTING':True,'DATABASE':self.path,'SECRET_KEY':'test','ADMIN_PASSWORD':None})
        self.c=sqlite3.connect(self.path);self.c.row_factory=sqlite3.Row
        self.client=self.app.test_client();self.client.get('/')
        with self.client.session_transaction() as s:self.csrf=s['csrf']
    def tearDown(self):self.c.close();self.temp.cleanup()
    def order(self,qty=1,mode='hot_wheels',key='a'*24):
        return self.client.post('/leads',data=dict(csrf=self.csrf,name='Example',phone='0771234567',address='Address',city='Colombo',product='tampered',product_mode=mode,rack_colour='black',quantity=qty,cod='1',weight_g=300,action='confirm',intake_key=key))
    def booked(self):
        self.order()
        with self.c:
            self.c.execute("UPDATE orders SET status='booked',tracking='12345678',waybill='fixture.pdf'")
    def delivered(self):
        with self.c:
            self.c.execute("INSERT OR REPLACE INTO fde_observations VALUES('12345678','delivered','',?)",(int(time.time()),))
            finance.capture(self.c)
    def test_server_price_threshold_and_custom_price(self):
        for i,(qty,expected) in enumerate([(1,220000),(2,400000),(3,565000)]):
            self.assertEqual(self.order(qty,key=str(i)*24).status_code,302)
            self.assertEqual(self.c.execute('SELECT cod_cents FROM leads ORDER BY id DESC LIMIT 1').fetchone()[0],expected)
        self.order(mode='custom',key='z'*24)
        self.assertEqual(self.c.execute('SELECT cod_cents FROM leads ORDER BY id DESC LIMIT 1').fetchone()[0],100)
    def test_delivered_profit_and_expense_idempotency(self):
        self.booked();self.delivered()
        with self.c:finance.capture(self.c)
        d=finance.overview(self.c,'all');self.assertEqual((d['revenue'],d['outbound'],d['profit']),(220000,40000,180000))
        data=dict(csrf=self.csrf,action='expense',date=finance.today(),category='Facebook ads',amount='100',request_key='a'*32,note='Monthly',month='all')
        for _ in range(2):self.assertEqual(self.client.post('/finance',data=data).status_code,302)
        self.assertEqual(finance.overview(self.c,'all')['profit'],170000)
        self.assertEqual(self.client.get('/finance?month=all').status_code,200)
    def test_return_scans_once_and_never_recredits_revenue(self):
        self.booked();self.delivered()
        first=finance.receive_return(self.c,'CCP12345678','packing02');self.assertFalse(first['duplicate'])
        self.assertTrue(finance.receive_return(self.c,'PP3D-000001','packing02')['duplicate'])
        with self.c:finance.capture(self.c)
        d=finance.overview(self.c,'all');self.assertEqual((d['outbound'],d['inbound'],d['profit']),(40000,40000,-80000))
        with self.assertRaises(ValueError):handover.record(self.c,'PP3D-000001','packing02')
    def test_undelivered_return_never_counts_cod_as_income(self):
        self.booked();finance.receive_return(self.c,'12345678','packing02');self.delivered()
        d=finance.overview(self.c,'all');self.assertEqual(d['revenue'],0);self.assertEqual(d['profit'],-80000)
    def test_concurrent_returns_are_idempotent(self):
        self.booked()
        def run(_):
            c=sqlite3.connect(self.path,timeout=10);c.row_factory=sqlite3.Row
            try:return finance.receive_return(c,'12345678','packing02')['duplicate']
            finally:c.close()
        with ThreadPoolExecutor(2) as pool:self.assertEqual(sorted(pool.map(run,range(2))),[False,True])
        self.assertEqual(finance.overview(self.c,'all')['inbound'],40000)
    def test_packing02_returns_allowed_finance_forbidden_and_csrf(self):
        self.booked();add_user(self.c,'packing02','packer','fixture-password')
        with self.c:self.c.execute("UPDATE users SET packing_only=1 WHERE username='packing02'")
        with self.client.session_transaction() as s:s['username']='packing02';s['role']='packer'
        self.assertEqual(self.client.get('/packing/returns').status_code,200)
        self.assertEqual(self.client.get('/finance').status_code,403)
        self.assertEqual(self.client.post('/packing/returns',data={'barcode':'12345678'}).status_code,400)
        self.assertEqual(self.client.post('/packing/returns',data={'barcode':'12345678','csrf':self.csrf}).status_code,200)
    def test_month_boundaries_owner_corrections_and_snapshot_removal(self):
        self.booked();self.delivered()
        with self.c:
            self.c.execute("UPDATE finance_deliveries SET delivered_on='2026-09-30',date_source='Owner corrected'")
            self.c.execute("UPDATE finance_shipping SET shipped_on='2026-09-29',cost_cents=45000,date_source='Owner corrected'")
            self.c.execute('DELETE FROM fde_observations')
            finance.capture(self.c)
        d=finance.overview(self.c,'2026-09');self.assertEqual(d['profit'],175000)
        self.assertEqual(finance.overview(self.c,'2026-10')['profit'],0)
        self.assertEqual(self.client.get('/finance?month=bad').status_code,400)
