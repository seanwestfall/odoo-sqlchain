"""Provider timeout classification at the real adapter process boundary; no network."""
import subprocess,sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'chainsql/arc'))
from controller import NodeProvider,BoundaryError
sys.path.insert(0,str(ROOT/'chainsql/documents'))
from seller import Provider
from core import Denied
class Bounds(unittest.TestCase):
 def test_arc_timeout_fails_closed_without_retry(self):
  with patch('subprocess.run',side_effect=subprocess.TimeoutExpired('fixture',90)) as run:
   with self.assertRaises(BoundaryError):NodeProvider('node','fixture','private.env')('submit',{})
   self.assertEqual(run.call_count,1);self.assertEqual(run.call_args.kwargs['timeout'],90)
 def test_seller_timeout_leaves_reconciliation_to_caller(self):
  with patch('subprocess.run',side_effect=subprocess.TimeoutExpired('fixture',65)) as run:
   with self.assertRaises(Denied):Provider('fixture').call('settle')
   self.assertEqual(run.call_count,1);self.assertEqual(run.call_args.kwargs['timeout'],65)
if __name__=='__main__':unittest.main()
