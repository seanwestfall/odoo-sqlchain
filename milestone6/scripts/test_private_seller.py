import base64,hashlib,json,os,sys,tempfile,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'chainsql/documents'))
from core import Vault,Denied,Conflict,proof
from seller import Seller,header

class FakeProvider:
    """Synthetic settlement ledger; no chain, keys or real payment."""
    def __init__(self):self.settles=0;self.paid=False;self.lose=False;self.offline=False
    def call(self,op,**v):
        p=v.get('payload',{})
        if op=='validate':
            if p['resource']!=v['resource'] or p['accepted']!=v['requirements'] or p['payload']['authorization']['from'].lower()!=v['wallet']:raise Denied('Invalid')
            return {'valid':True}
        if op=='verify':return {'block':'1'}
        if op=='observe':
            if self.offline:raise Denied('Unavailable')
            return {'transaction':'0x'+'ab'*32,'receipt_status':'success'} if self.paid else {}
        if op=='settle':
            self.settles+=1;self.paid=True
            if self.lose:raise Denied('Lost response')
            return {'success':True}

class PrivateSeller(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.key=os.urandom(32);self.v=Vault(self.tmp.name,self.key)
        self.data=b'SAMPLE PRIVATE CERTIFICATE\x00\r\nnot a true business statement'
        self.until=int(time.time())+3600
        self.id=self.v.publish('company-1','attachment:1','v1',self.data,self.until,'approved:operator','10000','0x'+'22'*20)
        self.wallet='0x'+'11'*20;self.token=self.v.buyer('buyer-a',self.wallet);self.v.grant(self.id,'buyer-a',self.until)
        self.provider=FakeProvider();self.s=Seller(self.v,self.provider)
        code,h,_=self.s.handle(self.id,self.token);self.challenge=json.loads(base64.b64decode(h['PAYMENT-REQUIRED']))
        self.p=dict(x402Version=2,resource=self.challenge['resource'],accepted=self.challenge['accepts'][0],payload={'signature':'TEST-ONLY-NOT-A-SIGNATURE','authorization':{'from':self.wallet,'to':'0x'+'22'*20,'value':'10000','validAfter':str(int(time.time())-5),'validBefore':str(self.until),'nonce':'0x'+'33'*32}})
    def tearDown(self):self.v.close();self.tmp.cleanup()
    def buy(self):return self.s.handle(self.id,self.token,header(self.p))
    def test_expired_prepared_authorization_is_not_dispatched(self):
        self.p['payload']['authorization']['validBefore']=str(int(time.time())-1)
        self.assertEqual(self.buy()[0],202)
        self.assertEqual(self.provider.settles,0)
    def test_exact_bytes(self):
        m=self.v.manifest(self.id);salt=bytes.fromhex(m['salt']);self.assertTrue(proof.verify(self.data,m['sha256'],salt,m['commitment']));self.assertFalse(proof.verify(self.data+b' ',m['sha256'],salt,m['commitment']))
    def test_salt_hides_predictable_commitment(self):self.assertNotEqual(proof.commitment(self.data,b'a'*32),proof.commitment(self.data,b'b'*32))
    def test_encrypted_at_rest(self):
        self.assertNotIn(self.data,self.v.version(self.id)['blob'])
        with self.assertRaises(Exception):proof.unseal(b'x'*32,self.v.version(self.id)['blob'],self.id)
    def test_wrong_identity_aad(self):
        with self.assertRaises(Exception):proof.unseal(self.key,self.v.version(self.id)['blob'],'other-version')
    def test_unauthorized_cannot_pay_for_access(self):
        with self.assertRaises(Denied):self.s.handle(self.id,'attacker',header(self.p))
        self.assertEqual(self.provider.settles,0)
    def test_authentication_is_not_a_grant(self):
        token=self.v.buyer('not-granted',self.wallet)
        with self.assertRaises(Denied):self.s.handle(self.id,token,header(self.p))
        self.assertEqual(self.provider.settles,0)
    def test_wrong_wallet_rejected(self):
        self.p['payload']['authorization']['from']='0x'+'44'*20
        with self.assertRaises(Denied):self.buy()
    def test_402_is_v2(self):self.assertEqual(self.challenge['x402Version'],2);self.assertEqual(self.challenge['accepts'][0]['amount'],'10000')
    def test_delivery_and_replay(self):
        self.assertEqual(self.buy()[2],self.data);self.assertEqual(self.buy()[2],self.data);self.assertEqual(self.provider.settles,1)
    def test_lost_paid_response_survives_restart(self):
        self.provider.lose=True;self.assertEqual(self.buy()[0],202)
        self.v.close();self.v=Vault(self.tmp.name,self.key);self.s=Seller(self.v,self.provider)
        self.assertEqual(self.buy()[0],200);self.assertEqual(self.provider.settles,1)
    def test_uncertain_never_resettles(self):
        self.provider.lose=True;self.buy();self.provider.paid=False
        self.assertEqual(self.buy()[0],202);self.assertEqual(self.provider.settles,1)
    def test_revocation_blocks_paid_replay(self):
        self.buy();self.v.revoke(self.id,'buyer-a')
        with self.assertRaises(Denied):self.buy()
    def test_version_pinned_after_edit(self):
        self.buy();self.v.publish('company-1','attachment:1','v2',b'edited',self.until,'approved:operator','20000','0x'+'22'*20)
        self.assertEqual(self.buy()[2],self.data)
    def test_price_change_blocked(self):
        self.p['accepted']['amount']='1'
        with self.assertRaises(Denied):self.buy()
    def test_recipient_change_blocked(self):
        self.p['accepted']['payTo']='0x'+'44'*20
        with self.assertRaises(Denied):self.buy()
    def test_nonce_cannot_buy_second_version(self):
        self.buy();other=self.v.publish('company-1','attachment:1','v2',b'new',self.until,'operator','10000','0x'+'22'*20);self.v.grant(other,'buyer-a',self.until)
        self.p['resource']['url']='http://127.0.0.1:8096/resources/'+other
        with self.assertRaises(Conflict):self.s.handle(other,self.token,header(self.p))
    def test_changed_signature_not_replayed(self):
        self.buy();self.p['payload']['signature']='other'
        with self.assertRaises(Conflict):self.buy()
    def test_authorization_encrypted(self):
        self.buy();row=self.v.db.execute('SELECT payload FROM orders').fetchone();self.assertNotIn(b'TEST-ONLY',row[0])
    def test_retention_enforced(self):
        with self.assertRaises(Denied):self.v.purge(self.id)
        self.v.purge(self.id,now=self.until+1)
        with self.assertRaises(Denied):self.buy()
    def test_pending_prevents_purge(self):
        self.provider.lose=True;self.buy()
        with self.assertRaises(Denied):self.v.purge(self.id,now=self.until+1)
    def test_one_dispatch_claim_across_connections(self):
        self.v.prepare('key',self.id,'buyer-a',self.p,'1');second=Vault(self.tmp.name,self.key)
        try:self.assertTrue(self.v.claim_dispatch('key'));self.assertFalse(second.claim_dispatch('key'))
        finally:second.close()
    def test_unapproved_version_rejected(self):
        with self.assertRaises(Denied):self.v.publish('c','s','v',b'x',self.until,'','1','0x'+'22'*20)

    def test_observer_outage_stays_pending(self):
        self.provider.lose=True;self.buy();self.provider.offline=True
        self.assertEqual(self.buy()[0],202);self.assertEqual(self.provider.settles,1)
    def test_actual_http_auth_challenge_and_replay(self):
        import threading,queue,urllib.request,urllib.error
        from http.server import HTTPServer
        from seller import route_factory
        ready=queue.Queue()
        def serve():
            vault=Vault(self.tmp.name,self.key)
            server=HTTPServer(('127.0.0.1',0),route_factory(Seller(vault,self.provider)))
            ready.put(server.server_port)
            for _ in range(4):server.handle_request()
            server.server_close();vault.close()
        t=threading.Thread(target=serve,daemon=True);t.start();port=ready.get(timeout=5)
        url=f'http://127.0.0.1:{port}/resources/{self.id}'
        def get(headers):
            try:return urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=5)
            except urllib.error.HTTPError as e:return e
        with get({}) as r:self.assertEqual(r.status,404)
        with get({'Authorization':'Bearer '+self.token}) as r:self.assertEqual(r.status,402);self.assertIn('PAYMENT-REQUIRED',r.headers)
        headers={'Authorization':'Bearer '+self.token,'PAYMENT-SIGNATURE':header(self.p)}
        with get(headers) as r:self.assertEqual(r.status,200);self.assertEqual(r.read(),self.data)
        with get(headers) as r:self.assertEqual(r.status,200);self.assertEqual(r.read(),self.data)
        t.join(timeout=5);self.assertFalse(t.is_alive());self.assertEqual(self.provider.settles,1)

if __name__=='__main__':unittest.main(verbosity=2)
