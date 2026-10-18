"""Trusted policy-operator setup for ONE 0.01 Base Sepolia test-USDC purchase."""
from pathlib import Path
from datetime import datetime,timedelta,timezone
import json,subprocess
import psycopg2
from psycopg2.extras import Json
ROOT=Path(__file__).resolve().parents[2]
p=ROOT/'.local/milestone4/pilot.json'
if p.exists():raise SystemExit('Existing pilot retained: reconcile it; do not generate a new purchase.')
r=subprocess.run(['docker','compose','-f',str(ROOT/'milestone0/compose.yaml'),'exec','-T','odoo','odoo','shell','-d','chainsql_m0','--no-http','--log-level=critical'],input=(ROOT/'milestone4/scripts/inspect_odoo.py').read_text(),text=True,capture_output=True,check=True)
ops=json.loads(next(x[11:] for x in r.stdout.splitlines() if x.startswith('OPERATIONS:')))
op=next(o for o in ops if o['current'] and o['approval']=='approved')
state=json.loads((ROOT/'.local/circle_wallet/circle-setup.json').read_text());sender=state['wallets'][0];recipient=state['wallets'][1]['address']
now=datetime.now(timezone.utc)
s=dict(tenant='odoo:chainsql_m0:1:x402',business_reference=f"account.move:{op['bill']}",request_revision=str(op['revision']),source_wallet=sender['id'],destination=recipient,network='eip155:84532',asset='USDC',interface='x402-eip3009-6',amount_atomic='10000',fee_ceiling_atomic='0',policy_version='boundary-v1',approval_identity='milestone4-user-authorized-test-purchase',valid_from=(now-timedelta(seconds=5)).isoformat().replace('+00:00','Z'),valid_until=(now+timedelta(minutes=30)).isoformat().replace('+00:00','Z'))
spec=dict(url=f"http://127.0.0.1:8094/vendor-verification/{op['partner']}?version=1",method='GET',body='',resource_version='1',resource_key='demo-vendor-verification',operation_id=str(op['id']),operation_fingerprint=op['fingerprint'],scheme='exact',asset='0x036CbD53842c5426634e7929541eC2318f3dCF7e',domain_name='USDC',domain_version='2')
with psycopg2.connect(host=str(ROOT/'.local/milestone0/socket'),port=55432,user='m0_admin',dbname='chainsql_m0') as db:
 with db.cursor() as cur:
  cur.execute('SET LOCAL ROLE chainsql_policy')
  cur.execute('SELECT chainsql.set_wallet_v1(%s,%s,%s,true)',(s['tenant'],s['source_wallet'],'chainsql_odoo'))
  for scope in ['*',s['source_wallet']]:cur.execute('SELECT chainsql.set_budget_v1(%s,%s,10000,0,10000,0)',(s['tenant'],scope))
  cur.execute('SELECT chainsql.set_pause_v1(false)')
  cur.execute('SELECT chainsql.approve_resource_v1(%s,%s)',(Json(s),Json(spec)));aid=str(cur.fetchone()[0])
p.write_text(json.dumps(dict(operation=op,approval_id=aid,snapshot=s,request=spec),indent=2));p.chmod(0o600)
print('One resource approval issued for operation',op['id'],'bill',op['bill'],'amount 10000 atomic test USDC; no invoice payment authorized.')
