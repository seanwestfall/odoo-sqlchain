"""Observe, replay exact authorization, link via ORM, and save public evidence."""
from pathlib import Path
import sys,json,subprocess
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'chainsql/x402'))
from controller import ResourceController
v=json.loads((ROOT/'.local/milestone4/pilot.json').read_text());c=json.loads((ROOT/'.local/milestone4/boundary.json').read_text());x=ResourceController(c)
tid=v['purchase_id'];s,r,fp,blob,digest=x.call('SELECT * FROM chainsql.resource_material_v1(%s)',(tid,));auth=x.decrypt(blob,digest,tid)
observed=x.run(tid,reconcile_only=True);assert observed['payment_state']=='confirmed'
replay=x.provider('redeliver',s,r,fp,dict(auth,transaction=observed['transaction']))
assert replay['settlement']['transaction']==observed['transaction'];assert replay['delivery']['demonstration'] is True
again=x.run(tid,reconcile_only=True);assert again['transaction']==observed['transaction']
assert x.call('SELECT * FROM chainsql.resource_material_v1(%s)',(tid,))[4]==digest
code='''from odoo import api
import json
env=api.Environment(env.cr,env.ref('base.user_admin').id,{'allowed_company_ids':[1]})
op=env['chainsql.operation'].browse(OP_ID)
before=(op.move_id.payment_state,op.move_id.amount_residual,op.boundary_transfer_id)
op.action_sync_resources();op.action_sync_resources()
p=op.resource_purchase_ids.filtered(lambda p:p.purchase_id=='TID')
assert p.payment_state=='confirmed' and p.delivery_state=='delivered'
assert (op.move_id.payment_state,op.move_id.amount_residual,op.boundary_transfer_id)==before
env.cr.commit()
print('LINKED:'+json.dumps({'operation_id':op.id,'bill_id':op.move_id.id,'bill_reference':op.move_id.name,'purchase_record_id':p.id,'payment_state':p.payment_state,'delivery_state':p.delivery_state,'bill_payment_state':op.move_id.payment_state,'bill_residual':op.move_id.amount_residual,'payment_reference':p.payment_reference,'resource_result':p.resource_result}))
'''.replace('OP_ID',str(v['operation_id'])).replace('TID',tid)
p=subprocess.run(['docker','compose','-f',str(ROOT/'milestone0/compose.yaml'),'exec','-T','odoo','odoo','shell','-d','chainsql_m0','--no-http','--log-level=critical'],input=code,text=True,capture_output=True,check=True)
linked=json.loads(next(line[7:] for line in p.stdout.splitlines() if line.startswith('LINKED:')))
evidence=dict(purchase_id=tid,observation=again,odoo=linked,replay_same_transaction=True,authorization_digest_unchanged=True,authorization_digest=digest,request=r,independent_merchant=False)
(ROOT/'milestone4/evidence/live.json').write_text(json.dumps(evidence,indent=2));print(json.dumps(evidence,indent=2))
