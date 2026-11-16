import unittest
from unittest.mock import patch
from pathlib import Path
from home_worker import printer_command
class MacPrintTests(unittest.TestCase):
 def test_mac_a4_landscape_without_sumatra(self):
  with patch('home_worker.sys.platform','darwin'):
   command=printer_command({'printer':'HP LaserJet'},Path('/tmp/labels with spaces.pdf'))
  self.assertEqual(command[:3],['/usr/bin/lp','-d','HP LaserJet'])
  self.assertIn('orientation-requested=4',command)
  self.assertIn('media=A4',command)
  self.assertEqual(command[-1],'/tmp/labels with spaces.pdf')
 def test_missing_printer_rejected(self):
  with patch('home_worker.sys.platform','darwin'):
   with self.assertRaises(ValueError):printer_command({},Path('/tmp/labels.pdf'))
