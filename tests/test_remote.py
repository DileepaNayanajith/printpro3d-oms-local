import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from werkzeug.exceptions import HTTPException
from oms import create_app, remote, automation
from oms.station_client import execute, recover, API


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.app=create_app({'TESTING':True,'DATABASE':str(self.root/'db.sqlite3'),'SECRET_KEY':'test','ADMIN_PASSWORD':None})
        self.c=sqlite3.connect(self.app.config['DATABASE']);self.c.row_factory=sqlite3.Row
        self.client=self.app.test_client();self.client.get('/')
        with self.client.session_transaction() as s:self.csrf=s['csrf']
        self.client.post('/leads',data=dict(csrf=self.csrf,name='Sample',phone='0771234567',address='Address',city='Colombo',product='hw black',quantity=1,cod='1850',weight_g=300,action='confirm',intake_key='z'*24))
        self.token=remote.issue_token(self.c)
        self.app.config['CLOUD_MODE']=True
        self.headers={'Authorization':'Bearer '+self.token}
    def tearDown(self):self.c.close();self.temp.cleanup()
    def post(self,path,data=None):return self.client.post('/api/station/'+path,json=data or {},headers=self.headers)
    def reserve(self):automation.reserve(self.c,1,'12345678',1,'test',packing_confirmed=True)
    def test_api_is_authenticated_without_csrf_and_local_mode_disabled(self):
        self.assertEqual(self.client.post('/api/station/poll',json={'kind':'fde','ready':True}).status_code,401)
        self.assertEqual(self.post('poll',{'kind':'fde','ready':False}).status_code,200)
        self.assertNotEqual(self.c.execute('SELECT token_hash FROM home_station').fetchone()[0],self.token)
        self.app.config['CLOUD_MODE']=False
        self.assertEqual(self.post('poll',{'kind':'fde'}).status_code,404)
    def test_offline_station_leaves_order_queued(self):
        self.reserve();self.post('poll',{'kind':'fde','ready':False})
        self.assertEqual(self.c.execute('SELECT state FROM booking_jobs').fetchone()[0],'queued')
    def test_fde_success_is_atomic_and_ack_is_idempotent(self):
        self.reserve();t=self.post('poll',{'kind':'fde','ready':True}).json['task'];tid=t['id']
        self.assertIsNone(self.post('poll',{'kind':'fde','ready':True}).json['task'])
        self.assertEqual(self.post(tid+'/result',{'outcome':'success'}).status_code,409)
        self.assertEqual(self.post(tid+'/start').status_code,200)
        self.assertEqual(self.post(tid+'/start').status_code,409)
        self.assertEqual(self.post(tid+'/result',{'outcome':'success'}).status_code,200)
        self.assertEqual(self.post(tid+'/result',{'outcome':'success'}).status_code,200)
        self.assertEqual(self.c.execute('SELECT tracking FROM orders').fetchone()[0],'12345678')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM whatsapp_outbox').fetchone()[0],1)
    def test_uncertain_submission_never_requeues(self):
        self.reserve();t=self.post('poll',{'kind':'fde','ready':True}).json['task']
        self.post(t['id']+'/start');self.post(t['id']+'/result',{'outcome':'uncertain'})
        self.assertEqual(self.c.execute('SELECT state FROM booking_jobs').fetchone()[0],'needs_review')
        self.assertIsNone(self.post('poll',{'kind':'fde','ready':True}).json['task'])
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM whatsapp_outbox').fetchone()[0],0)
    def test_expiry_rejects_old_executor(self):
        self.reserve();t=self.post('poll',{'kind':'fde','ready':True}).json['task']
        with self.c:self.c.execute('UPDATE station_tasks SET updated_at=0')
        self.assertEqual(self.post(t['id']+'/start').status_code,409)
        # The failed request rolls back its transaction; the next poll durably expires it.
        self.post('poll',{'kind':'fde','ready':True})
        self.assertEqual(self.c.execute('SELECT state FROM booking_jobs').fetchone()[0],'needs_review')
        self.assertEqual(self.post(t['id']+'/result',{'outcome':'success'}).status_code,409)
    def test_only_scan_authorized_booking_is_claimed(self):
        automation.reserve(self.c,1,'12345678',1,'test',packing_confirmed=False)
        self.assertIsNone(self.post('poll',{'kind':'fde','ready':True}).json['task'])
    def test_blocked_preparation_can_be_explicitly_retried(self):
        self.reserve();t=self.post('poll',{'kind':'fde','ready':True}).json['task']
        self.post(t['id']+'/result',{'outcome':'blocked'})
        with self.c:self.c.execute("UPDATE booking_jobs SET state='queued'")
        t2=self.post('poll',{'kind':'fde','ready':True}).json['task']
        self.assertNotEqual(t['id'],t2['id'])
    def test_revocation_stops_execution(self):
        self.reserve();t=self.post('poll',{'kind':'fde','ready':True}).json['task']
        with self.c:self.c.execute('UPDATE home_station SET enabled=0')
        self.assertEqual(self.post(t['id']+'/start').status_code,401)
    def test_cloud_has_no_open_demo(self):
        self.assertEqual(self.client.get('/').status_code,503)
        self.assertEqual(self.client.get('/healthz').status_code,200)

    def test_print_batch_and_preparation_failure(self):
        from oms import labels
        with self.c:labels.enqueue(self.c,1)
        labels.queue_batch(self.c,[1])
        with patch('oms.remote.labels.load_settings',return_value={'sender':{'name':'Test','address':'Address','phone':'0700000000'}}):
            task=self.post('poll',{'kind':'print','ready':True}).json['task']
        self.assertEqual(len(task['payload']['orders']),1)
        self.post(task['id']+'/result',{'outcome':'blocked'})
        self.assertEqual(self.c.execute('SELECT state FROM print_jobs').fetchone()[0],'failed')
        labels.queue_batch(self.c,[1])
        with patch('oms.remote.labels.load_settings',return_value={'sender':{'name':'Test','address':'Address','phone':'0700000000'}}):
            task=self.post('poll',{'kind':'print','ready':True}).json['task']
        self.post(task['id']+'/start')
        self.post(task['id']+'/result',{'outcome':'success'})
        self.assertEqual(self.c.execute('SELECT state FROM print_jobs').fetchone()[0],'spooled')
    def test_confirmation_send_and_duplicate_result(self):
        from oms import confirmations
        confirmations.queue(self.c,'Example','0771234567','confirmation-test-key-1234')
        task=self.post('poll',{'kind':'confirmation','ready':True}).json['task']
        self.assertEqual(task['payload']['include_photo'],1)
        self.post(task['id']+'/start')
        for _ in range(2):self.assertEqual(self.post(task['id']+'/result',{'outcome':'success'}).status_code,200)
        self.assertEqual(self.c.execute('SELECT state FROM whatsapp_confirmations').fetchone()[0],'sent')
        self.assertIsNone(self.post('poll',{'kind':'confirmation','ready':True}).json['task'])
    def test_reports_keep_unknown_categories_unchanged(self):
        from oms import fde_reports
        fde_reports.request_sync(self.c)
        task=self.post('poll',{'kind':'reports','ready':True}).json['task']
        self.post(task['id']+'/start')
        result={'outcome':'success','reports':{'waiting':{'total':1,'rows':{'12345678':'PP3D-000001'}}}}
        self.assertEqual(self.post(task['id']+'/result',result).status_code,200)
        self.assertEqual(self.c.execute('SELECT total FROM fde_report_totals').fetchone()[0],1)
        self.assertEqual(self.c.execute('SELECT state FROM fde_report_sync').fetchone()[0],'partial')
    def test_only_owner_can_pair_and_sign_in_is_rate_limited(self):
        from manage import add_user
        add_user(self.c,'packer','packer','long-enough-test-password')
        with self.client.session_transaction() as s:s['username']='packer';s['role']='packer'
        self.assertEqual(self.client.get('/station').status_code,403)
        with self.client.session_transaction() as s:s.clear()
        self.client.get('/login')
        with self.client.session_transaction() as s:csrf=s['csrf']
        for _ in range(10):
            self.assertEqual(self.client.post('/login',data={'csrf':csrf,'username':'packer','password':'wrong'}).status_code,400)
        self.assertEqual(self.client.post('/login',data={'csrf':csrf,'username':'packer','password':'wrong'}).status_code,429)

class JournalTests(unittest.TestCase):
    def test_lost_start_ack_does_not_perform(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal=Path(tmp)/'job.json';api=Mock();api.post.side_effect=TimeoutError()
            perform=Mock()
            with self.assertRaises(TimeoutError):execute(api,{'id':'a'},journal,lambda t:None,perform)
            perform.assert_not_called();self.assertTrue(journal.exists())
            api.post.side_effect=None;recover(api,journal)
            api.post.assert_called_with('a/result',{'outcome':'uncertain'})
    def test_lost_result_ack_retries_ack_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal=Path(tmp)/'job.json';api=Mock();api.post.side_effect=[{},TimeoutError()]
            perform=Mock(return_value={})
            with self.assertRaises(TimeoutError):execute(api,{'id':'b'},journal,lambda t:None,perform)
            self.assertEqual(perform.call_count,1)
            api.post.side_effect=None;recover(api,journal)
            api.post.assert_called_with('b/result',{'outcome':'success'})
            self.assertFalse(journal.exists())
    def test_http_and_credential_urls_rejected(self):
        for url in ['http://example.com','https://user:pass@example.com','https://example.com/x']:
            with self.assertRaises(ValueError):API(url,'test')

class TransferTests(unittest.TestCase):
    def test_snapshot_round_trip_and_no_secret_files(self):
        from cloud_transfer import export,restore
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';source.mkdir();target=root/'target'
            app=create_app({'TESTING':True,'DATABASE':str(source/'oms.sqlite3'),'SECRET_KEY':'test','ADMIN_PASSWORD':None})
            (source/'staff-access.txt').write_text('DO NOT COPY')
            (source/'session-secret').write_text('DO NOT COPY')
            (source/'printing.json').write_text(json.dumps({'printer':'old Mac printer','sender':{'name':'Business','address':'Address','phone':'0700000000'}}))
            archive=root/'snapshot.zip';export(source,archive)
            import zipfile
            with zipfile.ZipFile(archive) as z:
                self.assertEqual(set(z.namelist()),{'oms.sqlite3','printing.json'})
                self.assertNotIn('printer',json.loads(z.read('printing.json')))
            restore(archive,target)
            with sqlite3.connect(target/'oms.sqlite3') as c:self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            with self.assertRaises(ValueError):restore(archive,target)
    def test_zip_traversal_rejected(self):
        from cloud_transfer import restore
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive=root/'bad.zip'
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr('oms.sqlite3',b'bad');z.writestr('../escape',b'bad')
            with self.assertRaises(ValueError):restore(archive,root/'target')
            self.assertFalse((root/'escape').exists())

class CloudStartupTests(unittest.TestCase):
    def test_cloud_startup_uses_persistent_directory_and_owner_access(self):
        import os
        from cloud_serve import build_app
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{
            'OMS_CLOUD':'1','OMS_HTTPS':'1','OMS_SECRET':'s'*40,'OMS_INSTANCE_PATH':tmp,
            'OMS_OWNER_PASSWORD':'an-owner-test-password','OMS_PACKING_PASSWORD':'a-packer-test-password',
            'OMS_SENDER_NAME':'Business','OMS_SENDER_ADDRESS':'Address','OMS_SENDER_PHONE':'0700000000'
        }):
            app=build_app();app.config['TESTING']=True
            self.assertEqual(app.config['DATABASE'],str(Path(tmp)/'oms.sqlite3'))
            self.assertTrue(app.config['SESSION_COOKIE_SECURE'])
            client=app.test_client();client.get('/login',base_url='https://example.com')
            with client.session_transaction(base_url='https://example.com') as s:csrf=s['csrf']
            response=client.post('/login',base_url='https://example.com',data={'csrf':csrf,'username':'owner','password':'an-owner-test-password'})
            self.assertEqual(response.status_code,302)
            self.assertEqual(client.get('/station',base_url='https://example.com').status_code,200)
            with client.session_transaction(base_url='https://example.com') as s:csrf=s['csrf']
            self.assertEqual(client.post('/station',base_url='https://example.com',data={'csrf':csrf,'action':'pair'}).status_code,200)
            self.assertNotIn(b'Copy this pairing key',client.get('/station',base_url='https://example.com').data)
