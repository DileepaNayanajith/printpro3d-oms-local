import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from oms import create_app, handover
from manage import add_user

class HandoverTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=self.tmp.name+'/test.db'
        self.app=create_app({'TESTING':True,'DATABASE':self.path,'SECRET_KEY':'test'})
        self.c=sqlite3.connect(self.path);self.c.row_factory=sqlite3.Row
        add_user(self.c,'packing02','packer','fixture-password-only')
        add_user(self.c,'owner','admin','fixture-password-only')
        with self.c:
            self.c.execute("UPDATE users SET packing_only=1 WHERE username='packing02'")
            self.c.execute("INSERT INTO leads(id,name,phone,address,city,cod_cents) VALUES(1,'Fixture customer','0770000000','Private address','Colombo',225000)")
            self.c.execute("INSERT INTO orders(id,lead_id,status,tracking) VALUES(1,1,'booked','CCP12345678')")
            self.c.execute("INSERT INTO print_jobs(order_id,state,marked_printed) VALUES(1,'spooled',1)")
        self.client=self.app.test_client();self.client.get('/login')
        with self.client.session_transaction() as s:csrf=s['csrf']
        response=self.client.post('/login',data={'csrf':csrf,'username':'packing02','password':'fixture-password-only'})
        self.assertEqual(response.location,'/packing')
        with self.client.session_transaction() as s:self.csrf=s['csrf']
    def tearDown(self):self.c.close();self.tmp.cleanup()
    def scan(self,barcode='PP3D-000001'):
        return self.client.post('/packing/handover',data={'csrf':self.csrf,'barcode':barcode})
    def test_packing_only_access_and_minimal_data(self):
        page=self.client.get('/packing');self.assertEqual(page.status_code,200)
        self.assertNotIn(b'/labels',page.data);self.assertNotIn(b'Private address',page.data)
        for path in ['/dashboard','/handovers','/labels','/scan','/orders/1','/orders.csv','/help','/station']:
            self.assertEqual(self.client.get(path).status_code,403,path)
        self.assertEqual(self.client.get('/').location,'/packing')
        self.assertEqual(self.client.post('/orders/1/dispatch',data={'csrf':self.csrf}).status_code,403)
    def test_scan_marks_out_and_duplicate_never_increments(self):
        first=self.scan();self.assertEqual(first.status_code,200)
        self.assertFalse(first.json['duplicate']);self.assertEqual(first.json['today_count'],1)
        self.assertEqual(first.json['name'],'Fixture customer');self.assertEqual(first.json['cod_cents'],225000)
        self.assertNotIn('phone',first.json)
        again=self.scan();self.assertTrue(again.json['duplicate']);self.assertEqual(again.json['today_count'],1)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM parcel_handovers').fetchone()[0],1)
        self.assertEqual(self.c.execute('SELECT status FROM orders').fetchone()[0],'dispatched')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM events').fetchone()[0],1)
    def test_unbooked_unprinted_and_invalid_barcodes_are_rejected(self):
        for code in ['CCP12345678','000001','PP3D-999999']:
            self.assertEqual(self.scan(code).status_code,409)
        with self.c:self.c.execute("UPDATE orders SET status='awaiting_booking'")
        self.assertEqual(self.scan().status_code,409)
        with self.c:
            self.c.execute("UPDATE orders SET status='booked'")
            self.c.execute("UPDATE print_jobs SET marked_printed=0,state='ready'")
        self.assertEqual(self.scan().status_code,409)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM parcel_handovers').fetchone()[0],0)
    def test_concurrent_scans_count_once(self):
        def run(_):
            c=sqlite3.connect(self.path,timeout=10);c.row_factory=sqlite3.Row
            try:return handover.record(c,'PP3D-000001','packing02')['duplicate']
            finally:c.close()
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(run,range(2)))
        self.assertEqual(sorted(results),[False,True])
    def test_sri_lanka_dates_and_old_dispatched_orders(self):
        self.scan()
        with self.c:self.c.execute("UPDATE parcel_handovers SET created_at='2026-09-30 19:00:00'")
        self.assertEqual(handover.report(self.c,'2026-10-01')['count'],1)
        self.assertEqual(handover.report(self.c,'2026-09-30')['count'],0)
        with self.c:self.c.execute('DELETE FROM parcel_handovers')
        self.assertTrue(self.scan().json['duplicate'])
        self.assertEqual(self.scan().json['today_count'],0)
    def test_csrf_and_account_revocation(self):
        self.assertEqual(self.client.post('/packing/handover',data={'barcode':'PP3D-000001'}).status_code,400)
        with self.c:self.c.execute("UPDATE users SET active=0 WHERE username='packing02'")
        self.assertEqual(self.scan().location,'/login')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM parcel_handovers').fetchone()[0],0)
