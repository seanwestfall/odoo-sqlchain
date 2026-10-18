from odoo import api,Command
from odoo.exceptions import AccessError,UserError
import json,os
env=api.Environment(env.cr,env.ref('base.user_admin').id,{'allowed_company_ids':[1]})
op=env['chainsql.operation'].browse(int(os.environ['M4_OPERATION_ID']))
checks=[]
before=set(op.resource_purchase_ids.ids)
class Rollback(Exception):pass
try:
 with env.cr.savepoint():
  op.action_queue_resource();tid=(op.resource_purchase_ids.filtered(lambda p:p.id not in before)).purchase_id
  assert tid
  raise Rollback()
except Rollback:pass
op.invalidate_recordset(['resource_purchase_ids'])
assert set(op.resource_purchase_ids.ids)==before
# Queue rollback must also remove the SQL job.
try:
 with env.cr.savepoint():env.cr.execute('SELECT chainsql.resource_status_v1(%s)',(tid,))
except Exception as error:
 assert getattr(error,'pgcode',None)=='P0002'
else:raise AssertionError('rolled-back SQL job survived')
# Safe status lookup through the app-owned ORM link cannot find the rolled-back job.
checks.append('rolled-back Odoo queue leaves no resource link')
op.action_queue_resource();purchase=op.resource_purchase_ids.filtered(lambda p:p.id not in before);assert len(purchase)==1
op.action_queue_resource();assert op.resource_purchase_ids.filtered(lambda p:p.id not in before)==purchase;checks.append('double click returns the same resource purchase')
for f in [lambda:purchase.write({'amount_atomic':'1'}),lambda:env['chainsql.resource.purchase'].create({'operation_id':op.id,'company_id':1,'purchase_id':'forged'})]:
 try:f()
 except AccessError:pass
 else:raise AssertionError('immutable purchase API allowed mutation')
checks.append('ordinary create/write cannot forge resource evidence')
try:
 with env.cr.savepoint():
  company=env['res.company'].sudo().create({'name':'M4 isolated company test'})
  user=env['res.users'].sudo().create({'name':'M4 other company','login':'m4-company-test','company_id':company.id,'company_ids':[Command.set(company.ids)],'group_ids':[Command.set([env.ref('chainsql_base.group_operator').id])]})
  foreign=purchase.with_user(user).with_context(allowed_company_ids=company.ids)
  try:foreign.read(['purchase_id'])
  except AccessError:checks.append('other company cannot inspect purchase')
  else:raise AssertionError('cross-company leak')
  try:foreign.action_sync()
  except AccessError:checks.append('other company cannot synchronize purchase')
  else:raise AssertionError('cross-company sync')
  raise Rollback()
except Rollback:pass
# Editing the bill invalidates the independent purchase approval transactionally.
try:
 with env.cr.savepoint():
  op.move_id.write({'ref':(op.move_id.ref or '')+' M4 rollback test'})
  env.flush_all()
  env.cr.execute('SELECT * FROM chainsql.approved_resource_v1(%s,%s)',(f'odoo:{env.cr.dbname}:1:x402',f'account.move:{op.move_id.id}'))
  assert not env.cr.fetchone();checks.append('material bill edit revokes resource approval')
  raise Rollback()
except Rollback:pass
env.cr.commit()
print('PURCHASE:'+json.dumps({'purchase_id':purchase.purchase_id,'odoo_purchase_id':purchase.id,'operation_id':op.id,'bill_id':op.move_id.id,'checks':checks}))
