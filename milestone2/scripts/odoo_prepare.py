import json
from odoo import api
assert env.cr.dbname.startswith('chainsql_m2_odoo_')
company=env.ref('base.main_company')
env=api.Environment(env.cr,env.ref('base.user_admin').id,{'allowed_company_ids':[company.id]})
source=env['account.move'].search([('move_type','=','in_invoice'),('state','=','posted'),('amount_residual','>',0)],limit=1)
bill=source.copy({'ref':'Milestone 2 isolated acceptance fixture','invoice_date':source.invoice_date})
bill.action_post()
wallet=env['chainsql.wallet.approval'].create({'name':'M2 isolated test wallet','company_id':company.id,
    'partner_id':bill.partner_id.id,'recipient':'mock:m2-recipient'})
wallet.action_approve()
bill.write({'chainsql_wallet_id':wallet.id})
op=env['chainsql.operation'].browse(bill.action_chainsql_prepare()['res_id']);op.action_approve()
env.cr.commit()
print('FIXTURE:'+json.dumps({'op_id':op.id,'bill_id':bill.id,'tenant':f'odoo:{env.cr.dbname}:{company.id}',
    'business_reference':f'account.move:{bill.id}','request_revision':str(op.revision),
    'destination':op.recipient,'amount_atomic':op.amount_atomic}))
