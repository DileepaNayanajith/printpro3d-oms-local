import io
import sqlite3
import tempfile
import unittest
from oms import create_app

class Workflow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app({'TESTING':True,'DATABASE':self.temp.name+'/test.sqlite3','SECRET_KEY':'test','ADMIN_PASSWORD':None})
        self.app.instance_path = self.temp.name
        self.client = self.app.test_client()
        self.client.get('/')
        with self.client.session_transaction() as s:
            self.csrf = s['csrf']
        self.data = dict(name='Test customer',phone='+94771234567',address='Test address',city='Colombo',product='Sample print',quantity='2',cod='1250.50',weight_g='300')

    def tearDown(self):
        self.temp.cleanup()

    def post(self,url,data=None):
        return self.client.post(url,data=dict(csrf=self.csrf,**(data or {})))

    def qualify(self):
        self.assertEqual(self.post('/leads',self.data).status_code,302)
        self.assertEqual(self.post('/leads/1',dict(self.data,action='qualify')).status_code,302)

    def test_full_flow_and_double_submit(self):
        self.qualify()
        self.post('/leads/1',dict(self.data,action='qualify'))
        with sqlite3.connect(self.app.config['DATABASE']) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM orders').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM booking_jobs').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT phone,cod_cents FROM leads').fetchone(),('0771234567',125050))
        self.assertEqual(self.post('/orders/1/pack').status_code,409)
        self.assertEqual(self.post('/orders/1/booking',{'tracking':'TEST-1234'}).status_code,302)
        self.assertEqual(self.post('/orders/1/booking',{'tracking':'TEST-1234'}).status_code,409)
        self.assertEqual(self.post('/orders/1/pack').status_code,409)
        self.assertEqual(self.post('/orders/1/waybill',{'waybill':(io.BytesIO(b'%PDF-1.4\n fixture'),'label.pdf')}).status_code,302)
        response = self.client.get('/orders/1/waybill')
        self.assertEqual(response.status_code,200)
        response.close()
        self.assertEqual(self.post('/orders/1/pack').status_code,302)
        self.assertIn(b'packed',self.client.get('/packing').data)
        self.assertIn(b'1250.50',self.client.get('/orders.csv').data)

    def test_invalid_data(self):
        self.assertEqual(self.post('/leads',dict(self.data,cod='NaN')).status_code,400)
        self.assertEqual(self.post('/leads',dict(self.data,phone='abc')).status_code,400)
        self.post('/leads',self.data)
        self.assertEqual(self.post('/leads/1',dict(self.data,action='qualify',address='')).status_code,400)
        with sqlite3.connect(self.app.config['DATABASE']) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM orders').fetchone()[0],0)

    def test_csrf_and_host(self):
        self.assertEqual(self.client.post('/leads',data=self.data).status_code,400)
        self.assertEqual(self.client.get('/',headers={'Host':'attacker.example'}).status_code,403)

    def test_packer_permissions(self):
        self.qualify()
        self.app.config.update(ADMIN_PASSWORD='admin-test',PACKER_PASSWORD='pack-test')
        self.assertEqual(self.client.get('/').status_code,302)
        self.post('/login',{'role':'packer','password':'pack-test'})
        with self.client.session_transaction() as s:
            self.csrf=s['csrf']
        self.assertEqual(self.client.get('/packing').status_code,200)
        for path in ('/','/orders.csv','/orders/1','/leads/1'):
            self.assertEqual(self.client.get(path).status_code,403)
        self.assertEqual(self.post('/orders/1/booking',{'tracking':'TEST-1234'}).status_code,403)

    def test_unique_tracking_csv_escaping(self):
        self.qualify()
        self.post('/leads',dict(self.data,name='=DANGEROUS()'))
        self.post('/leads/2',dict(self.data,name='=DANGEROUS()',action='qualify'))
        self.post('/orders/1/booking',{'tracking':'TEST-1234'})
        self.assertEqual(self.post('/orders/2/booking',{'tracking':'TEST-1234'}).status_code,409)
        self.assertIn(b"'=DANGEROUS()",self.client.get('/orders.csv').data)
