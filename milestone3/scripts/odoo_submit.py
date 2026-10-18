import json,os
from odoo import api
env=api.Environment(env.cr,env.ref('base.user_admin').id,{'allowed_company_ids':[env.ref('base.main_company').id]})
op=env['chainsql.operation'].browse(int(os.environ['M3_OP_ID']))
op.action_request_boundary_transfer();tid=op.boundary_transfer_id
op.action_request_boundary_transfer();assert op.boundary_transfer_id==tid
assert not op.arc_payment_id
env.cr.commit()
print('TRANSFER:'+json.dumps({'id':tid}))
