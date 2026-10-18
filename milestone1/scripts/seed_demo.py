"""Odoo shell: create a labelled disposable demo bill and company-specific mock wallet."""
from odoo import api
assert env.cr.dbname == 'chainsql_m0'
company=env.ref('base.main_company')
env=api.Environment(env.cr,env.ref('base.user_admin').id,{'allowed_company_ids':[company.id]})
bill=env['account.move'].search([('ref','=','ChainSQL Milestone 1 demo'),('company_id','=',company.id)],limit=1)
if not bill:
    source=env['account.move'].search([('move_type','=','in_invoice'),('state','=','posted'),('amount_residual','>',0)],limit=1)
    assert source, 'A posted disposable demo vendor bill is required.'
    bill=source.copy({'ref':'ChainSQL Milestone 1 demo','invoice_date':source.invoice_date})
    bill.action_post()
wallet=env['chainsql.wallet.approval'].search([('name','=','Milestone 1 simulation wallet'),('company_id','=',company.id),('partner_id','=',bill.partner_id.id)],limit=1)
if not wallet:
    wallet=env['chainsql.wallet.approval'].create({'name':'Milestone 1 simulation wallet',
        'company_id':company.id,'partner_id':bill.partner_id.id,'recipient':'mock:ready-mat'})
    wallet.action_approve()
if bill.chainsql_wallet_id != wallet:
    bill.write({'chainsql_wallet_id':wallet.id})
env.cr.commit()
print('DEMO_BILL:',bill.id,bill.name,'company',company.id,'wallet',wallet.id)
