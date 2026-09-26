import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from oms import create_app
from oms import labels


class LabelFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.app=create_app({'TESTING':True,'DATABASE':str(self.root/'test.db'),'SECRET_KEY':'test','ADMIN_PASSWORD':None})
        self.client=self.app.test_client();self.client.get('/')
        with self.client.session_transaction() as s:self.csrf=s['csrf']
        self.conn=sqlite3.connect(self.root/'test.db');self.conn.row_factory=sqlite3.Row
        self.data=dict(name='Test',phone='0771234567',address='Sample road',city='Colombo',product='Print',quantity=1,cod='100',weight_g=300,action='confirm',intake_key='x'*24)
        self.post('/leads',self.data)
        (self.root/'printing.json').write_text(json.dumps({'printer':'TEST_PRINTER','sender':{'name':'Test sender','address':'Sample sender address','phone':'0771234567'}}))

    def tearDown(self):self.conn.close();self.temp.cleanup()
    def post(self,url,data):return self.client.post(url,data=dict(csrf=self.csrf,**data))

    def test_duplicate_order_only_queues_one_label_and_print_once(self):
        self.post('/leads',self.data)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM print_jobs').fetchone()[0],1)
        self.assertFalse(labels.print_one(self.conn,self.root,Mock()))
        labels.queue_batch(self.conn,[1])
        runner=Mock(return_value=Mock(returncode=0,stdout='request id is TEST_PRINTER-123 (1 file(s))'))
        self.assertTrue(labels.print_one(self.conn,self.root,runner))
        self.assertFalse(labels.print_one(self.conn,self.root,runner))
        runner.assert_called_once()
        self.assertEqual(self.conn.execute('SELECT state FROM print_jobs').fetchone()[0],'spooled')
        self.assertTrue((self.root/'labels/1.pdf').read_bytes().startswith(b'%PDF'))

    def test_uncertain_print_never_retries_itself(self):
        labels.queue_batch(self.conn,[1])
        runner=Mock(side_effect=TimeoutError())
        labels.print_one(self.conn,self.root,runner)
        self.assertEqual(self.conn.execute('SELECT state FROM print_jobs').fetchone()[0],'needs_review')
        self.assertFalse(labels.print_one(self.conn,self.root,runner))
        self.assertEqual(self.post('/orders/1/print-label',{}).status_code,400)

    def test_scan_requires_print_then_authorizes_one_booking(self):
        payload={'reference':'PP3D-000001','waybill_number':'CCP17779999'}
        self.assertEqual(self.post('/scan',payload).status_code,409)
        with self.conn:self.conn.execute("UPDATE print_jobs SET state='spooled'")
        self.assertEqual(self.post('/scan',payload).status_code,302)
        row=self.conn.execute('SELECT state,packing_confirmed,assigned_waybill FROM booking_jobs').fetchone()
        self.assertEqual(tuple(row),('queued',1,'17779999'))
        self.assertEqual(self.post('/scan',payload).status_code,409)
        self.assertEqual(self.post('/orders/1/pack',{}).status_code,409)
        with self.conn:self.conn.execute("UPDATE orders SET status='booked',tracking='17779999'")
        self.assertEqual(self.post('/orders/1/pack',{}).status_code,302)

    def test_scan_does_not_guess_an_order_from_courier_barcode(self):
        self.assertEqual(self.post('/scan',{'reference':'CCP17779999','waybill_number':'17779999'}).status_code,400)
        self.assertEqual(self.conn.execute('SELECT state FROM booking_jobs').fetchone()[0],'pending')

    def test_selected_batch_pairs_labels_and_keeps_unselected_ready(self):
        for n in range(2,5):self.post('/leads',dict(self.data,intake_key=str(n)*24))
        response=self.post('/labels',{'orders':['1','2','3']})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.post('/labels',{'orders':['1','4']}).status_code,400)
        self.assertEqual(self.conn.execute('SELECT state FROM print_jobs WHERE order_id=4').fetchone()[0],'ready')
        runner=Mock(return_value=Mock(returncode=0,stdout='request id is TEST-42 (1 file(s))'))
        labels.print_one(self.conn,self.root,runner)
        runner.assert_called_once()
        target=Path(runner.call_args[0][0][-1])
        self.assertIn(b'/Count 2',target.read_bytes())
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM print_jobs WHERE state='spooled'").fetchone()[0],3)
        self.assertEqual(self.conn.execute('SELECT COUNT(DISTINCT spool_id) FROM print_jobs').fetchone()[0],1)
        self.assertFalse(labels.print_one(self.conn,self.root,runner))

    def test_batch_rejects_empty_and_duplicate_click(self):
        self.assertEqual(self.post('/labels',{}).status_code,400)
        self.assertEqual(self.post('/labels',{'orders':['1','1']}).status_code,302)
        self.assertEqual(self.post('/labels',{'orders':['1']}).status_code,400)
        self.assertEqual(self.client.get('/labels').status_code,200)
        self.assertEqual(self.client.get('/scan/status').status_code,200)

    def test_save_and_add_next_returns_to_desk_without_printing(self):
        r=self.post('/leads',dict(self.data,intake_key='y'*24,return_to='desk'))
        self.assertIn('/?saved=',r.location)
        self.assertEqual(self.conn.execute('SELECT state FROM print_jobs WHERE order_id=2').fetchone()[0],'ready')
