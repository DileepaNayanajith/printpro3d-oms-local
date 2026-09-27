import sqlite3
import tempfile
import unittest
from unittest.mock import Mock
from oms import create_app, automation, whatsapp


class WhatsAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        app = create_app({'TESTING': True, 'DATABASE': self.tmp.name + '/test.db'})
        self.c = sqlite3.connect(app.config['DATABASE'])
        self.c.row_factory = sqlite3.Row
        with self.c:
            self.c.execute("INSERT INTO leads(name,phone) VALUES('Customer','0771234567')")
            self.c.execute('INSERT INTO orders(lead_id) VALUES(1)')
            self.c.execute("INSERT INTO booking_jobs(order_id,reference) VALUES(1,'PP3D-000001')")

    def tearDown(self):
        self.c.close()
        self.tmp.cleanup()

    def book(self):
        automation.confirm_booking(self.c, 1, '17779999', 'test')

    def test_queue_only_after_confirmed_booking_and_unique(self):
        whatsapp.queue(self.c, 1)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM whatsapp_outbox').fetchone()[0], 0)
        self.book()
        whatsapp.queue(self.c, 1)
        row = self.c.execute('SELECT * FROM whatsapp_outbox').fetchone()
        self.assertEqual(row['phone'], '94771234567')
        self.assertIn('17779999', row['body'])
        self.assertIn('https://www.fdedomestic.com', row['body'])
        self.assertNotIn('dispatched', row['body'])
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM whatsapp_outbox').fetchone()[0], 1)

    def test_failed_booking_does_not_queue(self):
        with self.c:
            self.c.execute("UPDATE booking_jobs SET state='submitting'")
        with self.assertRaises(automation.Conflict):
            self.book()
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM whatsapp_outbox').fetchone()[0], 0)

    def test_uncertain_send_not_retried(self):
        self.book()
        browser = Mock()
        browser.send.side_effect = TimeoutError()
        self.assertTrue(whatsapp.send_one(self.c, browser))
        self.assertFalse(whatsapp.send_one(self.c, browser))
        browser.send.assert_called_once()
        self.assertEqual(self.c.execute('SELECT state FROM whatsapp_outbox').fetchone()[0], 'needs_review')

    def test_prepare_failure_can_resume_without_sending(self):
        self.book()
        browser = Mock()
        browser.prepare.side_effect = RuntimeError('Login required')
        with self.assertRaises(RuntimeError):
            whatsapp.send_one(self.c, browser)
        browser.send.assert_not_called()
        self.assertEqual(self.c.execute('SELECT state FROM whatsapp_outbox').fetchone()[0], 'queued')

    def test_recover_and_invalid_number(self):
        with self.c:
            self.c.execute("UPDATE leads SET phone='0112345678'")
        self.book()
        self.assertEqual(self.c.execute('SELECT state FROM whatsapp_outbox').fetchone()[0], 'invalid_phone')
        with self.c:
            self.c.execute("UPDATE whatsapp_outbox SET state='sending'")
        whatsapp.recover(self.c)
        self.assertEqual(self.c.execute('SELECT state FROM whatsapp_outbox').fetchone()[0], 'needs_review')

    def test_success_claimed_before_browser_send(self):
        self.book()
        browser = Mock()
        def sent(*args):
            self.assertEqual(self.c.execute('SELECT state FROM whatsapp_outbox').fetchone()[0], 'sending')
        browser.send.side_effect = sent
        self.assertTrue(whatsapp.send_one(self.c, browser))
        self.assertFalse(whatsapp.send_one(self.c, browser))
        self.assertEqual(self.c.execute('SELECT state FROM whatsapp_outbox').fetchone()[0], 'sent')

    def test_trigger_catches_existing_worker_and_skips_old_bookings(self):
        with self.c:
            self.c.execute("UPDATE orders SET tracking='17778888',status='booked'")
            self.c.execute("UPDATE booking_jobs SET state='succeeded'")
        whatsapp.ingest(self.c)
        whatsapp.ingest(self.c)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM whatsapp_outbox').fetchone()[0], 1)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM whatsapp_booking_events').fetchone()[0], 0)

    def test_old_messages_are_not_sent_after_long_outage(self):
        self.book()
        with self.c:
            self.c.execute('UPDATE whatsapp_outbox SET created_at=0')
        browser = Mock()
        self.assertTrue(whatsapp.send_one(self.c, browser))
        browser.prepare.assert_not_called()
        browser.send.assert_not_called()
        self.assertEqual(self.c.execute('SELECT state FROM whatsapp_outbox').fetchone()[0], 'stale')

    def test_migration_does_not_backfill_old_bookings(self):
        with self.c:
            self.c.execute('DROP TRIGGER whatsapp_booking_confirmed')
            self.c.execute("UPDATE orders SET tracking='17778888',status='booked'")
            self.c.execute("UPDATE booking_jobs SET state='succeeded'")
        whatsapp.migrate(self.c)
        whatsapp.ingest(self.c)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM whatsapp_outbox').fetchone()[0], 0)
