import json
from odoo import api,fields,models
from odoo.exceptions import AccessError,UserError

class Purchase(models.Model):
    _name='chainsql.resource.purchase'
    _description='Separate x402 resource expense (test USDC)'
    _rec_name='purchase_id'
    _check_company_auto=True
    operation_id=fields.Many2one('chainsql.operation',required=True,check_company=True,ondelete='restrict')
    company_id=fields.Many2one('res.company',required=True,index=True)
    purchase_id=fields.Char(required=True,readonly=True,index=True)
    request_fingerprint=fields.Char(readonly=True)
    request_revision=fields.Char(readonly=True)
    amount_atomic=fields.Char(readonly=True)
    network=fields.Char(readonly=True)
    asset=fields.Char(readonly=True)
    payment_state=fields.Char(readonly=True,default='queued')
    delivery_state=fields.Char(readonly=True,default='pending')
    payment_reference=fields.Char(readonly=True)
    resource_request=fields.Json(readonly=True)
    resource_result=fields.Json(readonly=True)
    evidence=fields.Json(readonly=True)
    _purchase_unique=models.Constraint('UNIQUE(purchase_id)','Purchase already linked.')

    @api.model_create_multi
    def create(self,vals):raise AccessError('Queue resource purchases from the originating operation.')
    def write(self,vals):raise AccessError('Use the controlled synchronization action.')
    def unlink(self):raise AccessError('Purchase evidence cannot be deleted.')
    def action_sync(self):
        for rec in self:
            rec.operation_id._authorize()
            rec.check_access('write')
            self.env.cr.execute('SELECT chainsql.resource_status_v1(%s)',(rec.purchase_id,))
            status=self.env.cr.fetchone()[0]
            if status['snapshot']['tenant']!=f'odoo:{self.env.cr.dbname}:{rec.company_id.id}:x402':raise AccessError('Wrong purchase company.')
            result=status.get('purchase') or {}
            super(Purchase,rec).write({'payment_state':result.get('payment_state',status['state']), 'delivery_state':result.get('delivery_state','pending'),
                'payment_reference':(result.get('evidence') or {}).get('transaction'), 'resource_result':result.get('result'),'evidence':result.get('evidence')})
        return True

class Operation(models.Model):
    _inherit='chainsql.operation'
    resource_purchase_ids=fields.One2many('chainsql.resource.purchase','operation_id',readonly=True)

    def _create_request(self,vals):
        return super()._create_request(dict(vals,resource_purchase_ids=False))

    def action_queue_resource(self):
        self.ensure_one();self._authorize();self._validate_current()
        if self.approval_outcome!='approved':raise UserError('Approve the current operation first.')
        # Lock this ORM row to serialize double-clicks and insertion of linked records.
        self.env.cr.execute('SELECT id FROM chainsql_operation WHERE id=%s FOR UPDATE',(self.id,))
        self.invalidate_recordset(['resource_purchase_ids'])
        if self.resource_purchase_ids:
            self.resource_purchase_ids.action_sync()
            if any(p.payment_state!='cancelled' for p in self.resource_purchase_ids):return True
        tenant=f'odoo:{self.env.cr.dbname}:{self.company_id.id}:x402'
        self.env.cr.execute('SELECT * FROM chainsql.approved_resource_v1(%s,%s)',(tenant,f'account.move:{self.move_id.id}'))
        row=self.env.cr.fetchone()
        if not row:raise UserError('An independent policy operator must authorize this resource expense and its exact endpoint, price and recipient.')
        aid,s,r,fp=row
        if r['operation_id']!=str(self.id) or r['operation_fingerprint']!=self.fingerprint:raise UserError('Resource approval refers to a stale operation.')
        self.env.cr.execute('SELECT chainsql.request_resource_v1(%s,%s,%s,%s)::text',(aid,json.dumps(s),json.dumps(r),f'x402:{self.id}:{fp}'))
        tid=self.env.cr.fetchone()[0]
        values=dict(operation_id=self.id,company_id=self.company_id.id,purchase_id=tid,request_fingerprint=fp,request_revision=s['request_revision'],amount_atomic=s['amount_atomic'],network=s['network'],asset='USDC (6 decimals)',resource_request=r,payment_state='requested',delivery_state='pending',payment_reference=False,resource_result=False,evidence=False)
        super(Purchase,self.env['chainsql.resource.purchase'].with_context({})).create(values)
        return True

    def action_sync_resources(self):
        self._authorize();return self.resource_purchase_ids.action_sync()
