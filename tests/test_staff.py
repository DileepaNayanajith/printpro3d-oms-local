import re
import sqlite3
import tempfile
import unittest
from oms import create_app
from manage import add_user


class StaffTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=create_app({'TESTING':True,'DATABASE':self.temp.name+'/staff.sqlite3','SECRET_KEY':'test','ADMIN_PASSWORD':None})
        self.conn=sqlite3.connect(self.app.config['DATABASE'])
        self.client=self.app.test_client()
        self.client.get('/')
        with self.client.session_transaction() as s:self.csrf=s['csrf']
        self.data=dict(name='Test customer',phone='0771234567',address='Test address',city='Colombo',product='Print',quantity='1',cod='500',weight_g='300')

    def tearDown(self):
        self.conn.close(); self.temp.cleanup()

    def post(self,path,data):
        return self.client.post(path,data=dict(csrf=self.csrf,**data))

    def login(self,name,password='a-long-test-password'):
        result=self.post('/login',dict(username=name,password=password))
        with self.client.session_transaction() as s:self.csrf=s['csrf']
        return result

    def test_one_step_order_is_idempotent(self):
        page=self.client.get('/').data.decode()
        key=re.search(r'name="intake_key" value="([^"]+)"',page).group(1)
        payload=dict(self.data,action='confirm',intake_key=key)
        first=self.post('/leads',payload); second=self.post('/leads',payload)
        self.assertEqual(first.status_code,302)
        self.assertEqual(first.location,second.location)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM orders').fetchone()[0],1)
        self.assertEqual(self.conn.execute('SELECT status FROM leads').fetchone()[0],'qualified')

    def test_incomplete_confirmed_order_stays_unsaved(self):
        result=self.post('/leads',dict(self.data,action='confirm',intake_key='x'*24,address=''))
        self.assertEqual(result.status_code,400)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM leads').fetchone()[0],0)

    def test_named_roles_hashing_and_revocation(self):
        add_user(self.conn,'alice','caller','a-long-test-password')
        add_user(self.conn,'packer','packer','a-long-test-password')
        self.assertNotEqual(self.conn.execute("SELECT password_hash FROM users WHERE username='alice'").fetchone()[0],'a-long-test-password')
        self.assertEqual(self.client.get('/').status_code,302)
        self.assertEqual(self.login('alice','wrong').status_code,400)
        self.assertEqual(self.login('alice').status_code,302)
        self.assertEqual(self.client.get('/').status_code,200)
        self.post('/leads',dict(self.data,action='confirm',intake_key='a'*24))
        self.assertEqual(self.conn.execute('SELECT actor FROM events').fetchone()[0],'alice')
        with self.conn:self.conn.execute("UPDATE users SET active=0 WHERE username='alice'")
        self.assertEqual(self.client.get('/').status_code,302)
        self.assertEqual(self.login('packer').status_code,302)
        self.assertEqual(self.client.get('/packing').status_code,200)
        self.assertEqual(self.client.get('/courier').status_code,403)
        self.assertEqual(self.client.get('/orders.csv').status_code,403)

    def test_search_and_packing_views(self):
        self.post('/leads',dict(self.data,action='confirm',intake_key='b'*24))
        self.assertIn(b'Test customer',self.client.get('/?q=0771234567').data)
        self.assertNotIn(b'Test customer',self.client.get('/?q=nothing-matches').data)
        self.assertIn(b'Test customer',self.client.get('/packing').data)
        self.assertNotIn(b'Test customer',self.client.get('/packing?status=packed').data)


if __name__=='__main__':unittest.main()
