#!/usr/bin/env python3
"""Native PostgreSQL integration/security tests. All mutations target unique test databases."""
import concurrent.futures
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid
import psycopg2
from psycopg2.extras import Json

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'chainsql/boundary'))
from signer import RestrictedSigner, reconcile
PG=Path('/opt/homebrew/opt/postgresql@16/bin')
DB='chainsql_m3_verify_'+uuid.uuid4().hex[:10]
ADMIN=dict(host=str(ROOT/'.local/milestone0/socket'),port=55432,user='m0_admin',dbname=DB)
creds0=json.loads((ROOT/'.local/milestone0/credentials.json').read_text())
creds2=json.loads((ROOT/'.local/milestone2/credentials.json').read_text())
roles={name:dict(host='127.0.0.1',port=55432,dbname=DB,user='chainsql_'+name,
      password=(creds0 if name in ('odoo','worker') else creds2)[name]) for name in ['odoo','worker','signer','observer']}
checks=[]
def call(query,params=(),role='admin',db=None):
    conf=dict(ADMIN if role in ('admin','policy') else roles[role])
    if db: conf['dbname']=db
    with closing(psycopg2.connect(**conf)) as conn:
        with conn:
            with conn.cursor() as cur:
                if role=='policy':cur.execute('SET LOCAL ROLE chainsql_policy')
                cur.execute(query,params)
                return cur.fetchall() if cur.description else []
def scalar(q,p=(),role='admin',db=None):return call(q,p,role,db)[0][0]
def check(name,condition=True):
    assert condition,name
    checks.append(name);print('PASS:',name,flush=True)
def denied(name,fn,contains=None):
    try:fn()
    except (psycopg2.Error,ValueError) as e:
        if contains:assert contains in str(e),(name,str(e))
        check(name)
    else:raise AssertionError(name)

def create_db(db):
    with closing(psycopg2.connect(**dict(ADMIN,dbname='postgres'))) as conn:
        conn.autocommit=True
        with conn.cursor() as cur:cur.execute('CREATE DATABASE '+db+' OWNER chainsql_odoo TEMPLATE template0')
    base=(ROOT/'milestone0/scripts/install_extension.sql').read_text()
    install=(ROOT/'milestone2/scripts/install.sql').read_text()
    subprocess.run([str(PG/'psql'),'-Xq','-v','ON_ERROR_STOP=1','-h',ADMIN['host'],'-p','55432','-U','m0_admin','-d',db],
                   input=base+'\n'+install+'\n'+(ROOT/'milestone3/scripts/install.sql').read_text(),text=True,capture_output=True,check=True)
    call('REVOKE ALL ON DATABASE '+db+' FROM PUBLIC; GRANT CONNECT ON DATABASE '+db+' TO chainsql_odoo,chainsql_worker,chainsql_signer,chainsql_observer',db=db)
create_db(DB)
sys.path.insert(0,str(ROOT/'chainsql/arc'))
from controller import ArcController,BoundaryError
import tempfile
call('SELECT chainsql.set_pause_v1(false)',role='policy')
call('SELECT chainsql.enable_arc_v1(true)',role='policy')
TENANT='arc-test:'+DB
WALLET='fixture-signing-wallet'
for scope in ['*',WALLET]:
    call('SELECT chainsql.set_budget_v1(%s,%s,10000000,1000000000000000000,1000000,50000000000000000)',(TENANT,scope),'policy')
call('SELECT chainsql.set_wallet_v1(%s,%s,%s,true)',(TENANT,WALLET,'chainsql_odoo'),'policy')
def make_request():
    now=datetime.now(timezone.utc)
    s=dict(tenant=TENANT,business_reference=str(uuid.uuid4()),request_revision='1',source_wallet=WALLET,
        destination='0x'+'22'*20,network='eip155:5042002',asset='USDC',interface='arc-erc20-6-fee18',amount_atomic='10000',
        fee_ceiling_atomic='50000000000000000',policy_version='boundary-v1',approval_identity='test-reviewer',
        valid_from=(now-timedelta(seconds=1)).isoformat().replace('+00:00','Z'),valid_until=(now+timedelta(hours=1)).isoformat().replace('+00:00','Z'))
    aid=scalar('SELECT chainsql.approve_transfer_v1(%s)',(Json(s),),'policy')
    tid=str(scalar('SELECT chainsql.request_transfer_v1(%s,%s,%s)',(aid,Json(s),s['business_reference']),'odoo'))
    _,token,fence,_=call('SELECT * FROM chainsql.claim_transfer_v1(%s)',(tid,),'worker')[0]
    return tid,str(token),fence,s
class FixtureProvider:
    # Synthetic provider tests SQL/controller state machines; adapter.test.mjs tests real signing/decoding.
    def __init__(self):self.signs=0;self.sends=0;self.found=False
    def __call__(self,op,s,p=None,a=None):
        if op=='prepare':return dict(sender='0x'+'11'*20,pendingNonce='0',gas='50000',maxFeePerGas='2000000000',maxPriorityFeePerGas='1000000000')
        if op=='sign':
            self.signs+=1
            return dict(raw='fixture-not-broadcastable',txHash='0x'+hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest())
        if op=='validate':return dict(txHash=a['txHash'])
        if op=='submit':self.sends+=1;self.found=True;return dict(state='uncertain',txHash=a['txHash'])
        if not self.found:return dict(state='uncertain',txHash=a['txHash'])
        return dict(state='confirmed',network=s['network'],chainId=5042002,asset='USDC',token='0x3600000000000000000000000000000000000000',
            amountAtomic=s['amount_atomic'],amountDecimals=6,feeAtomic='1000000000000',feeDecimals=18,txHash=a['txHash'],
            receiptStatus='success',matchingTransferLogs=1,blockNumber='20',blockHash='0x'+'33'*32,
            finalizedBlockNumber='20',finalizedBlockHash='0x'+'33'*32,observedAt=datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),providerRequestId=p['providerRequestId'])
config=json.loads((ROOT/'.local/milestone2/signer.json').read_text());config['database']=roles['signer']
provider=FixtureProvider();directory=tempfile.mkdtemp(prefix='chainsql-m3-')
c=ArcController(config,{'database':roles['observer']},provider,directory,TENANT)
tid,token,fence,s=make_request()
c.prepare(tid,token,fence)
check('encrypted authorization committed before transmission',scalar('SELECT count(*) FROM chainsql.transfer_authorizations WHERE transfer_id=%s',(tid,))==1 and provider.sends==0)
check('same preparation reuses authorization',c.prepare(tid,token,fence) and provider.signs==1)
denied('Arc cannot pass through mock settlement gateway',lambda:call('SELECT chainsql.accept_mock_transfer_v1(%s,%s,%s,%s)',(tid,token,fence,'0'*64),'signer'))
check('lost submission response classified uncertain',c.submit(tid,token,fence)['state']=='uncertain')
result=c.reconcile(tid)
check('original hash recovered without another signing or submission',result['state']=='confirmed' and provider.signs==1 and provider.sends==1)
c.reconcile(tid)
check('repeated observation does not spend twice',scalar('SELECT value_spent FROM chainsql.transfer_budgets WHERE tenant=%s AND scope=%s',(TENANT,'*'))==10000)
for field in ['state','feeAtomic','blockNumber','finalizedBlockNumber','providerRequestId','matchingTransferLogs']:
    bad=dict(result);bad.pop(field)
    denied('reject missing receipt field '+field,lambda:call('SELECT chainsql.record_arc_observation_v1(%s,%s)',(tid,Json(bad)),'observer'))
for role in ['odoo','worker']:
    denied(role+' cannot inspect authorization',lambda:call('SELECT * FROM chainsql.arc_recovery_material_v1(%s)',(tid,),role))
    denied(role+' cannot enable Arc',lambda:call('SELECT chainsql.enable_arc_v1(true)',role=role))
# Concurrent reservation/planning uses one sender nonce stream across distinct obligations.
requests=[make_request() for _ in range(6)]
def prepare_one(r):return c.prepare(*r[:3])
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(prepare_one,requests))
check('concurrent workers allocate unique sender nonces',scalar('SELECT count(DISTINCT nonce) FROM chainsql.arc_plans')==7)
t2,k2,f2,s2=requests[0]
call('SELECT chainsql.cancel_transfer_v1(%s)',(t2,),'odoo')
call("UPDATE chainsql.transfers SET lease_until=clock_timestamp()-interval '1 minute' WHERE id=%s",(t2,))
call('SELECT chainsql.reconcile_transfer_v1(%s)',(t2,),'observer')
check('signed Arc cancellation retains reservation',scalar('SELECT reserved FROM chainsql.transfers WHERE id=%s',(t2,)))
denied('cancelled authorization cannot dispatch',lambda:c.submit(t2,k2,f2))
call('SELECT chainsql.enable_arc_v1(false)',role='policy')
r=requests[1]
denied('pause blocks dispatch of saved authorization',lambda:c.submit(*r[:3]))
check('reconciliation works with execution disabled',c.reconcile(tid)['state']=='confirmed')
# A failed durable save must not transmit; the external journal recovers the same authorization.
call('SELECT chainsql.enable_arc_v1(true)',role='policy')
failure=make_request();fid,ft,ff,_=failure
call("CREATE FUNCTION public.fail_arc_save() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected persistence failure'; END $$; CREATE TRIGGER fail_arc_save BEFORE INSERT ON chainsql.transfer_authorizations FOR EACH ROW EXECUTE FUNCTION public.fail_arc_save()")
before_sends=provider.sends
denied('authorization persistence failure prevents dispatch',lambda:c.prepare(fid,ft,ff))
check('failed persistence sends no transaction',provider.sends==before_sends)
before_signs=provider.signs
call('DROP TRIGGER fail_arc_save ON chainsql.transfer_authorizations; DROP FUNCTION public.fail_arc_save()')
c.prepare(fid,ft,ff)
check('failed save recovery reuses encrypted journal authorization',provider.signs==before_signs)
call("UPDATE chainsql.transfers SET lease_until=clock_timestamp()-interval '1 minute' WHERE id=%s",(fid,))
_,new_token,new_fence,_=call('SELECT * FROM chainsql.claim_transfer_v1(%s)',(fid,),'worker')[0]
denied('stale worker cannot sign after ownership changes',lambda:c.prepare(fid,ft,ff))
check('new owner retains original hash',c.prepare(fid,str(new_token),new_fence)==c.material(fid)[2]['txHash'])
call('SELECT chainsql.enable_arc_v1(false)',role='policy')
# Native extension-owned runtime data survives pg_dump/restore (including encrypted bytes and nonce high-water).
backup=Path(directory)/'backup.dump'
subprocess.run([str(PG/'pg_dump'),'-Fc','-h',ADMIN['host'],'-p','55432','-U','m0_admin','-d',DB,'-f',str(backup)],check=True,capture_output=True)
restored=DB+'_restored'
create_db(restored)
toc=subprocess.check_output([str(PG/'pg_restore'),'--list',str(backup)],text=True)
tocfile=backup.with_suffix('.toc')
tocfile.write_text('\n'.join(';'+line if ' SCHEMA - chainsql ' in line else line for line in toc.splitlines())+'\n')
r=subprocess.run([str(PG/'pg_restore'),'-L',str(tocfile),'-h',ADMIN['host'],'-p','55432','-U','m0_admin','-d',restored,str(backup)],capture_output=True,text=True)
if r.returncode:raise RuntimeError(r.stderr)
check('backup restores nonce high-water',scalar('SELECT next_nonce FROM chainsql.arc_wallet_nonces',db=restored)==8)
check('backup restores encrypted authorizations',scalar('SELECT count(*) FROM chainsql.transfer_authorizations',db=restored)==8)
check('backup restores terminal observation',scalar('SELECT count(*) FROM chainsql.arc_observations',db=restored)==1)
restored_config=dict(config,database=dict(roles['signer'],dbname=restored))
restored_controller=ArcController(restored_config,{'database':dict(roles['observer'],dbname=restored)},provider,directory,TENANT)
check('restored dispatched attempt reconciles by original hash',restored_controller.reconcile(tid)['txHash']==result['txHash'])
check('restore reconciliation never transmits',provider.sends==before_sends)
(ROOT/'milestone3/evidence/native.json').write_text(json.dumps(dict(verified_at=datetime.now(timezone.utc).isoformat(),database=DB,checks=checks,checks_passed=len(checks),provider='synthetic; no live transfer'),indent=2)+'\n')
print('COMPLETE',len(checks),'native checks')
