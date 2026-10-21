from test_remote import RemoteTests
import time
class ControlTests(RemoteTests):
 def test_control_requires_token(self):
  self.assertEqual(self.client.post('/api/station/control',json={}).status_code,401)
 def test_control_claim_once_and_expiry(self):
  with self.c:
   self.c.execute("INSERT INTO station_controls(kind,created_at) VALUES('fde',?)",(int(time.time()),))
   self.c.execute("INSERT INTO station_controls(kind,created_at) VALUES('whatsapp',0)")
  self.assertEqual([r['kind'] for r in self.post('control').json['commands']],['fde'])
  self.assertEqual(self.post('control').json['commands'],[])
 def test_launcher_rejects_arbitrary_commands(self):
  from station_controller import launch
  with self.assertRaises(ValueError):launch('shell',self.root,{})
 def test_owner_button_requires_csrf_and_online_controller(self):
  from manage import add_user
  add_user(self.c,'owner','admin','test-password-long-enough')
  with self.client.session_transaction() as s:s['username']='owner';s['role']='admin'
  self.assertEqual(self.client.post('/station',data={'action':'open-fde'}).status_code,400)
  self.assertEqual(self.client.post('/station',data={'action':'open-fde','csrf':self.csrf}).status_code,409)
  self.post('control')
  self.assertEqual(self.client.post('/station',data={'action':'open-fde','csrf':self.csrf}).status_code,302)
  self.assertEqual(self.c.execute('SELECT kind FROM station_controls').fetchone()[0],'fde')
