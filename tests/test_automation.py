import sqlite3
import tempfile
import unittest
from unittest.mock import Mock

from oms import create_app, SCHEMA
from oms import automation as jobs
from oms.fde_browser import FDEBrowser, FormMismatch, SignInRequired, field_values


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name+'/test.sqlite3'
        self.app = create_app({'TESTING':True,'DATABASE':self.path,'SECRET_KEY':'test',
                               'ADMIN_PASSWORD':None,'ENABLE_LIVE_BOOKING':False})
        self.client = self.app.test_client()
        self.client.get('/')
        with self.client.session_transaction() as session:
            self.csrf = session['csrf']
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        data = dict(name='Test customer',phone='0771234567',address='Test only',city='Colombo',
                    product='Blue keytag',quantity='2',cod='1999.50',weight_g='1200')
        for n in (1,2):
            self.post('/leads',data)
            self.post(f'/leads/{n}',dict(data,action='qualify'))

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def post(self,path,data=None):
        return self.client.post(path,data=dict(csrf=self.csrf,**(data or {})))

    def queue(self,number='0017778578'):
        self.assertEqual(self.post('/orders/1/prepare',{'waybill_number':number,'weight_kg':'2'}).status_code,302)

    def prepared(self):
        self.queue()
        self.assertEqual(jobs.claim(self.conn),1)
        browser = Mock()
        self.assertTrue(jobs.prepare_one(self.conn,1,browser))
        browser.submit.assert_not_called()
        return browser

    def test_tracking_entry_alone_cannot_mark_order_booked(self):
        self.assertEqual(self.post('/orders/1/booking', {'tracking':'17778578'}).status_code,400)
        self.assertEqual(jobs.snapshot(self.conn,1)['state'],'pending')
        self.assertIsNone(self.conn.execute('SELECT tracking FROM orders WHERE id=1').fetchone()[0])
        page=self.client.get('/orders/1').data
        self.assertIn(b'FDE browser is offline',page)
        self.assertIn(b'Fill FDE form automatically',page)

    def test_packing_confirmation_submits_once_without_second_approval(self):
        data={'waybill_number':'17778579','weight_kg':'2'}
        self.assertEqual(self.post('/orders/1/confirm-packing',data).status_code,302)
        self.assertEqual(self.post('/orders/1/confirm-packing',data).status_code,409)
        self.assertEqual(jobs.claim(self.conn),1)
        browser=Mock()
        jobs.prepare_one(self.conn,1,browser)
        self.assertFalse(jobs.submit_packed(self.conn,1,browser,False))
        browser.submit.assert_not_called()
        self.assertTrue(jobs.submit_packed(self.conn,1,browser,True))
        self.assertFalse(jobs.submit_packed(self.conn,1,browser,True))
        browser.submit.assert_called_once()
        self.assertEqual(jobs.snapshot(self.conn,1)['state'],'needs_review')

    def test_fresh_success_receipt_completes_booking(self):
        self.post('/orders/1/confirm-packing',{'waybill_number':'17778579','weight_kg':'2'})
        jobs.claim(self.conn)
        browser=Mock()
        browser.submit.return_value=True
        jobs.prepare_one(self.conn,1,browser)
        jobs.submit_packed(self.conn,1,browser,True)
        self.assertEqual(jobs.snapshot(self.conn,1)['state'],'succeeded')
        self.assertEqual(self.conn.execute('SELECT tracking FROM orders WHERE id=1').fetchone()[0],'17778579')
        browser.submit.assert_called_once()

    def test_preparation_only_never_gains_packing_authorization(self):
        browser=self.prepared()
        self.assertFalse(jobs.submit_packed(self.conn,1,browser,True))
        browser.submit.assert_not_called()

    def test_reservation_uniqueness_and_underweight(self):
        self.assertEqual(self.post('/orders/1/prepare',{'waybill_number':'17778578','weight_kg':'1'}).status_code,400)
        self.queue('CCP0017778578')
        self.assertEqual(jobs.snapshot(self.conn,1)['assigned_waybill'],'0017778578')
        self.assertEqual(self.post('/orders/2/prepare',{'waybill_number':'0017778578','weight_kg':'2'}).status_code,409)
        self.assertEqual(self.post('/orders/1/prepare',{'waybill_number':'22222222','weight_kg':'2'}).status_code,409)
        self.assertEqual(jobs.claim(self.conn),1)
        self.assertIsNone(jobs.claim(self.conn))

    def test_prepare_never_confirms_booking(self):
        self.prepared()
        self.assertEqual(jobs.snapshot(self.conn,1)['state'],'prepared')
        self.assertIsNone(self.conn.execute('SELECT tracking FROM orders WHERE id=1').fetchone()[0])
        self.assertEqual(self.post('/orders/1/approve-submit',{'reviewed':'yes'}).status_code,409)
        self.assertEqual(self.post('/orders/1/pack').status_code,409)

    def test_submit_timeout_is_not_retried(self):
        browser = self.prepared()
        self.app.config['ENABLE_LIVE_BOOKING']=True
        jobs.heartbeat(self.conn,True)
        self.assertEqual(self.post('/orders/1/approve-submit').status_code,400)
        self.assertEqual(self.post('/orders/1/approve-submit',{'reviewed':'yes'}).status_code,302)
        self.assertEqual(self.post('/orders/1/approve-submit',{'reviewed':'yes'}).status_code,409)
        def timeout_after_click():
            self.assertEqual(jobs.snapshot(self.conn,1)['state'],'submitting')
            raise TimeoutError('may already exist')
        browser.submit.side_effect=timeout_after_click
        jobs.submit_one(self.conn,1,browser,True)
        self.assertEqual(jobs.snapshot(self.conn,1)['state'],'needs_review')
        self.assertIsNone(jobs.claim(self.conn))
        with self.assertRaises(jobs.Conflict):
            jobs.submit_one(self.conn,1,browser,True)
        browser.submit.assert_called_once()
        self.assertEqual(self.post('/orders/1/retry-prepare').status_code,400)

    def test_success_click_still_requires_record_confirmation(self):
        browser=self.prepared()
        jobs.transition(self.conn,1,'prepared','approved','test approval')
        jobs.submit_one(self.conn,1,browser,True)
        self.assertEqual(jobs.snapshot(self.conn,1)['state'],'needs_review')
        self.assertEqual(self.post('/orders/1/booking',{'record_checked':'yes','tracking':'99999999'}).status_code,409)
        self.assertEqual(self.post('/orders/1/booking',{'record_checked':'yes','tracking':'CCP0017778578'}).status_code,302)
        self.assertEqual(jobs.snapshot(self.conn,1)['state'],'succeeded')

    def test_restart_does_not_requeue_uncertain_work(self):
        self.prepared()
        jobs.recover_interrupted(self.conn)
        self.assertEqual(jobs.snapshot(self.conn,1)['state'],'needs_review')
        self.assertIsNone(jobs.claim(self.conn))
        self.assertEqual(self.post('/orders/1/retry-prepare',{'not_created':'yes'}).status_code,302)
        self.assertEqual(jobs.claim(self.conn),1)

    def test_preparation_failure_redacts_raw_error(self):
        self.queue()
        jobs.claim(self.conn)
        browser=Mock()
        browser.prepare.side_effect=RuntimeError('PRIVATE CUSTOMER AND COOKIE')
        self.assertFalse(jobs.prepare_one(self.conn,1,browser))
        row=jobs.snapshot(self.conn,1)
        self.assertEqual(row['state'],'blocked')
        self.assertNotIn('PRIVATE',row['message'])
        browser.submit.assert_not_called()

    def test_expired_login_pauses_before_any_submit(self):
        self.queue()
        jobs.claim(self.conn)
        browser=Mock()
        browser.prepare.side_effect=SignInRequired('login required')
        self.assertFalse(jobs.prepare_one(self.conn,1,browser))
        self.assertEqual(jobs.snapshot(self.conn,1)['state'],'login_required')
        self.assertIsNone(jobs.claim(self.conn))
        jobs.recover_interrupted(self.conn)
        self.assertEqual(jobs.snapshot(self.conn,1)['state'],'login_required')
        browser.submit.assert_not_called()

    def test_booked_tracking_cannot_be_reserved_with_prefix_alias(self):
        self.post('/orders/1/booking',{'record_checked':'yes','tracking':'CCP17778578'})
        self.assertEqual(self.post('/orders/2/prepare',{'waybill_number':'17778578','weight_kg':'2'}).status_code,409)

    def test_packing_gets_orders_before_booking_but_cannot_submit(self):
        self.assertIn(b'Confirm packing &amp;',self.client.get('/packing').data.replace(b' & ',b' &amp; '))
        self.app.config.update(ADMIN_PASSWORD='admin',PACKER_PASSWORD='packer')
        self.post('/login',{'role':'packer','password':'packer'})
        with self.client.session_transaction() as session:
            self.csrf=session['csrf']
        self.queue()
        self.assertEqual(self.client.get('/courier').status_code,403)
        self.assertEqual(self.post('/orders/1/approve-submit',{'reviewed':'yes'}).status_code,403)

    def test_existing_database_migration_is_idempotent(self):
        with sqlite3.connect(':memory:') as old:
            old.executescript(SCHEMA)
            old.execute("INSERT INTO leads(name,phone) VALUES('Existing','0771234567')")
            old.execute('INSERT INTO orders(lead_id) VALUES(1)')
            old.execute("INSERT INTO booking_jobs(order_id,reference) VALUES(1,'PP3D-000001')")
            jobs.migrate(old)
            jobs.migrate(old)
            self.assertEqual(old.execute('SELECT name FROM leads').fetchone()[0],'Existing')
            self.assertEqual(old.execute('SELECT state FROM booking_jobs').fetchone()[0],'pending')

    def test_status_screens_render_and_submit_control_stays_off(self):
        self.queue()
        for state in jobs.STATE_LABELS:
            with self.conn:
                self.conn.execute('UPDATE booking_jobs SET state=? WHERE order_id=1',(state,))
            for path in ('/courier','/orders/1','/packing'):
                response=self.client.get(path)
                self.assertEqual(response.status_code,200,(state,path))
                self.assertNotIn(b'Submit this booking once',response.data)


class AdapterTests(unittest.TestCase):
    def test_mapping_keeps_money_and_phone(self):
        values=field_values(dict(quantity=2,product='Blue keytag',reference='PP3D-000001',cod_cents=199950,
                                 name='Test',phone='0771234567',address='Test only',city='Colombo'))
        self.assertEqual(values['#amount'],'1999.50')
        self.assertEqual(values['#rContact1'],'0771234567')
        self.assertEqual(values['#pDesc'],'2 x Blue keytag')

    def test_redirect_to_login_blocks_filling(self):
        page=Mock(url='https://www.fdedomestic.com/client/signIn.php')
        adapter=FDEBrowser(page)
        with self.assertRaises(FormMismatch):
            adapter.prepare({'assigned_waybill':'17778578'})
        page.locator.assert_not_called()

    def test_submit_waits_for_observed_success_and_rejects_stale_receipt(self):
        page=Mock(url='https://www.fdedomestic.com/client/ccp_parcel_add.php')
        page.get_by_text.return_value.is_visible.return_value=False
        adapter=FDEBrowser(page)
        self.assertTrue(adapter.submit())
        page.locator.return_value.click.assert_called_once()
        page.get_by_text.return_value.wait_for.assert_called_once_with(state='visible',timeout=30000)
        page.get_by_text.return_value.is_visible.return_value=True
        with self.assertRaises(FormMismatch):
            adapter.submit()
        page.locator.return_value.click.assert_called_once()

    def test_city_capitalization_does_not_reject_exact_destination(self):
        page=Mock(url='https://www.fdedomestic.com/client/ccp_parcel_add.php')
        adapter=FDEBrowser(page)
        adapter.form_identity=Mock()
        adapter.city_id=''
        job=dict(quantity=1,product='Print',reference='PP3D-1',cod_cents=100,name='Test',phone='0771234567',address='Test',city='colombo 06',weight_kg=1)
        values=field_values(job)
        values.update({'#Rrcity':'Colombo 06','#RselectCityId':'','#ccpSecFrm select[name="weight"]':'1'})
        def locator(selector):
            result=Mock()
            result.input_value.return_value=values.get(selector,'')
            result.is_checked.return_value=False
            return result
        page.locator.side_effect=locator
        adapter.verify(job)
        values['#Rrcity']='Colombo 06 - Wellawatte & Pamankada'
        with self.assertRaises(FormMismatch):
            adapter.verify(job)

    def test_modified_or_unresolved_city_blocks_submit(self):
        page=Mock(url='https://www.fdedomestic.com/client/ccp_parcel_add.php')
        adapter=FDEBrowser(page)
        adapter.form_identity=Mock()
        job=dict(quantity=1,product='Print',reference='PP3D-1',cod_cents=100,name='Test',phone='0771234567',address='Test',city='Colombo',weight_kg=1)
        values=field_values(job)
        values['#ccpSecFrm select[name="weight"]']='1'
        values['#RselectCityId']=''
        def locator(selector):
            result=Mock()
            result.input_value.return_value=values.get(selector,'')
            result.is_checked.return_value=False
            return result
        page.locator.side_effect=locator
        with self.assertRaises(FormMismatch):
            adapter.verify(job)


if __name__ == '__main__':
    unittest.main()
