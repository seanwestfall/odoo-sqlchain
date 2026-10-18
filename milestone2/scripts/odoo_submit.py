import json,os
from odoo import api
from odoo.exceptions import AccessError
assert env.cr.dbname.startswith('chainsql_m2_odoo_')
company=env.ref('base.main_company')
env=api.Environment(env.cr,env.ref('base.user_admin').id,{'allowed_company_ids':[company.id]})
op=env['chainsql.operation'].browse(int(os.environ['M2_OP_ID']))
class RollbackTest(Exception):pass
try:
    with env.cr.savepoint():
        op.action_request_boundary_transfer()
        rolled_id=op.boundary_transfer_id
        raise RollbackTest()
except RollbackTest:pass
env.invalidate_all()
assert not op.boundary_transfer_id
try:
    with env.cr.savepoint():
        env.cr.execute('SELECT chainsql.transfer_status_v1(%s)',(rolled_id,))
except Exception:pass
else:raise AssertionError('Odoo rollback left a transfer job')
op.action_request_boundary_transfer()
first=op.boundary_transfer_id
op.action_request_boundary_transfer()
assert first==op.boundary_transfer_id
assert op.boundary_state=='requested'
other=env['res.company'].create({'name':'M2 other company'})
user=env['res.users'].with_context(no_reset_password=True).create({'name':'M2 isolated other user','login':'m2-isolation',
    'company_id':other.id,'company_ids':[(6,0,[other.id])],
    'group_ids':[(6,0,[env.ref('chainsql_base.group_approver').id,env.ref('account.group_account_invoice').id])]})
foreign=op.with_user(user).with_context(allowed_company_ids=[other.id])
for method in [foreign.action_request_boundary_transfer,foreign.action_sync_boundary,foreign.action_cancel_boundary]:
    try:
        with env.cr.savepoint():method()
    except AccessError:pass
    else:raise AssertionError('Cross-company boundary action succeeded')
env.cr.commit()
print('TRANSFER:'+json.dumps({'id':first,'checks':['Odoo rollback removes transfer request',
    'Odoo repeat submission returns same transfer','other company cannot submit, inspect or cancel boundary transfer']}))
