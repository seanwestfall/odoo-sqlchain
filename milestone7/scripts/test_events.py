import tempfile,unittest
from pathlib import Path
from events import record,counts
class Events(unittest.TestCase):
 def test_identity_and_dataset_isolation(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'events.sqlite'
   self.assertTrue(record(p,'event-1','synthetic','testdb','duplicate_suppressed'))
   self.assertFalse(record(p,'event-1','synthetic','testdb','duplicate_suppressed'))
   with self.assertRaises(ValueError):record(p,'event-1','testnet-pilot','testdb','human_intervention')
   self.assertEqual(counts(p,'synthetic','testdb'),{'duplicate_suppressed':1})
   self.assertEqual(counts(p,'testnet-pilot','testdb'),{})
   self.assertEqual(p.stat().st_mode & 0o777,0o600)
if __name__=='__main__':unittest.main()
