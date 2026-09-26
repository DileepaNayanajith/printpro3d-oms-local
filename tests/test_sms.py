import sqlite3
import tempfile
import unittest
from oms import create_app,sms

class SmsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.app=create_app({'TESTING':True,'DATABASE':self.tmp.name+'/test.db','SECRET_KEY':'test','ADMIN_PASSWORD':None})
        self.client=self.app.test_client();self.client.get('/')
        with self.client.session_transaction() as s:self.csrf=s['csrf']
        self.c=sqlite3.connect(self.app.config['DATABASE'])
        self.data=dict(name='Customer',phone='0771234567',address='Sample',city='Colombo',product='Print',quantity='1',cod='100',weight_g='300',action='confirm',intake_key='a'*24)
    def tearDown(self):self.c.close();self.tmp.cleanup()
    def post(self,path,data=None):return self.client.post(path,data=dict(csrf=self.csrf,**(data or {})))
    def test_processing_is_atomic_unique_and_not_sent(self):
        self.post('/leads',self.data);self.post('/leads',self.data)
        self.assertEqual(self.c.execute('SELECT kind,phone,state FROM sms_outbox').fetchall(),[('processing','94771234567','awaiting_setup')])
    def test_dispatch_requires_packing_and_only_queues_once(self):
        self.post('/leads',self.data)
        self.assertEqual(self.post('/orders/1/dispatch').status_code,409)
        with self.c:self.c.execute("UPDATE orders SET status='packed',tracking='17779999' WHERE id=1")
        self.assertEqual(self.post('/orders/1/dispatch').status_code,302)
        self.assertEqual(self.post('/orders/1/dispatch').status_code,409)
        row=self.c.execute("SELECT body,state FROM sms_outbox WHERE kind='dispatched'").fetchone()
        self.assertIn('17779999',row[0]);self.assertEqual(row[1],'awaiting_setup')
        self.assertNotIn(b'Customer',self.client.get('/packing').data)
        self.assertIn(b'Customer',self.client.get('/packing?status=dispatched').data)
    def test_invalid_sms_number_does_not_lose_order(self):
        self.post('/leads',dict(self.data,phone='0112345678'))
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM orders').fetchone()[0],1)
        self.assertEqual(self.c.execute('SELECT state FROM sms_outbox').fetchone()[0],'invalid_phone')
    def test_normalization(self):
        for value in ['0771234567','+94771234567','94 77 1234567']:
            self.assertEqual(sms.mobile_number(value),'94771234567')
        with self.assertRaises(ValueError):sms.mobile_number('0000000000')
