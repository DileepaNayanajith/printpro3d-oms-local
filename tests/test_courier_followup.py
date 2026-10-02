import time
from tests import test_remote
from oms import courier_followup


class CourierFollowupTests(test_remote.RemoteTests):
    def report(self, rows=None, total=None):
        task=self.post('poll',{'kind':'reports','ready':True}).json['task']
        if not task:
            from oms import fde_reports
            fde_reports.request_sync(self.c)
            task=self.post('poll',{'kind':'reports','ready':True}).json['task']
        self.post(task['id']+'/start')
        rows=rows if rows is not None else {'12345678':'PP3D-000001'}
        response=self.post(task['id']+'/result',{'outcome':'success','reports':{'rescheduled':{'total':len(rows) if total is None else total,'rows':rows}}})
        self.assertEqual(response.status_code,200)

    def tracked(self):
        with self.c:self.c.execute("UPDATE orders SET tracking='CCP12345678',status='dispatched' WHERE id=1")

    def test_followup_deduplicates_and_uses_existing_station(self):
        self.tracked();self.report();self.report()
        self.assertEqual(self.c.execute('SELECT count(*) FROM courier_followups').fetchone()[0],1)
        task=self.post('poll',{'kind':'confirmation','ready':True}).json['task']
        self.assertEqual(task['payload']['include_photo'],0)
        self.assertIn('rescheduled',task['payload']['body'])
        self.assertEqual(self.post(task['id']+'/start').status_code,200)
        self.post(task['id']+'/result',{'outcome':'success'})
        self.report()
        self.assertIsNone(self.post('poll',{'kind':'confirmation','ready':True}).json['task'])

    def test_partial_and_unknown_orders_do_not_message(self):
        self.tracked();self.report(total=2)
        self.assertEqual(self.c.execute('SELECT count(*) FROM courier_followups').fetchone()[0],0)
        self.report({'87654321':''})
        self.assertEqual(len(courier_followup.rows(self.c)),1)
        self.assertEqual(self.c.execute('SELECT count(*) FROM courier_followups').fetchone()[0],0)

    def test_cleared_status_cancels_queued_message(self):
        self.tracked();self.report();self.report({})
        self.assertIsNone(self.post('poll',{'kind':'confirmation','ready':True}).json['task'])
        self.assertEqual(self.c.execute('SELECT state FROM whatsapp_confirmations').fetchone()[0],'cancelled')

    def test_status_change_after_prepare_prevents_send(self):
        self.tracked();self.report()
        task=self.post('poll',{'kind':'confirmation','ready':True}).json['task']
        with self.c:self.c.execute("UPDATE fde_observations SET status='delivered'")
        self.assertEqual(self.post(task['id']+'/start').status_code,409)

    def test_stale_report_cannot_send(self):
        self.tracked();self.report()
        with self.c:self.c.execute('UPDATE fde_observations SET observed_at=?',(int(time.time())-901,))
        self.assertIsNone(self.post('poll',{'kind':'confirmation','ready':True}).json['task'])

    def test_dashboard_renders_and_contact_mark_keeps_message(self):
        self.tracked();self.report();self.app.config['CLOUD_MODE']=False
        response=self.client.get('/dashboard')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'Customers to call back',response.data)
        self.assertIn(b'tel:0771234567',response.data)
        self.assertEqual(self.client.post('/dashboard/callbacks/1/contacted',data={'csrf':self.csrf}).status_code,302)
        self.assertIsNotNone(self.c.execute('SELECT contacted_at FROM courier_followups').fetchone()[0])

    def test_scheduled_refresh_has_cooldown(self):
        self.report({})
        self.assertIsNone(self.post('poll',{'kind':'reports','ready':True}).json['task'])
        with self.c:self.c.execute('UPDATE fde_report_sync SET finished_at=0,requested_at=0')
        self.assertIsNotNone(self.post('poll',{'kind':'reports','ready':True}).json['task'])
