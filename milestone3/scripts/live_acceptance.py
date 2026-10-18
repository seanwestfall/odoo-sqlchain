"""Trusted single-bill testnet acceptance harness. Never usable by the delegated worker role.
Run only after prepare_pilot.py and funding. Exact approved amount is 0.01 test USDC.
"""
from contextlib import closing
from datetime import datetime,timedelta,timezone
import json,sys,subprocess,time
from pathlib import Path
import psycopg2
from psycopg2.extras import Json
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'chainsql/arc'))
from controller import ArcController,NodeProvider
local=root/'.local/milestone3'
pilot=json.loads((local/'pilot.json').read_text());conf=json.loads((local/'boundary.json').read_text())
provider=NodeProvider(conf['node'],conf['script'],conf['env_file'])
controller=ArcController(conf['signer'],conf['observer'],provider,conf['journal_directory'],conf['tenant'])
admin=dict(host=str(root/'.local/milestone0/socket'),port=55432,dbname='chainsql_m0',user='m0_admin')
def sql(q,args=(),policy=False,worker=False):
 d=json.loads((local/'worker.json').read_text()) if worker else admin
 with closing(psycopg2.connect(**d)) as c:
  with c:
   with c.cursor() as cr:
    if policy:cr.execute('SET LOCAL ROLE chainsql_policy')
    cr.execute(q,args);return cr.fetchone() if cr.description else None
compose=['docker','compose','-f',str(root/'milestone0/compose.yaml'),'-f',str(root/'milestone2/compose.yaml')]
def shell(code):
 r=subprocess.run(compose+['run','--rm','-T','odoo','odoo','shell','-d','chainsql_m0','--no-http','--log-level=critical'],input=code,text=True,capture_output=True)
 if r.returncode:raise RuntimeError('Odoo action failed; inspect local development logs before retry')
 return json.loads(next(l.removeprefix('LIVE:') for l in r.stdout.splitlines() if l.startswith('LIVE:')))
prefix="from odoo import api\nimport json\nenv=api.Environment(env.cr,env.ref('base.user_admin').id,{'allowed_company_ids':[env.ref('base.main_company').id]})\nop=env['chainsql.operation'].browse("+str(pilot['op_id'])+")\n"
policy_path=local/'pilot-policy.json'
if policy_path.exists():s=json.loads(policy_path.read_text())['snapshot']
else:
 now=datetime.now(timezone.utc)
 s={k:v for k,v in pilot.items() if k not in ['op_id','bill_id','bill_reference']}
 s.update(network='eip155:5042002',asset='USDC',interface='arc-erc20-6-fee18',fee_ceiling_atomic='50000000000000000',
  policy_version='boundary-v1',approval_identity='local-development-pilot-administrator',valid_from=(now-timedelta(seconds=1)).isoformat().replace('+00:00','Z'),valid_until=(now+timedelta(hours=23)).isoformat().replace('+00:00','Z'))
 assert s['amount_atomic']=='10000' and s['tenant']=='odoo:chainsql_m0:1:arc'
 # Read-only provider preflight before granting execution permission.
 provider('prepare',s)
 for scope in ['*',s['source_wallet']]:sql('SELECT chainsql.set_budget_v1(%s,%s,10000,50000000000000000,10000,50000000000000000)',(s['tenant'],scope),True)
 sql('SELECT chainsql.set_wallet_v1(%s,%s,%s,true)',(s['tenant'],s['source_wallet'],'chainsql_odoo'),True)
 aid=sql('SELECT chainsql.approve_transfer_v1(%s)',(Json(s),),True)[0]
 policy_path.write_text(json.dumps({'snapshot':s,'approval_id':str(aid)},indent=2)+'\n');policy_path.chmod(0o600)
# This is the explicitly bounded development policy, never an ordinary worker capability.
sql('SELECT chainsql.enable_arc_v1(true)',policy=True);sql('SELECT chainsql.set_pause_v1(false)',policy=True)
queued=shell(prefix+"op.action_request_boundary_transfer()\nenv.cr.commit()\nprint('LIVE:'+json.dumps({'transfer_id':op.boundary_transfer_id}))\n")
tid=queued['transfer_id']
existing=sql('SELECT state FROM chainsql.transfers WHERE id=%s',(tid,))[0]
if existing=='observed':result=controller.reconcile(tid)
else:
 _,token,fence,_=sql('SELECT * FROM chainsql.claim_transfer_v1(%s)',(tid,),worker=True)
 controller.prepare(tid,str(token),fence)
 # Intentionally discard submission response to exercise recovery by durable hash.
 controller.submit(tid,str(token),fence)
 controller=ArcController(conf['signer'],conf['observer'],provider,conf['journal_directory'],conf['tenant'])
 result=controller.reconcile(tid)
 for _ in range(5):
  if result['state'] in ('confirmed','reverted'):break
  time.sleep(2);result=controller.reconcile(tid)
 if result['state']!='confirmed':
  (root/'milestone3/evidence/live-pending.json').write_text(json.dumps(result,indent=2)+'\n')
  raise SystemExit('Original attempt remains pending/reverted. Reconcile it; do not create a replacement.')
# Lookup original receipt through adapter replay; submit returns before raw broadcast when found.
snapshot,plan,auth=controller.material(tid)
replay=provider('submit',snapshot,plan,auth)
assert replay['state']=='receipt_available' and replay['txHash']==result['txHash']
linked=shell(prefix+"op.action_sync_boundary()\nbefore={'payment_id':op.arc_payment_id.id,'bill_balance':op.move_id.amount_residual,'bill_state':op.move_id.payment_state}\nop.action_record_arc_payment()\npayment_id=op.arc_payment_id.id\nop.action_record_arc_payment()\nassert op.arc_payment_id.id==payment_id\nassert op.move_id.payment_state=='in_payment'\nenv.cr.commit()\nprint('LIVE:'+json.dumps({'before_accounting':before,'payment_id':payment_id,'bill_state':op.move_id.payment_state,'fee_move_id':op.arc_fee_move_id.id,'accounting_mapping':op.arc_accounting_mapping}))\n")
sql('SELECT chainsql.enable_arc_v1(false)',policy=True)
evidence=dict(observed_at=datetime.now(timezone.utc).isoformat(),**pilot,transfer_id=tid,receipt=result,replay=replay,
 submission_response_discarded=True,recovered_with_new_controller=True,odoo=linked,execution_disabled_after_acceptance=True)
(root/'milestone3/evidence/live.json').write_text(json.dumps(evidence,indent=2)+'\n')
print(json.dumps(evidence,indent=2))
