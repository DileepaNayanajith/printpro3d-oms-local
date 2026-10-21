import os,sqlite3,tempfile,unittest
from unittest.mock import patch
from oms import create_app,order_email
class EmailTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.app=create_app({'TESTING':True,'DATABASE':self.tmp.name+'/db','WEBSITE_TOKEN':'test'})
  self.client=self.app.test_client();self.c=sqlite3.connect(self.app.config['DATABASE']);self.c.row_factory=sqlite3.Row
 def tearDown(self):self.c.close();self.tmp.cleanup()
 def intake(self,**extra):
  data=dict(request_id='a'*24,name='Test',phone='0771234567',address='Street',city='Colombo',product='Rack',quantity=1,total_cents=200000,payment='cod',notes='');data.update(extra)
  return self.client.post('/api/website/orders',json=data,headers={'Authorization':'Bearer test'})
 def test_email_optional_and_invalid_header_rejected(self):
  self.assertEqual(self.intake(email='bad\r\nBcc: x@example.com').status_code,201)
  self.assertEqual(self.c.execute('SELECT count(*) FROM order_email_outbox').fetchone()[0],0)
 def test_events_deduplicate_and_capture_tracking(self):
  self.assertEqual(self.intake(notes='Email: buyer@example.com').status_code,201)
  self.intake(notes='Email: buyer@example.com')
  with self.c:
   self.c.execute("INSERT INTO orders(lead_id) VALUES(1)")
   self.c.execute("UPDATE orders SET status='booked',tracking='17770000' WHERE id=1")
   self.c.execute("UPDATE orders SET status='booked' WHERE id=1")
  rows=self.c.execute('SELECT * FROM order_email_outbox').fetchall()
  self.assertEqual(len(rows),3);self.assertEqual(rows[-1]['tracking'],'17770000')
 def test_uncertain_send_not_replayed(self):
  self.intake(email='buyer@example.com')
  with patch.dict(os.environ,{'OMS_SMTP_HOST':'smtp.example.com','OMS_SMTP_USER':'test','OMS_SMTP_PASSWORD':'test','OMS_EMAIL_FROM':'shop@example.com'}):
   calls=[]
   def fail(mail):calls.append(mail);raise TimeoutError()
   self.assertTrue(order_email.send_one(self.c,fail));self.assertFalse(order_email.send_one(self.c,fail));self.assertEqual(len(calls),1)
  self.assertEqual(self.c.execute('SELECT state FROM order_email_outbox').fetchone()[0],'needs_review')
 def test_not_configured_does_not_claim(self):
  self.intake(email='buyer@example.com')
  with patch.dict(os.environ,{},clear=True):self.assertFalse(order_email.send_one(self.c))
  self.assertEqual(self.c.execute('SELECT state FROM order_email_outbox').fetchone()[0],'queued')
 def test_migration_no_historical_messages(self):
  self.intake(notes='Email: buyer@example.com')
  with self.c:self.c.execute('DELETE FROM order_email_outbox')
  order_email.migrate(self.c)
  self.assertEqual(self.c.execute('SELECT count(*) FROM order_email_outbox').fetchone()[0],0)
