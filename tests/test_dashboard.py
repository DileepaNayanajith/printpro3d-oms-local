import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from oms import create_app, dashboard, fde_reports

class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=create_app({'TESTING':True,'DATABASE':self.temp.name+'/test.sqlite3','SECRET_KEY':'test','ADMIN_PASSWORD':None})
        self.c=sqlite3.connect(self.app.config['DATABASE']);self.c.row_factory=sqlite3.Row
        self.client=self.app.test_client();self.client.get('/')
        with self.client.session_transaction() as s:self.csrf=s['csrf']
    def tearDown(self):
        self.c.close();self.temp.cleanup()
    def order(self,product,quantity=1):
        self.client.post('/leads',data=dict(csrf=self.csrf,name='Example',phone='0771234567',address='Address',city='Colombo',product=product,quantity=quantity,cod='1850',weight_g=300,action='confirm',intake_key=str(self.c.execute('SELECT COUNT(*) FROM orders').fetchone()[0]).zfill(24)))
    def test_colours_and_ambiguity(self):
        self.assertEqual(dashboard.rack_breakdown('hw white 2 grey 1',3),({'white':2,'gray':1},''))
        self.assertEqual(dashboard.rack_breakdown('hw blk',4),({'black':4},''))
        self.assertTrue(dashboard.rack_breakdown('hw black 3',1)[1])
        self.assertTrue(dashboard.rack_breakdown('hw black white',3)[1])
        self.assertTrue(dashboard.rack_breakdown('keytag black',3)[1])
    def test_value_counts_override_and_handover(self):
        self.order('hw black 3');self.order('hw white 2 grey 1',3);self.order('TEST ONLY hw black',100)
        with self.c:
            self.c.execute("INSERT INTO rack_counts VALUES(1,3,0,0,'confirmed')")
            self.c.execute("UPDATE orders SET tracking='12345678' WHERE id=2")
            self.c.execute("INSERT INTO fde_observations VALUES('12345678','delivered','PP3D-000002',100)")
        d=dashboard.overview(self.c)
        self.assertEqual(d['total_value'],370000)
        self.assertEqual(d['total_racks'],6)
        self.assertEqual(d['pending_racks'],3)
        self.assertEqual(d['delivered_value'],185000)
        self.assertEqual(d['excluded'],1)
        self.assertEqual(self.client.get('/dashboard').status_code,200)
    def test_failed_refresh_preserves_last_good_data(self):
        with self.c:self.c.execute("INSERT INTO fde_report_totals VALUES('waiting',21,21,100)")
        self.assertEqual(fde_reports.request_sync(self.c),1)
        self.assertEqual(fde_reports.request_sync(self.c),0)
        with patch('oms.fde_reports.read_report',side_effect=RuntimeError('offline')):
            fde_reports.run_requested(self.c,None,lambda:None)
        self.assertEqual(self.c.execute("SELECT total FROM fde_report_totals WHERE status='waiting'").fetchone()[0],21)
        self.assertEqual(self.c.execute('SELECT state FROM fde_report_sync').fetchone()[0],'partial')
        self.assertEqual(self.client.post('/dashboard/refresh-courier').status_code,400)

    def test_login_failure_is_actionable_without_zeroing_counts(self):
        with self.c:self.c.execute("INSERT INTO fde_report_totals VALUES('waiting',21,21,100)")
        fde_reports.request_sync(self.c)
        with patch('oms.fde_reports.read_report',side_effect=fde_reports.FDELoginRequired()):
            fde_reports.run_requested(self.c,None,lambda:None)
        self.assertEqual(self.c.execute('SELECT state FROM fde_report_sync').fetchone()[0],'login_required')
        self.assertEqual(self.c.execute('SELECT total FROM fde_report_totals').fetchone()[0],21)
    def test_adjustment_leaves_courier_and_original_quantity_unchanged(self):
        self.order('hw black 3')
        response=self.client.post('/dashboard/orders/1/racks',data=dict(csrf=self.csrf,black=3,white=0,gray=0))
        self.assertEqual(response.status_code,302)
        self.assertEqual(dashboard.overview(self.c)['total_racks'],3)
        self.assertEqual(self.c.execute('SELECT quantity FROM leads').fetchone()[0],1)
        self.assertEqual(self.c.execute('SELECT status FROM orders').fetchone()[0],'awaiting_booking')
        self.assertEqual(self.client.post('/dashboard/orders/1/racks',data=dict(csrf=self.csrf,black=-1,white=0,gray=0)).status_code,400)
