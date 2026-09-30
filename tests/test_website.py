import sqlite3
import tempfile
import unittest
from oms import create_app

class WebsiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.app=create_app({'TESTING':True,'DATABASE':self.tmp.name+'/test.db','WEBSITE_TOKEN':'test-private-token'})
        self.client=self.app.test_client()
        self.payload=dict(request_id='a'*24,name='Test Customer',phone='+94771234567',address='Test Street',city='Colombo',product='2 x Test item',quantity=2,total_cents=410000,payment='cod',notes='Test')
    def tearDown(self):self.tmp.cleanup()
    def post(self, **changes):
        return self.client.post('/api/website/orders',json=dict(self.payload,**changes),headers={'Authorization':'Bearer test-private-token'})
    def test_auth(self):
        self.assertEqual(self.client.post('/api/website/orders',json=self.payload).status_code,401)
    def test_retry_and_conflict(self):
        first=self.post(); self.assertEqual(first.status_code,201)
        self.assertEqual(first.json,self.post().json)
        self.assertEqual(self.post(name='Changed').status_code,409)
        with sqlite3.connect(self.app.config['DATABASE']) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM leads').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM orders').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT phone FROM leads').fetchone()[0],'0771234567')
        self.assertIn(first.json['reference'].encode(),self.client.get('/').data)
    def test_bank_unverified(self):
        self.assertEqual(self.post(payment='bank').status_code,201)
        with sqlite3.connect(self.app.config['DATABASE']) as c:
            row=c.execute('SELECT status,notes,cod_cents FROM leads').fetchone()
            self.assertEqual(row[0],'new');self.assertIn('UNVERIFIED',row[1]);self.assertEqual(row[2],0)
    def test_validation(self):
        for data in [dict(phone='bad'),dict(quantity=True),dict(total_cents=-1),dict(city=''),dict(payment='paid')]:
            self.assertEqual(self.post(**data).status_code,400)
