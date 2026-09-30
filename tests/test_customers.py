import tempfile
import unittest
import sqlite3
from unittest.mock import patch
from oms import create_app

class CustomersTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=self.tmp.name+'/test.db'
  self.app=create_app({'TESTING':True,'DATABASE':self.path,'WEBSITE_TOKEN':'secret','ADMIN_PASSWORD':None})
  self.c=self.app.test_client();self.headers={'Authorization':'Bearer secret','X-Store-Client':'test'}
 def tearDown(self):self.tmp.cleanup()
 def auth(self,action='register',**data):
  return self.c.post('/api/website/account/'+action,json=dict(username='customer1',password='long-test-password',name='Customer',**data),headers=self.headers)
 def account(self,name):
  r=self.c.post('/api/website/account/register',json=dict(username=name,password='long-test-password',name=name),headers=self.headers)
  self.assertEqual(r.status_code,200,r.data);return dict(self.headers,**{'X-Customer-Session':r.json['token']})
 def checkout(self,headers,payment='bank'):
  return self.c.post('/api/website/orders',json=dict(request_id='idempotency-key-1234567',name='Customer',phone='0771234567',city='Colombo',address='A street',product='1 x item',quantity=1,total_cents=185000,payment=payment),headers=headers)
 def test_identity_ownership_logout(self):
  a=self.account('alice');b=self.account('bob')
  r=self.checkout(a);self.assertEqual(r.status_code,201,r.data)
  self.assertEqual(len(self.c.get('/api/website/account/orders',headers=a).json['orders']),1)
  self.assertEqual(self.c.get('/api/website/account/orders',headers=b).json['orders'],[])
  self.assertEqual(self.c.post('/api/website/account/returns',json=dict(reference=r.json['reference'],reason='The product arrived broken'),headers=b).status_code,404)
  for _ in range(2):self.assertEqual(self.c.post('/api/website/account/returns',json=dict(reference=r.json['reference'],reason='The product arrived broken'),headers=a).status_code,200)
  with sqlite3.connect(self.path) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM customer_returns').fetchone()[0],1)
  self.c.post('/api/website/account/logout',json={},headers=a)
  self.assertEqual(self.c.get('/api/website/account/orders',headers=a).status_code,401)
  self.assertEqual(self.checkout(a).status_code,401)
 def test_login_and_throttle(self):
  self.account('customer1');self.assertEqual(self.auth('login').status_code,200)
  with sqlite3.connect(self.path) as c:
   stored=c.execute('SELECT password_hash FROM customers').fetchone()[0];self.assertNotEqual(stored,'long-test-password')
  for _ in range(16):r=self.c.post('/api/website/account/login',json=dict(username='customer1',password='wrong-password'),headers=self.headers)
  self.assertEqual(r.status_code,429)
 def test_bank_blocks_qualification(self):
  a=self.account('alice');self.checkout(a)
  self.c.get('/')
  with self.c.session_transaction() as s:csrf=s['csrf']
  data=dict(csrf=csrf,name='Customer',phone='0771234567',city='Colombo',address='A street',product='item',quantity='1',cod='1850',weight_g='500',action='qualify')
  self.assertEqual(self.c.post('/leads/1',data=data).status_code,400)
  self.assertEqual(self.c.post('/leads/1',data=dict(data,payment_verified='yes')).status_code,302)
  with sqlite3.connect(self.path) as c:
   self.assertEqual(c.execute('SELECT cod_cents FROM leads').fetchone()[0],0)
   self.assertEqual(c.execute('SELECT payment_verified FROM website_orders').fetchone()[0],1)
 def test_google_unconfigured_and_invalid(self):
  self.assertEqual(self.c.post('/api/website/account/google',json={'credential':'fake'},headers=self.headers).status_code,503)
  self.app.config['GOOGLE_CLIENT_ID']='test-google-client'
  with patch('google.oauth2.id_token.verify_oauth2_token',side_effect=ValueError('invalid')):
   self.assertEqual(self.c.post('/api/website/account/google',json={'credential':'fake'},headers=self.headers).status_code,401)
  with patch('google.oauth2.id_token.verify_oauth2_token',return_value={'sub':'verified-google-123','email_verified':True,'name':'Google customer'}) as verify:
   response=self.c.post('/api/website/account/google',json={'credential':'verified-token'},headers=self.headers)
   self.assertEqual(response.status_code,200);self.assertEqual(verify.call_args.args[2],'test-google-client')
 def test_customer_routes_require_bridge_auth(self):
  for path in ['orders','config']:
   self.assertEqual(self.c.get('/api/website/account/'+path).status_code,401)
