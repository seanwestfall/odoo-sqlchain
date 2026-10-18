"""Create a single, explicitly labelled development bill. No chain or accounting payment here."""
import json,os
from odoo import api,Command,fields
assert env.cr.dbname=='chainsql_m0'
company=env.ref('base.main_company')
env=api.Environment(env.cr,env.ref('base.user_admin').id,{'allowed_company_ids':[company.id]})
reference='ChainSQL Milestone 3 — 0.01 USDC Arc acceptance'
bill=env['account.move'].search([('ref','=',reference),('company_id','=',company.id)],limit=1)
if not bill:
 source=env['account.move'].search([('move_type','=','in_invoice'),('state','=','posted'),('company_id','=',company.id)],limit=1)
 account=source.invoice_line_ids.filtered(lambda l:l.account_id)[:1].account_id
 bill=env['account.move'].create({'move_type':'in_invoice','partner_id':source.partner_id.id,'journal_id':source.journal_id.id,'company_id':company.id,'currency_id':company.currency_id.id,'ref':reference,'invoice_date':fields.Date.today(),'invoice_line_ids':[Command.create({
  'name':'Arc testnet acceptance — demonstration only','quantity':1,'price_unit':0.01,'account_id':account.id,'tax_ids':[Command.clear()]})]})
 bill.action_post()
wallet=env['chainsql.wallet.approval'].search([('name','=','Arc M3 acceptance recipient'),('company_id','=',company.id)],limit=1)
if not wallet:
 wallet=env['chainsql.wallet.approval'].create({'name':'Arc M3 acceptance recipient','company_id':company.id,'partner_id':bill.partner_id.id,
  'network':'eip155:5042002','recipient':os.environ['ARC_RECIPIENT']})
 wallet.action_approve()
assert wallet.recipient==os.environ['ARC_RECIPIENT']
if bill.chainsql_wallet_id!=wallet:bill.chainsql_wallet_id=wallet
op=env['chainsql.operation'].browse(bill.action_chainsql_prepare()['res_id'])
if op.state=='review':op.action_approve()
assert op.amount_atomic=='10000'
config=env['chainsql.arc.journal'].search([('company_id','=',company.id)],limit=1)
if not config:
 def account(code,name,kind,reconcile=False):
  return env['account.account'].create({'name':name,'code':code,'account_type':kind,'reconcile':reconcile,'company_ids':[Command.link(company.id)]})
 clearing=account('999301','Arc outstanding test payments','asset_current',True)
 fee_clearing=account('999302','Arc gas test clearing','asset_current',True)
 expense=account('999303','Arc gas test expense','expense')
 journal=env['account.journal'].create({'name':'Arc TEST only','code':'ARCT','type':'bank','company_id':company.id})
 method=journal.outbound_payment_method_line_ids.filtered(lambda m:m.code=='manual')[:1];method.payment_account_id=clearing
 fee_journal=env['account.journal'].create({'name':'Arc TEST fees','code':'ARCF','type':'general','company_id':company.id})
 config=env['chainsql.arc.journal'].create({'company_id':company.id,'journal_id':journal.id,'method_id':method.id,'fee_journal_id':fee_journal.id,
  'fee_expense_id':expense.id,'fee_clearing_id':fee_clearing.id})
config._check_mapping()
env.cr.commit()
print('PILOT:'+json.dumps({'op_id':op.id,'bill_id':bill.id,'bill_reference':bill.name,'tenant':op._boundary_tenant(),
 'business_reference':f'account.move:{bill.id}','request_revision':str(op.revision),'destination':op.recipient,'amount_atomic':op.amount_atomic}))
