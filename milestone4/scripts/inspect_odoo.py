from odoo import api
import json
env=api.Environment(env.cr,env.ref('base.user_admin').id,{'allowed_company_ids':[1]})
rows=[]
for op in env['chainsql.operation'].search([]):
 rows.append(dict(id=op.id,bill=op.move_id.id,partner=op.move_id.partner_id.id,revision=op.revision,fingerprint=op.fingerprint,approval=op.approval_outcome,current=op.approval_current,state=op.state))
print('OPERATIONS:'+json.dumps(rows))
