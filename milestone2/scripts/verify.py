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
DB='chainsql_m2_verify_'+uuid.uuid4().hex[:10]
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
                   input=base+'\n'+install,text=True,capture_output=True,check=True)
    call('REVOKE ALL ON DATABASE '+db+' FROM PUBLIC; GRANT CONNECT ON DATABASE '+db+' TO chainsql_odoo,chainsql_worker,chainsql_signer,chainsql_observer',db=db)
create_db(DB)
call('SELECT chainsql.set_pause_v1(false)',role='policy')
config=json.loads((ROOT/'.local/milestone2/signer.json').read_text());config['database']=roles['signer']
signer=RestrictedSigner(config)
observer={'database':roles['observer']}

def provision(tenant,value=100,fee=100,per_value=100,per_fee=10,wallets=('wallet-a',)):
    call('SELECT chainsql.set_budget_v1(%s,%s,%s,%s,%s,%s)',(tenant,'*',value,fee,per_value,per_fee),'policy')
    for wallet in wallets:
        call('SELECT chainsql.set_budget_v1(%s,%s,%s,%s,%s,%s)',(tenant,wallet,value,fee,per_value,per_fee),'policy')
        call('SELECT chainsql.set_wallet_v1(%s,%s,%s,true)',(tenant,wallet,'chainsql_odoo'),'policy')

def snapshot(tenant,business=None,amount='10',fee='2',revision='1',wallet='wallet-a',seconds=1800):
    now=datetime.now(timezone.utc)
    return dict(tenant=tenant,business_reference=business or str(uuid.uuid4()),request_revision=revision,
        source_wallet=wallet,destination='mock:vendor-a',network='mock:local',asset='USDC',interface='mock-usdc-6',
        amount_atomic=amount,fee_ceiling_atomic=fee,policy_version='boundary-v1',approval_identity='independent-policy-reviewer',
        valid_from=(now-timedelta(seconds=1)).isoformat().replace('+00:00','Z'),valid_until=(now+timedelta(seconds=seconds)).isoformat().replace('+00:00','Z'))
def approve(s):return str(scalar('SELECT chainsql.approve_transfer_v1(%s)',(Json(s),),'policy'))
def request(s,aid=None,key=None):
    aid=aid or approve(s)
    return str(scalar('SELECT chainsql.request_transfer_v1(%s,%s,%s)',(aid,Json(s),key or str(uuid.uuid4())),'odoo'))
def claim(t):
    row=call('SELECT * FROM chainsql.claim_transfer_v1(%s)',(t,),'worker')[0]
    return t,str(row[1]),row[2]
def status(t):return scalar('SELECT chainsql.transfer_status_v1(%s)',(t,),'odoo')
def budget(tenant,scope='*'):
    return call('SELECT value_reserved,fee_reserved,value_spent,fee_spent FROM chainsql.transfer_budgets WHERE tenant=%s AND scope=%s',(tenant,scope))[0]
def cancel(t):return scalar('SELECT chainsql.cancel_transfer_v1(%s)',(t,),'odoo')

# SQL role boundaries are real, not UI flags.
for role in ['odoo','worker']:
    for q in ['SELECT * FROM chainsql.transfer_authorizations','UPDATE chainsql.transfer_budgets SET value_limit=999999',
              'SELECT chainsql.set_pause_v1(false)','SET ROLE chainsql_policy','SET ROLE chainsql_signer']:
        denied(role+' cannot '+q.split('chainsql.')[-1],lambda q=q,role=role:call(q,role=role))
denied('signer cannot edit policy',lambda:call('SELECT chainsql.set_pause_v1(false)',role='signer'))
denied('worker cannot issue independent transfer approvals',lambda:call("SELECT chainsql.approve_transfer_v1('{}')",role='worker'))
denied('worker cannot mark settlement observed',lambda:call('SELECT chainsql.reconcile_transfer_v1(%s)',(str(uuid.uuid4()),),'worker'))
check('extension installed natively as dedicated owner',scalar("SELECT extversion||':'||pg_get_userbyid(extowner) FROM pg_extension WHERE extname='chainsql'")=='0.2.1:chainsql_owner')

provision('concurrency',value=100,fee=40,per_value=10,per_fee=2,wallets=('a','b','c','d'))
for wallet in ['a','b','c','d']:
    call('SELECT chainsql.set_budget_v1(%s,%s,30,10,10,2)',('concurrency',wallet),'policy')
ids=[request(snapshot('concurrency',wallet=['a','b','c','d'][i%4])) for i in range(32)]
def try_claim(t):
    try:return claim(t)
    except psycopg2.Error as e:
        assert 'budget exceeded' in str(e),str(e)
        return None
with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:claims=list(pool.map(try_claim,ids))
check('32 concurrent requests cannot exceed cumulative company value budget',sum(c is not None for c in claims)==10 and budget('concurrency')[0]==100)
check('concurrent requests cannot exceed any wallet budget',all(budget('concurrency',w)[0]<=30 for w in ['a','b','c','d']))
check('payment and fee allowances reserved atomically',budget('concurrency')[:2]==(100,20))
provision('fee-budget',value=10000,fee=5)
feeids=[request(snapshot('fee-budget')) for _ in range(8)]
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:feeclaims=list(pool.map(try_claim,feeids))
check('concurrent cumulative fee budget is independently enforced',sum(c is not None for c in feeclaims)==2 and budget('fee-budget')[:2]==(20,4))
provision('limits',per_value=5,per_fee=2)
denied('per-operation value cap enforced before signing',lambda:claim(request(snapshot('limits'))),'budget exceeded')
denied('per-operation fee cap enforced before signing',lambda:claim(request(snapshot('limits',amount='1',fee='3'))),'budget exceeded')
denied('fractional atomic amounts rejected',lambda:approve(snapshot('limits',amount='1.5')))
s=snapshot('limits');s['network']='arc-testnet'
denied('live-network snapshots fail closed',lambda:approve(s))

provision('lifecycle',value=10000,fee=1000)
s=snapshot('lifecycle');aid=approve(s);t=request(s,aid,'same-key')
check('duplicate request returns the original operation',request(s,aid,'same-key')==t)
denied('changed recipient cannot reuse independent approval',lambda:request(dict(s,destination='mock:other'),aid,'changed'))
c=claim(t)
denied('active owner cannot be independently claimed',lambda:claim(t))
# Fault injection: simulate elapsed lease without delaying every test for 30 seconds.
call("UPDATE chainsql.transfers SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",(t,))
c2=claim(t)
check('lease takeover retains deterministic preparation identity',c2[0]==c[0] and c2[2]>c[2])
denied('stale worker cannot prepare another authorization',lambda:signer.prepare(*c),'stale fenced ownership')
digest=signer.prepare(*c2)
blob=scalar('SELECT ciphertext FROM chainsql.transfer_authorizations WHERE transfer_id=%s',(t,))
check('authorization encrypted at rest',b'mock:vendor-a' not in bytes(blob) and b'signature' not in bytes(blob))
check('retry preserves the exact authorization',signer.prepare(*c2)==digest and bytes(blob)==bytes(scalar('SELECT ciphertext FROM chainsql.transfer_authorizations WHERE transfer_id=%s',(t,))))
check('ordinary SQL status excludes signing material',not any(k in status(t) for k in ['ciphertext','signature','digest','authorization']))
call('SELECT chainsql.set_pause_v1(true)',role='policy')
denied('pause is rechecked at dispatch',lambda:signer.dispatch(*c2),'paused')
call('SELECT chainsql.set_pause_v1(false)',role='policy')
call("SELECT chainsql.set_wallet_v1('lifecycle','wallet-a','chainsql_odoo',false)",role='policy')
denied('wallet permission is rechecked at dispatch',lambda:signer.dispatch(*c2),'wallet permission revoked')
call("SELECT chainsql.set_wallet_v1('lifecycle','wallet-a','chainsql_odoo',true)",role='policy')
receipt=signer.dispatch(*c2)
check('exact persisted authorization settles only once',signer.dispatch(*c2)==receipt and scalar('SELECT count(*) FROM chainsql.mock_settlements WHERE transfer_id=%s',(t,))==1)
check('cancellation after dispatch retains the reservation and requires reconciliation',cancel(t)=='reconciliation' and status(t)['reserved'])
check('observed settlement after cancellation requires compensation',reconcile(observer,t)=='observed' and 'compensation' in status(t)['reason'])
check('reservation converts to value and actual fee spend',budget('lifecycle')==(0,0,10,1))
check('repeat observation never double counts spend',reconcile(observer,t)=='observed' and budget('lifecycle')==(0,0,10,1))
s2=dict(s,request_revision='2',destination='mock:edited')
a2=approve(s2)
denied('settled obligation cannot acquire another payable revision',lambda:request(s2,a2))

# A database persistence failure must stop execute() before any dispatch intent or transmission.
tfail=request(snapshot('lifecycle'));cfail=claim(tfail)
call("CREATE FUNCTION public.fail_authorization_test() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected persistence failure'; END $$; CREATE TRIGGER fail_authorization_test BEFORE INSERT ON chainsql.transfer_authorizations FOR EACH ROW EXECUTE FUNCTION public.fail_authorization_test()")
denied('authorization persistence failure closes the execution path',lambda:signer.execute(*cfail),'injected persistence failure')
check('failed save creates neither authorization nor dispatch',status(tfail)['state']=='reserved' and scalar('SELECT count(*) FROM chainsql.transfer_authorizations WHERE transfer_id=%s',(tfail,))==0 and scalar('SELECT count(*) FROM chainsql.mock_settlements WHERE transfer_id=%s',(tfail,))==0)
call('DROP TRIGGER fail_authorization_test ON chainsql.transfer_authorizations; DROP FUNCTION public.fail_authorization_test()')
check('unsigned cancellation safely releases its reservation',cancel(tfail)=='cancelled' and not status(tfail)['reserved'])

# Even a signer SQL session cannot dispatch an authorization saved in its current transaction.
tdur=request(snapshot('lifecycle'));cdur=claim(tdur)
def uncommitted_dispatch():
    with closing(psycopg2.connect(**roles['signer'])) as conn:
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT chainsql.save_authorization_v1(%s,%s,%s,%s,%s)',(*cdur,psycopg2.Binary(b'x'*80),'a'*64))
                cur.execute('SELECT * FROM chainsql.dispatch_transfer_v1(%s,%s,%s)',cdur)
denied('dispatch requires a previously committed authorization',uncommitted_dispatch,'must commit')
check('failed durability check rolls back the authorization save',scalar('SELECT count(*) FROM chainsql.transfer_authorizations WHERE transfer_id=%s',(tdur,))==0)
cancel(tdur)

sedit=snapshot('lifecycle');tedit=request(sedit);cedit=claim(tedit);signer.prepare(*cedit)
new=dict(sedit,request_revision='2',destination='mock:changed-recipient');newaid=approve(new)
denied('edited recipient invalidates old approval before dispatch',lambda:signer.dispatch(*cedit),'stale or revoked')
denied('edited revision cannot bypass an outstanding signed attempt',lambda:request(new,newaid))
check('cancelling a prepared authorization retains funds until proven safe',cancel(tedit)=='reconciliation' and status(tedit)['reserved'])
check('missing receipt alone does not release reservations',reconcile(observer,tedit)=='reconciliation' and status(tedit)['reserved'])

sexp=snapshot('lifecycle',seconds=2);texp=request(sexp);cexp=claim(texp);signer.prepare(*cexp)
# Commit dispatch intent but simulate a lost response/crash before transmission.
call('SELECT * FROM chainsql.dispatch_transfer_v1(%s,%s,%s)',cexp,'signer')
check('uncertain dispatch cancellation becomes reconciliation',cancel(texp)=='reconciliation' and status(texp)['reserved'])
time.sleep(2.2)
check('authoritative expiry without settlement safely releases reservation',reconcile(observer,texp)=='cancelled' and not status(texp)['reserved'])
denied('old authorization cannot settle after reservation release',lambda:signer.dispatch(*cexp))

srev=snapshot('lifecycle');arev=approve(srev);trev=request(srev,arev);crev=claim(trev);signer.prepare(*crev)
call('SELECT chainsql.revoke_approval_v1(%s)',(arev,),'policy')
denied('current revocation is rechecked at dispatch',lambda:signer.dispatch(*crev),'stale or revoked')
denied('immutable payment snapshot rejects even accidental privileged UPDATE',lambda:call("UPDATE chainsql.transfers SET snapshot=jsonb_set(snapshot,'{destination}','\"mock:evil\"') WHERE id=%s",(trev,)))
denied('issued approvals cannot be unrevoked',lambda:call('UPDATE chainsql.transfer_approvals SET revoked=false WHERE id=%s',(arev,)))

# Native dump/restore must preserve encrypted runtime authorization bytes and ownership.
RESTORE=DB.replace('verify','restore')
backup=ROOT/'.local/milestone2'/f'{DB}.dump'
pgargs=['-h',ADMIN['host'],'-p','55432','-U','m0_admin']
subprocess.run([str(PG/'pg_dump'),*pgargs,'-Fc','-f',str(backup),DB],check=True,capture_output=True)
create_db(RESTORE)
toc=subprocess.check_output([str(PG/'pg_restore'),'--list',str(backup)],text=True)
tocfile=backup.with_suffix('.toc')
tocfile.write_text('\n'.join(';' + line if ' SCHEMA - chainsql ' in line else line for line in toc.splitlines())+'\n')
subprocess.run([str(PG/'pg_restore'),*pgargs,'--exit-on-error','-L',str(tocfile),'-d',RESTORE,str(backup)],check=True,capture_output=True)
call('SELECT chainsql.set_pause_v1(true)',role='policy',db=RESTORE)
check('native backup/restore preserves encrypted authorizations',bytes(scalar('SELECT ciphertext FROM chainsql.transfer_authorizations WHERE transfer_id=%s',(t,),db=RESTORE))==bytes(blob))
check('native backup/restore preserves spent and reserved budgets',call('SELECT * FROM chainsql.transfer_budgets ORDER BY tenant,scope')==call('SELECT * FROM chainsql.transfer_budgets ORDER BY tenant,scope',db=RESTORE))
check('restored boundary is explicitly paused before use',scalar('SELECT paused FROM chainsql.execution_gate',db=RESTORE))
check('restored extension retains dedicated owner',scalar("SELECT pg_get_userbyid(extowner) FROM pg_extension WHERE extname='chainsql'",db=RESTORE)=='chainsql_owner')
check('signer key can decrypt the restored exact authorization',signer._open(scalar('SELECT ciphertext FROM chainsql.transfer_authorizations WHERE transfer_id=%s',(t,),db=RESTORE),digest,t)['snapshot']==s)
result={'verified_at':datetime.now(timezone.utc).isoformat(),'database':DB,'restore_database':RESTORE,
        'checks_passed':len(checks),'checks':checks,'network':'mock:local','live_execution_enabled':False}
(ROOT/'milestone2/evidence/integration.json').write_text(json.dumps(result,indent=2)+'\n')
print('COMPLETE:',len(checks),'checks passed; native verification databases retained.')
