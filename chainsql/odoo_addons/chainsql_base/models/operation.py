import json
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError


class Operation(models.Model):
    _name = 'chainsql.operation'
    _description = 'Immutable ChainSQL request and observed mock result'
    _rec_name = 'bill_reference'
    _order = 'id desc'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, index=True)
    bill_reference = fields.Char(required=True)
    revision = fields.Integer(required=True)
    fingerprint = fields.Char(required=True)
    request = fields.Json(required=True)
    wallet_id = fields.Many2one('chainsql.wallet.approval', required=True, check_company=True)
    amount_atomic = fields.Char(required=True, help='Integer atomic units, 6 decimals. Simulation only.')
    asset = fields.Char(required=True)
    recipient = fields.Char(required=True)
    network = fields.Char(required=True)
    policy_version = fields.Char(required=True, default='mock-v1')
    recommendation = fields.Char(default='Simulate only')
    explanation = fields.Text(default='Exercise the integration queue. No funds move and no accounting entries are created.')
    approval_outcome = fields.Selection([('pending', 'Pending'), ('approved', 'Approved for simulation'), ('stale', 'Invalidated')], default='pending')
    approval_current = fields.Boolean(compute='_compute_approval_current', string='Approval still valid')
    approved_by = fields.Many2one('res.users')
    approved_at = fields.Datetime()
    state = fields.Selection([('review', 'Needs approval'), ('approved', 'Approved'), ('queued', 'Queued'), ('running', 'Running'), ('observed', 'Simulated result observed'), ('stale', 'Stale request'), ('error', 'Needs review')], default='review', index=True)
    operation_id = fields.Char(index=True)
    receipt_reference = fields.Char()
    resource_purchases = fields.Json(default=list)
    result = fields.Json()
    review_reason = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError('Prepare requests from the originating bill.')

    def write(self, vals):
        raise AccessError('Requests are immutable. Use the authorized operation actions.')

    def _create_request(self, vals):
        # RPC context defaults must never supply approval/execution metadata.
        vals = dict(vals, state='review', approval_outcome='pending', approved_by=False,
                    approved_at=False, operation_id=False, receipt_reference=False,
                    resource_purchases=[], result=False, review_reason=False,
                    recommendation='Simulate only',
                    explanation='Exercise the integration queue. No funds move and no accounting entries are created.')
        return super().create(vals)

    def _update(self, vals):
        return super().write(vals)

    def _invalidate(self, reason):
        return self._update({'state': 'stale', 'approval_outcome': 'stale', 'review_reason': reason})

    def _authorize(self, approver=False):
        self.check_access('write')
        group = 'chainsql_base.group_approver' if approver else 'chainsql_base.group_operator'
        if not self.env.user.has_group(group):
            raise AccessError('This ChainSQL action requires the appropriate role.')

    def _compute_approval_current(self):
        for rec in self:
            rec.approval_current = rec.approval_outcome == 'approved' and rec._current_matches()

    def _current_matches(self):
        return False

    def _validate_current(self):
        raise UserError('No originating ERP adapter is installed for this operation.')

    def action_approve(self):
        self.ensure_one()
        self._authorize(approver=True)
        self._validate_current()
        if self.state != 'review':
            raise UserError('Only a current request awaiting review can be approved.')
        self._update({'state': 'approved', 'approval_outcome': 'approved',
                      'approved_by': self.env.uid, 'approved_at': fields.Datetime.now()})
        return True

    def action_queue(self):
        self.ensure_one()
        self._authorize()
        self._validate_current()
        if self.operation_id:
            return True
        if self.state != 'approved' or self.approval_outcome != 'approved':
            raise UserError('An approver must approve this request before queueing.')
        payload = dict(self.request, fingerprint=self.fingerprint, request_revision=self.revision,
                       odoo_operation_id=self.id, mode='mock-v1')
        key = f'odoo-mock:{self.id}:{self.fingerprint}'
        # Same cursor and transaction as the Odoo request: never commit here.
        self.env.cr.execute('SELECT chainsql.enqueue_probe(%s::jsonb, %s)::text', [json.dumps(payload), key])
        operation_id = self.env.cr.fetchone()[0]
        self._update({'operation_id': operation_id, 'state': 'queued'})
        return True

    def action_sync(self):
        self._authorize()
        for rec in self:
            if not rec.operation_id or rec.state in ('observed', 'error'):
                continue
            self.env.cr.execute('SELECT state, payload, result FROM chainsql.probe_status(%s::uuid)', [rec.operation_id])
            row = self.env.cr.fetchone()
            if not row:
                raise UserError('Queue operation was not found for this database role.')
            state, payload, result = row
            if payload.get('fingerprint') != rec.fingerprint or payload.get('odoo_operation_id') != rec.id:
                rec._update({'state': 'error', 'review_reason': 'Queue request identity mismatch.'})
            elif state == 'observed':
                valid = (isinstance(result, dict) and result.get('mode') == 'mock-v1'
                         and result.get('fingerprint') == rec.fingerprint
                         and result.get('operation_id') == rec.operation_id
                         and result.get('status') == 'simulated'
                         and result.get('amount_atomic') == rec.amount_atomic
                         and result.get('recipient') == rec.recipient
                         and result.get('network') == rec.network
                         and result.get('asset') == rec.asset
                         and result.get('resource_purchases') == []
                         and result.get('receipt_reference') == 'mock:' + rec.operation_id)
                rec._update({'state': 'observed' if valid else 'error', 'result': result,
                             'receipt_reference': result.get('receipt_reference') if valid else False,
                             'resource_purchases': [],
                             'review_reason': 'Simulation only; no blockchain transfer or accounting posting.' if valid else 'Worker result failed request validation.'})
            elif state == 'running':
                rec._update({'state': 'running'})
        return True
