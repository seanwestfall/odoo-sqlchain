import json,os
from odoo import api,Command
from odoo.exceptions import UserError
assert env.cr.dbname.startswith('chainsql_m3_odoo_')
env=api.Environment(env.cr,env.ref('base.user_admin').id,{'allowed_company_ids':[env.ref('base.main_company').id]})
op=env['chainsql.operation'].browse(int(os.environ['M3_OP_ID']))
checks=[]
def check(name,cond):
 assert cond,name
 checks.append(name)
op.action_sync_boundary()
check('confirmed receipt does not create payment or change bill balance',not op.arc_payment_id and op.move_id.amount_residual>0)
try:
 with env.cr.savepoint():op.action_record_arc_payment()
except UserError:checks.append('accounting requires explicit journal configuration')
else:raise AssertionError('missing config accepted')
company=op.company_id

def account(code,name,kind,reconcile=False):
 return env['account.account'].create({'name':name,'code':code,'account_type':kind,'reconcile':reconcile,'company_ids':[Command.link(company.id)]})
clearing=account('999301','Arc outstanding test payments','asset_current',True)
fee_clearing=account('999302','Arc gas test clearing','asset_current',True)
expense=account('999303','Arc gas test expense','expense')
journal=env['account.journal'].create({'name':'Arc TEST only','code':'ARCT','type':'bank','company_id':company.id})
method=journal.outbound_payment_method_line_ids.filtered(lambda m:m.code=='manual')[:1]
method.payment_account_id=clearing
fee_journal=env['account.journal'].create({'name':'Arc TEST fees','code':'ARCF','type':'general','company_id':company.id})
config=env['chainsql.arc.journal'].create({'company_id':company.id,'journal_id':journal.id,'method_id':method.id,
 'fee_journal_id':fee_journal.id,'fee_expense_id':expense.id,'fee_clearing_id':fee_clearing.id})
# Roll back a material recipient edit and ensure the accounting path rejects it.
class Rollback(Exception):pass
try:
 with env.cr.savepoint():
  op.wallet_id.write({'recipient':'0x'+'44'*20})
  try:op.action_record_arc_payment()
  except UserError:checks.append('edited recipient blocks automatic accounting')
  else:raise AssertionError('changed recipient accepted')
  raise Rollback()
except Rollback:pass
op.invalidate_recordset();op.wallet_id.invalidate_recordset();op.move_id.invalidate_recordset()
op.action_record_arc_payment()
payment=op.arc_payment_id
check('ORM payment linked to operation',bool(payment) and payment.company_id==company)
check('payment remains outstanding, not paid',payment.state=='in_process')
check('bill stays In Payment until clearing',op.move_id.payment_state=='in_payment')
check('explicit action reconciles bill payable',op.move_id.amount_residual==0)
check('gas posted separately from vendor payment',bool(op.arc_fee_move_id) and op.arc_fee_move_id!=payment.move_id and payment.amount==float(int(op.amount_atomic)/1000000))
check('exact gas units retained',op.arc_fee_atomic=='15000000000000000')
check('fee rounding remainder explicit',op.arc_fee_rounding.startswith('-0.005'))
op.action_record_arc_payment()
check('repeat accounting action links same payment',op.arc_payment_id==payment)
check('mapping snapshot retained',op.arc_accounting_mapping['outstanding_account_id']==clearing.id)
env.cr.commit()
print('ACCOUNTING:'+json.dumps({'checks':checks,'bill_payment_state':op.move_id.payment_state,'payment_id':payment.id}))
