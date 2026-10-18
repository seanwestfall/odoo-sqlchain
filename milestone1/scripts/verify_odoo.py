"""Execute with Odoo shell in a disposable clone; intentionally commits test fixtures."""
import concurrent.futures
import importlib.util
import json
import time
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import psycopg2
from odoo import api
from odoo.exceptions import AccessError, UserError

checks = []
def check(name, value=True):
    assert value, name
    checks.append(name)
    print('PASS:', name, flush=True)

def denied(name, fn):
    try:
        with env.cr.savepoint():
            fn()
    except (AccessError, UserError):
        check(name)
    else:
        raise AssertionError(name)

assert env.cr.dbname.startswith('chainsql_m1_verify_'), 'Run only in a fresh verification clone.'
admin = env.ref('base.user_admin')
env = api.Environment(env.cr, admin.id, {})
bill = env['account.move'].search([('move_type','=','in_invoice'), ('state','=','posted'), ('amount_residual','>',0)], limit=1)
assert bill
company = bill.company_id
env = env(context=dict(env.context, allowed_company_ids=[company.id]))
bill = env['account.move'].browse(bill.id).copy({'ref': 'ChainSQL verification fixture', 'invoice_date': bill.invoice_date})
bill.action_post()
wallet = env['chainsql.wallet.approval'].with_context(default_state='approved', default_approved_by=admin.id).create(dict(name='Verification wallet', company_id=company.id,
    partner_id=bill.partner_id.id, recipient='mock:vendor-verification'))
check('context defaults cannot forge wallet approval',wallet.state == 'draft' and not wallet.approved_by)
wallet.action_approve()
bill.write({'chainsql_wallet_id': wallet.id})
op = env['chainsql.operation'].browse(bill.with_context(default_state='approved', default_approval_outcome='approved', default_operation_id='forged', default_approved_by=admin.id).action_chainsql_prepare()['res_id'])
check('context defaults cannot bypass request approval',op.state == 'review' and op.approval_outcome == 'pending' and not op.operation_id and not op.approved_by)
check('real posted vendor bill prepares immutable revision 1', op.revision == 1 and op.request['bill_id'] == bill.id)
denied('cannot queue without request approval', op.action_queue)
denied('RPC cannot change immutable amount', lambda: op.write({'amount_atomic': '1'}))
denied('RPC cannot forge an operation', lambda: env['chainsql.operation'].create({'company_id': company.id}))
denied('RPC cannot forge wallet approval metadata', lambda: wallet.write({'state': 'approved'}))
op.action_approve()
check('authorized approval records actor and policy', op.approved_by == admin and op.policy_version == 'mock-v1' and op.approval_current)

other = env['res.company'].create({'name': 'ChainSQL isolated verification company'})
other_user = env['res.users'].with_context(no_reset_password=True).create(dict(name='ChainSQL other company',
    login='chainsql-isolation-verification', company_id=other.id, company_ids=[(6,0,[other.id])],
    group_ids=[(6,0,[env.ref('chainsql_base.group_approver').id,env.ref('account.group_account_invoice').id])]))
foreign_op = op.with_user(other_user).with_context(allowed_company_ids=[other.id])
denied('another company cannot read operation', lambda: foreign_op.read(['request']))
denied('another company cannot approve operation', foreign_op.action_approve)
denied('another company cannot queue operation', foreign_op.action_queue)
denied('another company cannot sync operation', foreign_op.action_sync)
denied('another company cannot read wallet approval', lambda: wallet.with_user(other_user).with_context(allowed_company_ids=[other.id]).read(['recipient']))
check('shared vendor grants no cross-company wallet visibility', not env['chainsql.wallet.approval'].with_user(other_user).with_context(allowed_company_ids=[other.id]).search([('partner_id','=',bill.partner_id.id)]))
denied('another company cannot spoof allowed companies', lambda: foreign_op.with_context(allowed_company_ids=[company.id]).read(['request']))
operator = env['res.users'].with_context(no_reset_password=True).create(dict(name='ChainSQL operator verification',
    login='chainsql-operator-verification', company_id=company.id, company_ids=[(6,0,[company.id])],
    group_ids=[(6,0,[env.ref('chainsql_base.group_operator').id,env.ref('account.group_account_invoice').id])]))
denied('operator cannot approve operation', op.with_user(operator).action_approve)
denied('operator cannot edit wallet', lambda: wallet.with_user(operator).write({'recipient':'mock:evil'}))
denied('operator cannot change bill recipient', lambda: bill.with_user(operator).write({'chainsql_wallet_id':False}))

# Persist fixtures before testing independent connections and committed visibility.
env.cr.commit()
conf=json.loads(Path('/run/chainsql/worker.json').read_text())
conf['dbname']=env.cr.dbname
worker=psycopg2.connect(**conf)
worker.autocommit=False
try:
    with worker:
        with worker.cursor() as cur:
            cur.execute('SELECT id FROM account_move LIMIT 1')
except psycopg2.errors.InsufficientPrivilege:
    check('mock worker cannot read Odoo accounting tables')
else:
    raise AssertionError('Worker can read Odoo tables')
class RollbackProbe(Exception): pass
try:
    with env.cr.savepoint():
        op.action_queue()
        rolled_id = op.operation_id
        with worker:
            with worker.cursor() as cur:
                cur.execute('SELECT id::text FROM chainsql.claim_probe()')
                assert not cur.fetchall(), 'Uncommitted job became visible'
        raise RollbackProbe()
except RollbackProbe:
    pass
env.invalidate_all()
env.cr.execute('SELECT state FROM chainsql.probe_status(%s::uuid)', [rolled_id])
check('rolling back the Odoo action leaves no SQL job', not env.cr.fetchall() and not op.operation_id)
check('worker cannot observe a job before Odoo commit')
env.cr.commit()

registry=env.registry
op_id=op.id
company_id=company.id
operator_id=operator.id
# Independent Odoo transactions exercise real concurrent double clicks and framework-style retries.
def enqueue(_):
    for attempt in range(8):
        try:
            with registry.cursor() as cr:
                e=api.Environment(cr, operator_id, {'allowed_company_ids':[company_id]})
                o=e['chainsql.operation'].browse(op_id)
                o.action_queue()
                result=o.operation_id
                cr.commit()
                return result
        except psycopg2.errors.SerializationFailure:
            time.sleep(0.03)
    raise AssertionError('Serialization retries exhausted')
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    ids=list(pool.map(enqueue, range(4)))
check('four concurrent double-click requests return one obligation', len(set(ids)) == 1)
env.cr.rollback()
env.invalidate_all()
op=env['chainsql.operation'].browse(op_id)
check('repeat preparation returns original revision', bill.action_chainsql_prepare()['res_id'] == op.id)
spec=importlib.util.spec_from_file_location('mock_worker','/app/mock_worker.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as config_file:
    json.dump(conf, config_file);config_file.flush()
    run=subprocess.run([sys.executable, '/app/mock_worker.py', '--config', config_file.name, '--once'],
                       text=True, capture_output=True, check=True)
check('separate worker process observes committed request', 'Observed mock operation '+ids[0] in run.stdout)
check('worker has no duplicate job', not module.process_one(worker))
env.cr.rollback();env.invalidate_all()
accounting_before=bill.read(['state','amount_residual','payment_state','line_ids'])[0]
op.action_sync()
check('Odoo sync verifies and displays mock receipt', op.state == 'observed' and op.receipt_reference == 'mock:'+op.operation_id)
check('mock operation leaves accounting unchanged', bill.read(['state','amount_residual','payment_state','line_ids'])[0] == accounting_before)
check('request snapshot remains immutable after completion', op.request['amount_atomic'] == op.amount_atomic)

# Changes invalidate approvals, including direct accounting changes caught at queue time.
bill.write({'ref':'Material change verification'})
op2=env['chainsql.operation'].browse(bill.action_chainsql_prepare()['res_id']);op2.action_approve()
wallet.write({'recipient':'mock:changed'})
check('wallet changes invalidate wallet and request approval', wallet.state == 'draft' and op2.state == 'stale' and op2.approval_outcome == 'stale')
denied('stale wallet cannot be queued',op2.action_queue)
wallet.action_approve()
op3=env['chainsql.operation'].browse(bill.action_chainsql_prepare()['res_id']);op3.action_approve()
bill.write({'ref':'Second material change'})
check('bill changes invalidate pending approval',op3.state == 'stale')
denied('stale bill request cannot queue',op3.action_queue)
check('old revision snapshot survives material changes',op.request['vendor_reference'] != bill.ref)
op4=env['chainsql.operation'].browse(bill.action_chainsql_prepare()['res_id']);op4.action_approve()
# Model a residual recomputation from reconciliation without calling account.move.write.
# This is deliberately a test-only SQL mutation, rolled back below.
env.flush_all()
env.cr.execute('UPDATE account_move SET amount_residual = amount_residual - 1 WHERE id = %s', [bill.id])
bill.invalidate_recordset(['amount_residual']);op4.invalidate_recordset(['approval_current'])
check('balance change invalidates effective approval without a bill write',not op4.approval_current)
denied('balance changed after approval cannot queue',op4.action_queue)
worker.close()
env.cr.rollback()
print('EVIDENCE_JSON:'+json.dumps({'verified_at':datetime.now(timezone.utc).isoformat(), 'database':env.cr.dbname,
    'checks':checks,'checks_passed':len(checks),'bill_id':bill.id,'operation_id':ids[0]}))
