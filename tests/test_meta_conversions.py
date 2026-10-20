import json
import sqlite3
import tempfile
import time
import unittest
from oms import create_app, meta_conversions as meta

class MetaPurchaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.app=create_app({'TESTING':True,'DATABASE':self.tmp.name+'/test.db','WEBSITE_TOKEN':'test-token'})
        self.client=self.app.test_client()
        self.headers={'Authorization':'Bearer test-token'}
        self.attr=dict(consent=True,fbp='fb.1.1792490000000.123456',fbc='fb.1.1792490000000.real-click',contents=[dict(id='P3D-HW-RACK-10',quantity=3,item_price=1750)],shipping=400,phone='DO-NOT-SEND')
        self.payload=dict(request_id='a'*24,name='Private Customer',phone='0771234567',address='Private Street',city='Colombo',product='3 racks',quantity=3,total_cents=565000,payment='cod',meta_attribution=self.attr)
    def tearDown(self):self.tmp.cleanup()
    def db(self):
        c=sqlite3.connect(self.app.config['DATABASE']);c.row_factory=sqlite3.Row;return c
    def intake(self,**extra):
        r=self.client.post('/api/website/orders',json=dict(self.payload,**extra),headers=self.headers)
        self.assertEqual(r.status_code,201);return int(r.json['reference'].split('-')[1])
    def qualify(self,lead_id,payment_verified=0):
        with self.db() as c:
            c.execute("UPDATE leads SET status='qualified' WHERE id=?",(lead_id,))
            c.execute('UPDATE website_orders SET payment_verified=? WHERE lead_id=?',(payment_verified,lead_id))
            oid=c.execute('INSERT INTO orders(lead_id) VALUES(?)',(lead_id,)).lastrowid
            meta.enqueue(c,oid);return oid
    def test_submission_is_not_purchase_and_confirmation_is_durable(self):
        lid=self.intake()
        with self.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM meta_purchase_outbox').fetchone()[0],0)
        oid=self.qualify(lid)
        with self.db() as c:
            meta.enqueue(c,oid)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM meta_purchase_outbox').fetchone()[0],1)
        with self.db() as c:
            events=[]
            self.assertEqual(meta.deliver(c,'token',lambda event,_token: events.append(event) or {'events_received':1}),1)
            self.assertEqual(meta.deliver(c,'token',lambda *_:self.fail('duplicate send')),0)
            event=events[0];self.assertEqual(event['event_id'],f'purchase-PP3D-{oid:06d}')
            self.assertEqual(event['custom_data']['value'],5250);self.assertEqual(event['custom_data']['currency'],'LKR')
            self.assertNotIn('Private',json.dumps(event));self.assertNotIn('0771234567',json.dumps(event));self.assertNotIn('DO-NOT-SEND',json.dumps(event))
            self.assertEqual(c.execute('SELECT payload FROM meta_purchase_outbox').fetchone()[0],'{}')
    def test_declined_consent_or_missing_identifiers_never_queues(self):
        self.qualify(self.intake(meta_attribution=dict(self.attr,consent=False)))
        with self.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM meta_purchase_outbox').fetchone()[0],0)
    def test_unpaid_bank_and_changed_cod_totals_do_not_queue(self):
        lid=self.intake(payment='bank',total_cents=525000,meta_attribution=dict(self.attr,shipping=0))
        oid=self.qualify(lid)
        with self.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM meta_purchase_outbox').fetchone()[0],0)
            c.execute('UPDATE website_orders SET payment_verified=1 WHERE lead_id=?',(lid,));meta.enqueue(c,oid)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM meta_purchase_outbox').fetchone()[0],1)
    def test_retry_preserves_id_and_recovers_after_restart(self):
        oid=self.qualify(self.intake());now=int(time.time())
        with self.db() as c:
            self.assertEqual(meta.deliver(c,'token',lambda *_: (_ for _ in ()).throw(ValueError('network')),now),0)
            row=c.execute('SELECT * FROM meta_purchase_outbox').fetchone();self.assertEqual(row['attempts'],1)
            due=row['next_attempt'];self.assertGreater(due,now)
        with self.db() as c:
            sent=[];self.assertEqual(meta.deliver(c,'token',lambda e,_:sent.append(e) or {'events_received':1},due),1)
            self.assertEqual(sent[0]['event_id'],f'purchase-PP3D-{oid:06d}')
    def test_withdrawal_cancels_pending_server_event(self):
        self.qualify(self.intake())
        r=self.client.post('/api/website/meta/withdraw',json={'request_ids':['a'*24]},headers=self.headers)
        self.assertEqual(r.status_code,200)
        with self.db() as c:
            self.assertEqual(meta.deliver(c,'token',lambda *_:self.fail('withdrawn event sent')),0)
            self.assertEqual(c.execute('SELECT state FROM meta_purchase_outbox').fetchone()[0],'withdrawn')
    def test_cancelled_order_does_not_send(self):
        oid=self.qualify(self.intake())
        with self.db() as c:
            c.execute("UPDATE orders SET status='cancelled' WHERE id=?",(oid,))
        with self.db() as c:self.assertEqual(meta.deliver(c,'token',lambda *_:self.fail('cancelled event sent')),0)
    def test_order_retry_ignores_changed_optional_tracking(self):
        self.intake()
        r=self.client.post('/api/website/orders',json=dict(self.payload,meta_attribution=None),headers=self.headers)
        self.assertEqual(r.status_code,200)
    def test_actual_qualification_route_enqueues(self):
        lid=self.intake()
        self.client.get(f'/leads/{lid}')
        with self.client.session_transaction() as session: csrf=session['csrf']
        r=self.client.post(f'/leads/{lid}',data=dict(csrf=csrf,action='qualify',name='Private Customer',phone='0771234567',address='Private Street',city='Colombo',product='3 racks',quantity='3',cod='5650',weight_g='500',notes=''))
        self.assertIn(r.status_code,(302,303))
        with self.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM meta_purchase_outbox').fetchone()[0],1)
