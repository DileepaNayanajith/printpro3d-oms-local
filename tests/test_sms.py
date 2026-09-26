import sqlite3
import tempfile
import unittest
from unittest.mock import Mock,patch
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

    def test_transport_claims_once_and_uncertain_result_never_retries(self):
        self.post('/leads',self.data)
        self.c.row_factory=sqlite3.Row
        config={'enabled':True,'token':'test-secret','sender_id':'PRINTPRO3D','first_message_id':1}
        def uncertain(config,row):
            self.assertEqual(self.c.execute('SELECT state FROM sms_outbox').fetchone()[0],'sending')
            raise TimeoutError('sensitive error')
        sender=Mock(side_effect=uncertain)
        with patch('oms.sms.settings',return_value=config):
            self.assertTrue(sms.send_one(self.c,self.tmp.name,sender))
            self.assertFalse(sms.send_one(self.c,self.tmp.name,sender))
        sender.assert_called_once()
        self.assertEqual(self.c.execute('SELECT state FROM sms_outbox').fetchone()[0],'needs_review')

    def test_activation_does_not_send_old_messages_and_demo_is_blocked(self):
        self.post('/leads',self.data);self.c.row_factory=sqlite3.Row
        sender=Mock(return_value=('accepted','provider-1'))
        config={'enabled':True,'token':'test-secret','sender_id':'PRINTPRO3D','first_message_id':2}
        with patch('oms.sms.settings',return_value=config):self.assertFalse(sms.send_one(self.c,self.tmp.name,sender))
        self.post('/leads',dict(self.data,intake_key='b'*24))
        with patch('oms.sms.settings',return_value=dict(config,sender_id='TextLKDemo')):self.assertFalse(sms.send_one(self.c,self.tmp.name,sender))
        sender.assert_not_called()
        with patch('oms.sms.settings',return_value=config):self.assertTrue(sms.send_one(self.c,self.tmp.name,sender))
        self.assertEqual(self.c.execute('SELECT state FROM sms_outbox WHERE id=1').fetchone()[0],'awaiting_setup')
        self.assertEqual(self.c.execute('SELECT state FROM sms_outbox WHERE id=2').fetchone()[0],'accepted')

    def test_templates_fit_one_plain_sms_even_with_long_tracking(self):
        self.post('/leads',self.data)
        with self.c:self.c.execute("UPDATE orders SET status='packed',tracking=? WHERE id=1",('X'*64,))
        self.post('/orders/1/dispatch')
        for body, in self.c.execute('SELECT body FROM sms_outbox'):
            self.assertLessEqual(len(body),160);self.assertTrue(body.isascii())

    def test_whatsapp_prefills_current_status_without_marking_message_sent(self):
        from urllib.parse import urlsplit,parse_qs
        self.post('/leads',self.data)
        r=self.client.get('/orders/1/whatsapp')
        self.assertEqual(r.status_code,302)
        self.assertEqual(urlsplit(r.location).netloc,'wa.me')
        self.assertEqual(urlsplit(r.location).path,'/94771234567')
        self.assertIn('confirmed and processing',parse_qs(urlsplit(r.location).query)['text'][0])
        with self.c:self.c.execute("UPDATE orders SET status='booked',tracking='17779999' WHERE id=1")
        body=parse_qs(urlsplit(self.client.get('/orders/1/whatsapp').location).query)['text'][0]
        self.assertIn('being prepared',body)
        self.assertNotIn('has been handed',body)
        with self.c:self.c.execute("UPDATE orders SET status='dispatched' WHERE id=1")
        body=parse_qs(urlsplit(self.client.get('/orders/1/whatsapp').location).query)['text'][0]
        self.assertIn('has been handed',body);self.assertIn('17779999',body)
        self.assertEqual(self.c.execute('SELECT state FROM sms_outbox').fetchone()[0],'awaiting_setup')
