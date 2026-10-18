"""Disposable native database integration tests. No live signing or settlement."""
from pathlib import Path
import sys,json,uuid,subprocess,concurrent.futures,copy,tempfile,base64
from datetime import datetime,timedelta,timezone
from contextlib import closing
import psycopg2
from psycopg2.extras import Json
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'chainsql/x402'))
from controller import ResourceController,BoundaryError
PG=Path('/opt/homebrew/opt/postgresql@16/bin');DB='chainsql_m4_verify_'+uuid.uuid4().hex[:8]
admin=dict(host=str(ROOT/'.local/milestone0/socket'),port=55432,user='m0_admin',dbname=DB)
c0=json.loads((ROOT/'.local/milestone0/credentials.json').read_text());c2=json.loads((ROOT/'.local/milestone2/credentials.json').read_text())
roles={r:dict(host='127.0.0.1',port=55432,dbname=DB,user='chainsql_'+r,password=(c0 if r in ['odoo','worker'] else c2)[r]) for r in ['odoo','worker','signer','observer']}
with closing(psycopg2.connect(**dict(admin,dbname='postgres'))) as db:
 db.autocommit=True
 with db.cursor() as cur:cur.execute('CREATE DATABASE '+DB+' OWNER chainsql_odoo TEMPLATE template0')
cmd=[str(PG/'psql'),'-Xq','-v','ON_ERROR_STOP=1','-h',admin['host'],'-p','55432','-U','m0_admin','-d',DB]
script='\n'.join((ROOT/p).read_text() for p in ['milestone0/scripts/install_extension.sql','milestone2/scripts/install.sql','milestone3/scripts/install.sql','milestone4/scripts/install.sql'])
subprocess.run(cmd,input=script,text=True,check=True,capture_output=True)
def call(sql,args=(),role='admin'):
 with closing(psycopg2.connect(**(admin if role in ['admin','policy'] else roles[role]))) as db:
  with db:
   with db.cursor() as cur:
    if role=='policy':cur.execute('SET LOCAL ROLE chainsql_policy')
    cur.execute(sql,args);return cur.fetchall() if cur.description else []
def scalar(sql,args=(),role='admin'):return call(sql,args,role)[0][0]
checks=[]
def check(name,value=True):assert value,name;checks.append(name);print('PASS',name,flush=True)
def denied(name,f):
 try:f()
 except (psycopg2.Error,BoundaryError,ValueError):check(name)
 else:raise AssertionError(name)
tenant='test:'+DB
call('SELECT chainsql.set_pause_v1(false)',role='policy')
call('SELECT chainsql.set_wallet_v1(%s,%s,%s,true)',(tenant,'test-wallet','chainsql_odoo'),'policy')
def budgets(cap):
 for scope in ['*','test-wallet']:call('SELECT chainsql.set_budget_v1(%s,%s,%s,0,10000,0)',(tenant,scope,cap),'policy')
budgets(10000)
def request():
 now=datetime.now(timezone.utc)
 s=dict(tenant=tenant,business_reference=str(uuid.uuid4()),request_revision='1',source_wallet='test-wallet',destination='0x'+'22'*20,network='eip155:84532',asset='USDC',interface='x402-eip3009-6',amount_atomic='10000',fee_ceiling_atomic='0',policy_version='boundary-v1',approval_identity='test policy',valid_from=(now-timedelta(seconds=2)).isoformat().replace('+00:00','Z'),valid_until=(now+timedelta(minutes=30)).isoformat().replace('+00:00','Z'))
 r=dict(url='http://127.0.0.1:8094/vendor-verification/1?version=1',method='GET',body='',resource_version='1',resource_key='demo-vendor-verification',operation_id='1',operation_fingerprint='a'*64,scheme='exact',asset='0x036CbD53842c5426634e7929541eC2318f3dCF7e',domain_name='USDC',domain_version='2')
 a=scalar('SELECT chainsql.approve_resource_v1(%s,%s)',(Json(s),Json(r)),'policy')
 tid=str(scalar('SELECT chainsql.request_resource_v1(%s,%s,%s,%s)',(a,Json(s),Json(r),s['business_reference']),'odoo'))
 return tid,a,s,r
one,a,s,r=request();two,*_=request()
check('Identical enqueue returns same obligation',str(scalar('SELECT chainsql.request_resource_v1(%s,%s,%s,%s)',(a,Json(s),Json(r),s['business_reference']),'odoo'))==one)
denied('Changed request rejected',lambda:call('SELECT chainsql.request_resource_v1(%s,%s,%s,%s)',(a,Json(s),Json(dict(r,url=r['url']+'x')),'new'),'odoo'))
denied('Worker cannot read encrypted authorizations',lambda:call('SELECT * FROM chainsql.transfer_authorizations',role='worker'))
denied('Worker cannot change budget',lambda:call('SELECT chainsql.set_budget_v1(%s,%s,100000,0,10000,0)',(tenant,'*'),'worker'))
def claim(tid):return call('SELECT * FROM chainsql.claim_transfer_v1(%s)',(tid,),'worker')[0]
def try_claim(tid):
 try:return tid,claim(tid)
 except psycopg2.Error:return tid,None
with concurrent.futures.ThreadPoolExecutor(2) as ex:results=list(ex.map(try_claim,[one,two]))
check('Concurrent requests cannot exceed budget',sum(row is not None for _,row in results)==1)
tid,row=next((tid,row) for tid,row in results if row);_,token,fence,_=row
loser=next(tid for tid,row in results if row is None)
denied('Exhausted budget denies signing claim',lambda:claim(loser))
budgets(20000)
class Fixture:
 def __init__(self):self.signs=0;self.sends=0;self.settled=False;self.lose_response=False;self.offline=False;self.redeliveries=0
 def __call__(self,op,s,r,fp,a=None):
  if op=='challenge':return {'httpStatus':402}
  if op=='sign':self.signs+=1;return {'payment':{'fixture':fp},'fromBlock':'1'}
  if op=='validate':return {'valid':True}
  if op=='redeliver':self.redeliveries+=1;return {'delivery':{'demonstration':True}}
  if op=='purchase':
   self.sends+=1;self.settled=True
   if self.lose_response:raise BoundaryError('lost_response')
   return {'delivery':{'demonstration':True},'settlement':{'success':True,'transaction':'0x'+'11'*32}}
  if self.offline:raise BoundaryError('provider_unavailable')
  if not self.settled:return {'pending':True}
  return dict(transaction='0x'+'11'*32,network=s['network'],amount=s['amount_atomic'],recipient=s['destination'],authorization_nonce='0x'+fp,receipt_status='success')
fixture=Fixture();conf=dict(signer=roles['signer'],observer=roles['observer'],encryption_key=base64.b64encode(b'k'*32).decode(),tenant=tenant,journal_directory=tempfile.mkdtemp())
executor=ResourceController(conf,fixture)
call("CREATE FUNCTION public.fail_save() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected disk failure'; END $$; CREATE TRIGGER fail_save BEFORE INSERT ON chainsql.transfer_authorizations FOR EACH ROW EXECUTE FUNCTION public.fail_save()")
denied('Authorization persistence failure closes dispatch',lambda:executor.run(tid,str(token),fence))
check('No HTTP payment after failed save',fixture.sends==0)
call('DROP TRIGGER fail_save ON chainsql.transfer_authorizations')
e=executor.run(tid,str(token),fence)
check('Retry reuses journal authorization without resigning',fixture.signs==1)
check('Payment and resource states independently observed',e['payment_state']=='confirmed' and e['delivery_state']=='delivered')
original=scalar('SELECT digest FROM chainsql.transfer_authorizations WHERE transfer_id=%s',(tid,))
executor.run(tid,reconcile_only=True)
check('Reconciliation neither signs nor transmits',fixture.signs==1 and fixture.sends==1)
check('Authorization digest unchanged',original==scalar('SELECT digest FROM chainsql.transfer_authorizations WHERE transfer_id=%s',(tid,)))
# Lose a submitted response while the observer is offline; recover without another send.
budgets(30000)
lost,*_=request();_,lt,lf,_=claim(lost)
lost_provider=Fixture();lost_provider.lose_response=True;lost_provider.offline=True
recovery=ResourceController(dict(conf,journal_directory=tempfile.mkdtemp()),lost_provider)
pending=recovery.run(lost,str(lt),lf)
check('Lost response and unavailable observer retain reservation',pending['payment_state']=='pending' and scalar('SELECT reserved FROM chainsql.transfers WHERE id=%s',(lost,)))
lost_provider.offline=False
recovered=recovery.run(lost,reconcile_only=True)
check('Lost response recovered with original authorization',recovered['delivery_state']=='delivered' and lost_provider.signs==1 and lost_provider.sends==1 and lost_provider.redeliveries==1)
public=scalar('SELECT chainsql.resource_status_v1(%s)',(lost,),'odoo')
check('Public status excludes authorization bytes','ciphertext' not in json.dumps(public) and 'signature' not in json.dumps(public))
budgets(30000)
# New unsigned request, cancellation and revocation are inherited from M2.
third,a3,s3,r3=request();_,t3,f3,_=claim(third)
call('SELECT chainsql.set_pause_v1(true)',role='policy')
denied('Pause blocks signing',lambda:executor.run(third,str(t3),f3))
call('SELECT chainsql.set_pause_v1(false)',role='policy')
call('SELECT chainsql.invalidate_business_v1(%s,%s)',(tenant,s3['business_reference']),'odoo')
denied('Revoked approval blocks signing',lambda:executor.run(third,str(t3),f3))
call('SELECT chainsql.cancel_transfer_v1(%s)',(third,),'odoo')
check('Unsigned cancellation releases reservation',not scalar('SELECT reserved FROM chainsql.transfers WHERE id=%s',(third,)))
# No generic simulator expiry release on the new network.

four,a4,s4,r4=request();_,t4,f4,_=claim(four)
call('SELECT chainsql.save_authorization_v1(%s,%s,%s,%s,%s)',(four,t4,f4,psycopg2.Binary(b'fixture'*10), 'a'*64),'signer')
call('SELECT chainsql.dispatch_transfer_v1(%s,%s,%s)',(four,t4,f4),'signer')
denied('Missing transaction cannot confirm payment',lambda:call('SELECT chainsql.record_resource_v1(%s,%s,NULL)',(four,Json(dict(fingerprint=scalar('SELECT fingerprint FROM chainsql.resource_material_v1(%s)',(four,),'signer'),payment_state='confirmed',delivery_state='pending',network=s4['network'],amount=s4['amount_atomic'],recipient=s4['destination'],authorization_nonce='0x'+scalar('SELECT fingerprint FROM chainsql.resource_material_v1(%s)',(four,),'signer'),receipt_status='success'))),'observer'))
check('Cancellation after dispatch requires reconciliation',scalar('SELECT chainsql.cancel_transfer_v1(%s)',(four,),'odoo')=='reconciliation')
call('SELECT chainsql.reconcile_transfer_v1(%s)',(four,),'observer')
check('No simulator release of x402 budget',scalar('SELECT reserved FROM chainsql.transfers WHERE id=%s',(four,)))
call("UPDATE chainsql.transfers SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",(four,))
_,newtoken,newfence,_=claim(four)
denied('Stale fence cannot save independent authorization',lambda:call('SELECT chainsql.save_authorization_v1(%s,%s,%s,%s,%s)',(four,t4,f4,psycopg2.Binary(b'bad'),'b'*64),'signer'))
# Transaction rollback leaves neither a queued transfer nor a new resource link.
five,a5,s5,r5=request();call('SELECT chainsql.cancel_transfer_v1(%s)',(five,),'odoo')
denied('Even accidental approval UPDATE is rejected',lambda:call("UPDATE chainsql.resource_approvals SET request=request || '{\"method\":\"POST\"}'::jsonb WHERE approval_id=%s",(a5,)))
(ROOT/'milestone4/evidence/native.json').write_text(json.dumps({'database':DB,'checks':checks,'count':len(checks),'synthetic_provider':True},indent=2))
print('Native checks:',len(checks))
