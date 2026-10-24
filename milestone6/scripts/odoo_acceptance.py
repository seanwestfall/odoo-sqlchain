"""Run through Odoo shell in the disposable M6 database."""
import base64,json
from odoo import api,fields
from odoo.exceptions import AccessError,UserError
from datetime import timedelta
env=api.Environment(env.cr,2,{'allowed_company_ids':[1]})
checks=[]
def check(name,value):
    assert value,name
    checks.append(name)
def denied(name,fn):
    try:
        with env.cr.savepoint():fn()
    except (AccessError,UserError):checks.append(name)
    else:raise AssertionError(name)
bill=env['account.move'].browse(70).exists()
assert bill
raw=b'ChainSQL SYNTHETIC private certificate; no real supplier data.\r\nVersion 1\x00'
a=env['ir.attachment'].create({'name':'M6 synthetic certificate.bin','type':'binary','raw':raw,'mimetype':'application/octet-stream','res_model':'account.move','res_id':bill.id,'company_id':bill.company_id.id})
action=bill.with_context(default_approved_by=2).action_snapshot_document(a.id)
v=env['chainsql.document.version'].browse(action['res_id'])
check('snapshot starts unapproved despite injected default',not v.approved_by)
denied('unapproved export denied',v.action_export_approved)
v.action_approve();export=v.action_export_approved()
check('exact bytes exported',base64.b64decode(export['bytes_b64'])==raw)
check('source initially matches',v.action_verify_source()['params']['type']=='success')
a.write({'raw':raw+b'edited'})
check('changed source detected',v.action_verify_source()['params']['type']=='warning')
check('approved version survives source edit',v.action_export_approved()==export)
denied('immutable snapshot fields',lambda:v.write({'sha256':'bad'}))
denied('early purge denied',v.action_purge)
other=env['res.company'].create({'name':'M6 isolated acceptance company'})
u=env['res.users'].with_context(no_reset_password=True).create({'name':'M6 other-company approver','login':'m6-other-'+v.version_id,'company_id':other.id,'company_ids':[(6,0,[other.id])],'group_ids':[(6,0,[env.ref('chainsql_base.group_approver').id])]})
foreign=v.with_user(u).with_context(allowed_company_ids=[other.id])
denied('other company cannot read',lambda:foreign.read(['sha256']))
denied('other company cannot approve',foreign.action_approve)
denied('other company cannot export',foreign.action_export_approved)
operator=env['res.users'].with_context(no_reset_password=True).create({'name':'M6 operator','login':'m6-reader-'+v.version_id,'company_id':bill.company_id.id,'company_ids':[(6,0,[bill.company_id.id])],'group_ids':[(6,0,[env.ref('chainsql_base.group_operator').id])]})
r=v.with_user(operator)
denied('operator cannot export private content',r.action_export_approved)
denied('operator cannot read ciphertext',lambda:r.read(['ciphertext']))
second=env['chainsql.document.version'].browse(bill.action_snapshot_document(a.id)['res_id'])
from odoo.addons.chainsql_document_account.models.document import Document
super(Document,second).write({'retain_until':fields.Datetime.now()-timedelta(seconds=1)})
second.action_purge()
check('expired snapshot purged with metadata retained',second.purged and not second.ciphertext and second.sha256)
check('original Odoo attachment separately retained',bool(a.raw))
env.cr.commit()
print('EVIDENCE:'+json.dumps({'bill_id':bill.id,'document_id':v.id,'checks':checks,'synthetic':True}))
print('PRIVATE_EXPORT:'+json.dumps(export))
