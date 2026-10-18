#!/usr/bin/env python3
"""End-to-end Odoo ORM + native role + actual restricted signer tests in a clone."""
import json
from contextlib import closing
from datetime import datetime,timedelta,timezone
from pathlib import Path
import subprocess
import sys
import uuid
import psycopg2
from psycopg2.extras import Json
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'chainsql/boundary'))
from signer import RestrictedSigner
compose=['docker','compose','-f',str(ROOT/'milestone0/compose.yaml'),'-f',str(ROOT/'milestone2/compose.yaml')]
db='chainsql_m2_odoo_'+uuid.uuid4().hex[:10]
admin=dict(host=str(ROOT/'.local/milestone0/socket'),port=55432,user='m0_admin',dbname=db)
def sql(query,args=(),policy=False):
    with closing(psycopg2.connect(**admin)) as conn:
        with conn:
            with conn.cursor() as cur:
                if policy:cur.execute('SET LOCAL ROLE chainsql_policy')
                cur.execute(query,args)
                return cur.fetchall() if cur.description else []
running=subprocess.check_output(compose+['ps','--status','running','--services'],text=True).split()
subprocess.run(compose+['stop',*running],check=True,capture_output=True)
try:
    with closing(psycopg2.connect(**dict(admin,dbname='postgres'))) as conn:
        conn.autocommit=True
        with conn.cursor() as cur:cur.execute('CREATE DATABASE '+db+' OWNER chainsql_odoo TEMPLATE chainsql_m0')
finally:subprocess.run(compose+['up','-d',*running],check=True,capture_output=True)
sql('GRANT CONNECT ON DATABASE '+db+' TO chainsql_signer,chainsql_observer,chainsql_worker')
def shell(file,prefix,op_id=None):
    command=compose+['run','--rm','-T']
    if op_id:command+=['-e',f'M2_OP_ID={op_id}']
    command+=['odoo','odoo','shell','-d',db,'--no-http','--log-level=critical']
    r=subprocess.run(command,input=(ROOT/'milestone2/scripts'/file).read_text(),text=True,capture_output=True)
    if r.returncode:raise RuntimeError(r.stdout+'\n'+r.stderr)
    return json.loads(next(s for s in r.stdout.splitlines() if s.startswith(prefix)).removeprefix(prefix))
fixture=shell('odoo_prepare.py','FIXTURE:')
now=datetime.now(timezone.utc)
s={k:v for k,v in fixture.items() if k not in ['op_id','bill_id']}
s.update(source_wallet='m2-test-source',network='mock:local',asset='USDC',interface='mock-usdc-6',
    fee_ceiling_atomic='10',policy_version='boundary-v1',approval_identity='isolated-test-policy-reviewer',
    valid_from=(now-timedelta(seconds=1)).isoformat().replace('+00:00','Z'),
    valid_until=(now+timedelta(minutes=30)).isoformat().replace('+00:00','Z'))
sql('SELECT chainsql.set_pause_v1(false)',policy=True)
for scope in ['*','m2-test-source']:
    sql('SELECT chainsql.set_budget_v1(%s,%s,1000000000,10000,1000000000,1000)',(s['tenant'],scope),True)
sql('SELECT chainsql.set_wallet_v1(%s,%s,%s,true)',(s['tenant'],s['source_wallet'],'chainsql_odoo'),True)
sql('SELECT chainsql.approve_transfer_v1(%s)',(Json(s),),True)
transfer=shell('odoo_submit.py','TRANSFER:',fixture['op_id']);tid=transfer['id']
conf=json.loads((ROOT/'.local/milestone0/worker.json').read_text());conf.update(host='127.0.0.1',dbname=db)
with closing(psycopg2.connect(**conf)) as conn:
    with conn:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM chainsql.claim_transfer_v1(%s)',(tid,));_,token,fence,_=cur.fetchone()
signerconf=json.loads((ROOT/'.local/milestone2/signer.json').read_text());signerconf['database'].update(host='127.0.0.1',dbname=db)
signer=RestrictedSigner(signerconf);signer.prepare(tid,str(token),fence)
checks=transfer['checks']+shell('odoo_invalidation.py','INVALIDATION:',fixture['op_id'])
try:signer.dispatch(tid,str(token),fence)
except psycopg2.Error as e:assert 'stale or revoked' in str(e)
else:raise AssertionError('Signer accepted edited Odoo recipient')
checks.append('restricted signer refuses the authorization after an Odoo recipient edit')
assert sql('SELECT reserved FROM chainsql.transfers WHERE id=%s',(tid,))[0][0]
assert sql('SELECT count(*) FROM chainsql.mock_settlements WHERE transfer_id=%s',(tid,))[0][0]==0
checks.append('invalidated signed request retains reservation and creates no settlement')
result=dict(verified_at=datetime.now(timezone.utc).isoformat(),database=db,checks=checks,checks_passed=len(checks))
(ROOT/'milestone2/evidence/odoo-integration.json').write_text(json.dumps(result,indent=2)+'\n')
for name in checks:print('PASS:',name)
print('COMPLETE:',len(checks),'Odoo-to-boundary checks passed.')
