import base64,os,uuid
from pathlib import Path
from datetime import timedelta
from odoo import api,fields,models
from odoo.exceptions import AccessError,UserError
from ..proof import digest,commitment,seal,unseal,verify

def key():
    path=os.environ.get('CHAINSQL_DOCUMENT_KEY_FILE')
    if not path:raise UserError('Configure a private document encryption key file first.')
    value=Path(path).read_bytes()
    if len(value)!=32:raise UserError('Document key must contain 32 random bytes.')
    return value

class Document(models.Model):
    _name='chainsql.document.version'
    _description='Immutable encrypted document snapshot'
    _rec_name='version_id'
    _check_company_auto=True
    version_id=fields.Char(required=True,readonly=True,index=True)
    company_id=fields.Many2one('res.company',required=True,index=True)
    move_id=fields.Many2one('account.move',required=True,check_company=True,ondelete='restrict')
    source_attachment_id=fields.Many2one('ir.attachment',ondelete='set null',readonly=True)
    source_version=fields.Char(required=True,readonly=True)
    source_reference=fields.Char(required=True,readonly=True)
    sha256=fields.Char(required=True,readonly=True)
    commitment=fields.Char(required=True,readonly=True)
    ciphertext=fields.Binary(attachment=False,readonly=True,groups='chainsql_base.group_approver')
    retain_until=fields.Datetime(required=True,readonly=True)
    approved_by=fields.Many2one('res.users',readonly=True)
    approved_at=fields.Datetime(readonly=True)
    purged=fields.Boolean(readonly=True)
    _version_unique=models.Constraint('UNIQUE(version_id)','Version identity is unique.')
    @api.model_create_multi
    def create(self,values):raise AccessError('Snapshot an authorized bill attachment instead.')
    def write(self,values):raise AccessError('Document versions are immutable.')
    def unlink(self):raise AccessError('Retain document audit metadata.')
    def _authorize(self,approver=False):
        self.check_access('read')
        self.mapped('move_id').check_access('read')
        if not self.env.user.has_group('chainsql_base.group_approver' if approver else 'chainsql_base.group_operator'):raise AccessError('Document role required.')
    def action_approve(self):
        self.ensure_one();self._authorize(True)
        self.env.cr.execute('SELECT id FROM chainsql_document_version WHERE id=%s FOR UPDATE',(self.id,))
        self.invalidate_recordset()
        if self.purged or self.retain_until<=fields.Datetime.now():raise UserError('Retained content has expired.')
        if not self.approved_by:super().write({'approved_by':self.env.uid,'approved_at':fields.Datetime.now()})
        return True
    def _bytes(self):
        self.ensure_one();self._authorize(True)
        if self.purged or self.retain_until<=fields.Datetime.now():raise UserError('Snapshot expired or purged.')
        data=unseal(key(),base64.b64decode(self.ciphertext),self.version_id)
        if not verify(data[32:],self.sha256,data[:32],self.commitment):raise UserError('Snapshot integrity failed.')
        return data[:32],data[32:]
    def action_export_approved(self):
        self.ensure_one();self._authorize(True)
        if not self.approved_by:raise UserError('Approve this exact version before exporting to the private seller.')
        salt,data=self._bytes()
        return dict(company=str(self.company_id.id),source=self.source_reference,version=self.version_id,
            sha256=self.sha256,commitment=self.commitment,salt=salt.hex(),bytes_b64=base64.b64encode(data).decode(),
            retain_until=self.retain_until.isoformat()+'Z',approved_by=f'odoo:{self.env.cr.dbname}:user:{self.approved_by.id}')
    def action_verify_source(self):
        self.ensure_one();self._authorize()
        a=self.source_attachment_id
        a.check_access('read');self.move_id.check_access('read')
        matches=bool(a and digest(a.raw or b'')==self.sha256)
        return {'type':'ir.actions.client','tag':'display_notification','params':{'title':'Exact-byte comparison','message':'Source bytes match the retained version.' if matches else 'Source bytes changed or are unavailable. The retained version is unchanged.','type':'success' if matches else 'warning','sticky':True}}
    def action_purge(self):
        self.ensure_one();self._authorize(True)
        if self.retain_until>fields.Datetime.now():raise UserError('Retention period has not elapsed.')
        super().write({'ciphertext':False,'purged':True})
        return True

class Bill(models.Model):
    _inherit='account.move'
    chainsql_document_ids=fields.One2many('chainsql.document.version','move_id',groups='chainsql_base.group_operator')
    def action_snapshot_document(self,attachment_id):
        self.ensure_one();self.check_access('read')
        if not self.env.user.has_group('chainsql_base.group_approver'):raise AccessError('Approver role required for private snapshots.')
        a=self.env['ir.attachment'].browse(attachment_id).exists();a.check_access('read')
        if not a or a.res_model!='account.move' or a.res_id!=self.id or a.type!='binary' or (a.company_id and a.company_id!=self.company_id):raise AccessError('Attachment is not authorized for this bill.')
        data=a.raw or b''
        if len(data)>1024*1024:raise UserError('Pilot snapshots are limited to 1 MiB.')
        identity=str(uuid.uuid4());salt=os.urandom(32)
        v=super(Document,self.env['chainsql.document.version'].with_context({})).create(dict(version_id=identity,company_id=self.company_id.id,move_id=self.id,
            source_attachment_id=a.id,source_reference=f'account.move:{self.id}/attachment:{a.id}',source_version=str(a.write_date),sha256=digest(data),commitment=commitment(data,salt),
            ciphertext=base64.b64encode(seal(key(),salt+data,identity)),retain_until=fields.Datetime.now()+timedelta(days=30),approved_by=False,approved_at=False,purged=False))
        return {'type':'ir.actions.act_window','res_model':v._name,'res_id':v.id,'view_mode':'form'}
    def action_snapshot_bill_attachments(self):
        self.ensure_one()
        items=self.env['ir.attachment'].search([('res_model','=','account.move'),('res_id','=',self.id),('type','=','binary')])
        if not items:raise UserError('Attach a document to this bill first.')
        if len(items)>10:raise UserError('Use the explicit attachment action when more than ten documents are attached.')
        result=None
        for item in items:result=self.action_snapshot_document(item.id)
        return result
