import json,os
from odoo import api
assert env.cr.dbname.startswith('chainsql_m2_odoo_')
company=env.ref('base.main_company')
env=api.Environment(env.cr,env.ref('base.user_admin').id,{'allowed_company_ids':[company.id]})
op=env['chainsql.operation'].browse(int(os.environ['M2_OP_ID']))
bill=op.move_id
wallet=bill.chainsql_wallet_id
checks=[]
def approved():
    env.cr.execute('SELECT * FROM chainsql.approved_transfer_v1(%s,%s)',(f'odoo:{env.cr.dbname}:{company.id}',f'account.move:{bill.id}'))
    return env.cr.fetchone()
assert approved()
class RollbackTest(Exception):pass
for label,sql,args in [
    ('stored balance recomputation invalidates SQL approval','UPDATE account_move SET amount_residual=amount_residual-1 WHERE id=%s',(bill.id,)),
    ('recipient edit invalidates SQL approval','UPDATE chainsql_wallet_approval SET recipient=%s WHERE id=%s',('mock:changed',wallet.id))]:
    try:
        with env.cr.savepoint():
            env.cr.execute(sql,args)
            assert not approved(),label
            raise RollbackTest()
    except RollbackTest:pass
    assert approved(),'rolled back source edit must also roll back revocation'
    checks.append(label)
wallet.write({'recipient':'mock:changed-and-committed'})
env.flush_all()
assert not approved()
env.cr.commit()
checks.append('committed recipient edit revokes independently issued approval')
print('INVALIDATION:'+json.dumps(checks))
