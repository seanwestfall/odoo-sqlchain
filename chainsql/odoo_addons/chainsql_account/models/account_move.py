import hashlib
import json
from decimal import Decimal
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    chainsql_wallet_id = fields.Many2one('chainsql.wallet.approval', check_company=True,
        domain="[('company_id', '=', company_id), ('partner_id', '=', partner_id)]", copy=False,
        groups='chainsql_base.group_operator')
    chainsql_operation_ids = fields.One2many('chainsql.operation', 'move_id', copy=False, groups='chainsql_base.group_operator')

    user_can_approve_chainsql = fields.Boolean(compute='_compute_chainsql_approver')

    @api.depends_context('uid')
    def _compute_chainsql_approver(self):
        for rec in self:
            rec.user_can_approve_chainsql = self.env.user.has_group('chainsql_base.group_approver')

    @api.model_create_multi
    def create(self, vals_list):
        if any(v.get('chainsql_wallet_id', self.env.context.get('default_chainsql_wallet_id')) for v in vals_list) and not self.env.user.has_group('chainsql_base.group_approver'):
            raise AccessError('Only a ChainSQL approver may select the recipient wallet.')
        return super().create(vals_list)

    def _chainsql_lock(self):
        self.ensure_one()
        self.check_access('write')
        if not self.env.user.has_group('chainsql_base.group_operator'):
            raise AccessError('A ChainSQL operator role is required.')
        self.env.cr.execute('SELECT id FROM account_move WHERE id = %s FOR UPDATE', [self.id])
        self.invalidate_recordset()

    def _chainsql_snapshot(self):
        self.ensure_one()
        wallet = self.chainsql_wallet_id
        wallet.check_access('read')
        if (self.move_type != 'in_invoice' or self.state != 'posted'
                or self.currency_id.name != 'USD' or self.amount_residual <= 0):
            raise UserError('Use a posted USD vendor bill with a positive outstanding balance.')
        if (not wallet or wallet.company_id != self.company_id or wallet.partner_id != self.partner_id
                or wallet.state != 'approved'):
            raise UserError('Select an approved wallet for this vendor and this company.')
        atomic = Decimal(str(self.amount_residual)) * 1_000_000
        if atomic != atomic.to_integral_value():
            raise UserError('Amount cannot be represented exactly in 6 decimal atomic units.')
        return {'company_id': self.company_id.id, 'bill_id': self.id, 'bill_reference': self.name,
                'vendor_id': self.partner_id.id, 'vendor_reference': self.ref or '',
                'due_date': str(self.invoice_date_due or ''),
                'currency_id': self.currency_id.id, 'amount_atomic': str(int(atomic)),
                'asset': wallet.asset, 'decimals': 6, 'network': wallet.network,
                'recipient': wallet.recipient, 'wallet_id': wallet.id, 'wallet_version': wallet.version,
                'policy_version': 'mock-v1'}

    def action_chainsql_prepare(self):
        self._chainsql_lock()
        snapshot = self._chainsql_snapshot()
        fingerprint = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
        ops = self.chainsql_operation_ids.sorted('revision', reverse=True)
        op = ops[:1]
        if not op or op.fingerprint != fingerprint or op.state == 'stale':
            ops.filtered(lambda r: r.state in ('review', 'approved'))._invalidate('Bill payment details changed.')
            op = self.env['chainsql.operation']._create_request(dict(
                company_id=self.company_id.id, move_id=self.id, bill_reference=self.name,
                revision=(ops[:1].revision or 0) + 1, fingerprint=fingerprint, request=snapshot,
                wallet_id=self.chainsql_wallet_id.id,
                **{k: snapshot[k] for k in ['amount_atomic', 'asset', 'recipient', 'network', 'policy_version']}))
        return {'type': 'ir.actions.act_window', 'res_model': 'chainsql.operation',
                'res_id': op.id, 'view_mode': 'form', 'target': 'current'}

    def action_chainsql_queue(self):
        self._chainsql_lock()
        op = self.chainsql_operation_ids.sorted('revision', reverse=True)[:1]
        if not op:
            raise UserError('Prepare and approve a test request first.')
        op.action_queue()
        return {'type': 'ir.actions.act_window', 'res_model': 'chainsql.operation',
                'res_id': op.id, 'view_mode': 'form', 'target': 'current'}

    def write(self, vals):
        if 'chainsql_wallet_id' in vals and not self.env.user.has_group('chainsql_base.group_approver'):
            raise AccessError('Only a ChainSQL approver may select the recipient wallet.')
        result = super().write(vals)
        material = {'partner_id', 'company_id', 'currency_id', 'ref', 'name', 'state',
                    'invoice_line_ids', 'line_ids', 'invoice_date_due', 'chainsql_wallet_id'}
        if set(vals) & material:
            # Internal invalidation must also run for accounting users without a ChainSQL role.
            self.sudo().mapped('chainsql_operation_ids').filtered(
                lambda r: r.state in ('review', 'approved'))._invalidate('Bill details changed; prepare a new request.')
        return result


class Operation(models.Model):
    _inherit = 'chainsql.operation'
    move_id = fields.Many2one('account.move', required=True, check_company=True, ondelete='restrict', index=True)
    _revision_unique = models.Constraint('UNIQUE(move_id, revision)', 'Request revision already exists.')

    @api.depends('approval_outcome', 'move_id.amount_residual', 'move_id.state',
                 'move_id.partner_id', 'move_id.ref', 'move_id.currency_id',
                 'move_id.invoice_date_due', 'move_id.chainsql_wallet_id',
                 'wallet_id.state', 'wallet_id.version')
    def _compute_approval_current(self):
        return super()._compute_approval_current()

    def _current_matches(self):
        try:
            return self.move_id._chainsql_snapshot() == self.request
        except (UserError, AccessError):
            return False

    def _validate_current(self):
        self.ensure_one()
        self.move_id._chainsql_lock()
        # Serialize with wallet edits without granting the operator wallet-write authority.
        self.wallet_id.check_access('read')
        self.env.cr.execute('SELECT id FROM chainsql_wallet_approval WHERE id = %s FOR UPDATE', [self.wallet_id.id])
        self.wallet_id.invalidate_recordset()
        self.invalidate_recordset()
        snapshot = self.move_id._chainsql_snapshot()
        fingerprint = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
        if fingerprint != self.fingerprint or snapshot != self.request:
            raise UserError('Payment details changed. Prepare and approve a new request.')
