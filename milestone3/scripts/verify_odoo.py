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
db='chainsql_m3_odoo_'+uuid.uuid4().hex[:10]
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
    if op_id:command+=['-e',f'M3_OP_ID={op_id}']
    command+=['odoo','odoo','shell','-d',db,'--no-http','--log-level=critical']
    r=subprocess.run(command,input=(ROOT/'milestone3/scripts'/file).read_text(),text=True,capture_output=True)
    if r.returncode:raise RuntimeError(r.stdout+'\n'+r.stderr)
    return json.loads(next(s for s in r.stdout.splitlines() if s.startswith(prefix)).removeprefix(prefix))
r=subprocess.run(compose+['run','--rm','-T','odoo','odoo','-d',db,'--no-http','--stop-after-init','-i','chainsql_arc_account','--log-level=warn'],capture_output=True,text=True)
if r.returncode:raise RuntimeError(r.stdout+'\n'+r.stderr)
fixture=shell('odoo_prepare.py','FIXTURE:')
now=datetime.now(timezone.utc)
s={k:v for k,v in fixture.items() if k not in ['op_id','bill_id']}
s.update(source_wallet='m3-synthetic-source',network='eip155:5042002',asset='USDC',interface='arc-erc20-6-fee18',
 fee_ceiling_atomic='50000000000000000',policy_version='boundary-v1',approval_identity='isolated-test-reviewer',
 valid_from=(now-timedelta(seconds=1)).isoformat().replace('+00:00','Z'),valid_until=(now+timedelta(hours=1)).isoformat().replace('+00:00','Z'))
sql('SELECT chainsql.set_pause_v1(false)',policy=True);sql('SELECT chainsql.enable_arc_v1(true)',policy=True)
for scope in ['*',s['source_wallet']]:sql('SELECT chainsql.set_budget_v1(%s,%s,1000000000,100000000000000000,1000000000,50000000000000000)',(s['tenant'],scope),True)
sql('SELECT chainsql.set_wallet_v1(%s,%s,%s,true)',(s['tenant'],s['source_wallet'],'chainsql_odoo'),True)
sql('SELECT chainsql.approve_transfer_v1(%s)',(Json(s),),True)
tid=shell('odoo_submit.py','TRANSFER:',fixture['op_id'])['id']
# Trusted fixture insertion is confined to this disposable database; never represents live-chain evidence.
sql("UPDATE chainsql.transfers SET state='dispatched',reserved=true WHERE id=%s",(tid,))
sql('UPDATE chainsql.transfer_budgets SET value_reserved=%s,fee_reserved=%s WHERE tenant=%s',(s['amount_atomic'],s['fee_ceiling_atomic'],s['tenant']))
request_id=str(uuid.uuid4());tx='0x'+'aa'*32
sql('INSERT INTO chainsql.arc_plans(transfer_id,sender,nonce,gas,max_fee,priority_fee,provider_request_id,tx_hash) VALUES(%s,%s,0,50000,1000000000000,1000000000,%s,%s)',(tid,'0x'+'11'*20,request_id,tx))
e=dict(state='confirmed',chainId=5042002,network=s['network'],asset='USDC',token='0x3600000000000000000000000000000000000000',amountAtomic=s['amount_atomic'],amountDecimals=6,feeAtomic='15000000000000000',feeDecimals=18,txHash=tx,receiptStatus='success',blockNumber='20',blockHash='0x'+'33'*32,finalizedBlockNumber='20',finalizedBlockHash='0x'+'33'*32,observedAt=now.isoformat().replace('+00:00','Z'),matchingTransferLogs=1,providerRequestId=request_id)
sql('SELECT chainsql.record_arc_observation_v1(%s,%s)',(tid,Json(e)))
r=shell('odoo_accounting.py','ACCOUNTING:',fixture['op_id'])
r.update(database=db,verified_at=datetime.now(timezone.utc).isoformat(),receipt_source='synthetic fixture; no network transfer')
(ROOT/'milestone3/evidence/odoo.json').write_text(json.dumps(r,indent=2)+'\n')
for c in r['checks']:print('PASS:',c)
print('Bill payment state after explicit ORM reconciliation:',r['bill_payment_state'])
