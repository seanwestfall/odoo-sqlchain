"""Kill a child after durable dispatch claim; prove restart cannot dispatch again."""
import json,os,signal,subprocess,sys,tempfile,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'chainsql/documents'))
from core import Vault
class Recovery(unittest.TestCase):
 def test_sigkill_after_dispatch(self):
  with tempfile.TemporaryDirectory() as d:
   v=Vault(d,b'x'*32);identity=v.publish('synthetic','fixture','1',b'sample',int(time.time())+3600,'test','10000','0x'+'22'*20)
   v.buyer('buyer','0x'+'11'*20);v.prepare('fixed-payment',identity,'buyer',{'fixture':'not a payable authorization'},'1');v.close()
   code="import sys,time;sys.path.insert(0,sys.argv[1]);from core import Vault;v=Vault(sys.argv[2],b'x'*32);assert v.claim_dispatch('fixed-payment');print('durable',flush=True);time.sleep(60)"
   child=subprocess.Popen([sys.executable,'-c',code,str(ROOT/'chainsql/documents'),d],stdout=subprocess.PIPE,text=True)
   try:
    import select
    self.assertTrue(select.select([child.stdout],[],[],10)[0]);self.assertEqual(child.stdout.readline().strip(),'durable')
    child.kill();child.wait(timeout=10)
   finally:
    if child.poll() is None:child.kill();child.wait()
    child.stdout.close()
   restored=Vault(d,b'x'*32)
   self.assertEqual(restored.order('fixed-payment')['state'],'uncertain')
   self.assertFalse(restored.claim_dispatch('fixed-payment'))
   self.assertEqual(restored.order('fixed-payment')['from_block'],'1');restored.close()
if __name__=='__main__':unittest.main()
