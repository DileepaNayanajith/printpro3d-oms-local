import sqlite3
import tempfile
import unittest
from unittest.mock import Mock
from oms import create_app, whatsapp


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.app=create_app({'TESTING':True,'DATABASE':self.tmp.name+'/test.db','SECRET_KEY':'test','ADMIN_PASSWORD':None})
        self.client=self.app.test_client();self.client.get('/')
        with self.client.session_transaction() as s:self.csrf=s['csrf']
        self.c=sqlite3.connect(self.app.config['DATABASE']);self.c.row_factory=sqlite3.Row
        self.data={'csrf':self.csrf,'name':'Sample Customer','phone':'0771234567','request_key':'a'*24}
    def tearDown(self):
        self.c.close();self.tmp.cleanup()
    def test_submit_is_separate_from_orders_and_duplicate_safe(self):
        for _ in range(2):
            self.assertEqual(self.client.post('/confirmations',data=self.data).status_code,302)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM whatsapp_confirmations').fetchone()[0],1)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM orders').fetchone()[0],0)
        self.assertEqual(self.client.post('/confirmations',data=dict(self.data,request_key='b'*24)).status_code,400)
        row=self.c.execute('SELECT * FROM whatsapp_confirmations').fetchone()
        self.assertEqual(row['phone'],'94771234567')
        self.assertIn('3 or more racks',row['body'])
        self.assertIn('1,850',row['body']);self.assertIn('1,750',row['body'])
        self.assertIn('YES',row['body'])
    def test_bad_phone_and_csrf_do_not_queue(self):
        self.assertEqual(self.client.post('/confirmations',data=dict(self.data,phone='0111234567')).status_code,400)
        self.assertEqual(self.client.post('/confirmations',data=dict(self.data,csrf='bad')).status_code,400)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM whatsapp_confirmations').fetchone()[0],0)
    def test_sender_and_recovery_do_not_repeat_uncertain_messages(self):
        self.client.post('/confirmations',data=self.data)
        browser=Mock();browser.send.side_effect=TimeoutError()
        self.assertTrue(whatsapp.send_one(self.c,browser,'whatsapp_confirmations'))
        self.assertFalse(whatsapp.send_one(self.c,browser,'whatsapp_confirmations'))
        browser.send.assert_called_once()
        self.assertEqual(self.c.execute('SELECT state FROM whatsapp_confirmations').fetchone()[0],'needs_review')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM whatsapp_outbox').fetchone()[0],0)
    def test_success_and_page(self):
        self.client.post('/confirmations',data=self.data)
        browser=Mock()
        self.assertTrue(whatsapp.send_one(self.c,browser,'whatsapp_confirmations'))
        self.assertEqual(self.c.execute('SELECT state FROM whatsapp_confirmations').fetchone()[0],'sent')
        self.assertIn(b'Sample Customer',self.client.get('/confirmations').data)
