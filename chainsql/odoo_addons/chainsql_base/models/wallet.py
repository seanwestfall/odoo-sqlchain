from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


class WalletApproval(models.Model):
    _name = 'chainsql.wallet.approval'
    _description = 'Company-specific ChainSQL test wallet approval'
    _check_company_auto = True

    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, index=True)
    partner_id = fields.Many2one('res.partner', required=True, check_company=True)
    network = fields.Selection([('mock:local', 'Local simulation (no blockchain)')], required=True, default='mock:local')
    recipient = fields.Char(required=True, help='Simulation recipient identifier; never used to send funds.')
    asset = fields.Selection([('USDC', 'Simulated USDC (6 decimal units)')], required=True, default='USDC')
    version = fields.Integer(default=1, readonly=True)
    state = fields.Selection([('draft', 'Needs approval'), ('approved', 'Approved')], default='draft', readonly=True)
    approved_by = fields.Many2one('res.users', readonly=True)
    approved_at = fields.Datetime(readonly=True)

    def _authorize(self):
        if not self.env.user.has_group('chainsql_base.group_approver'):
            raise AccessError('Only a ChainSQL approver can change wallet approvals.')

    @api.model_create_multi
    def create(self, vals_list):
        self._authorize()
        for vals in vals_list:
            if set(vals) & {'state', 'version', 'approved_by', 'approved_at'}:
                raise AccessError('Approval metadata is controlled by approval actions.')
            if vals.get('company_id', self.env.company.id) not in self.env.companies.ids:
                raise AccessError('Company is outside the active companies.')
            vals.update(state='draft', version=1, approved_by=False, approved_at=False)
        return super().create(vals_list)

    def write(self, vals):
        self._authorize()
        self.check_access('write')
        if set(vals) & {'state', 'version', 'approved_by', 'approved_at'}:
            raise AccessError('Approval metadata is controlled by approval actions.')
        if 'company_id' in vals and any(r.company_id.id != vals['company_id'] for r in self):
            raise ValidationError('Create a separate wallet approval for another company.')
        for rec in self:
            rec._lock()
            super(WalletApproval, rec).write(dict(vals, state='draft', approved_by=False,
                                                approved_at=False, version=rec.version + 1))
            self.env['chainsql.operation'].search([('wallet_id', '=', rec.id),
                ('state', 'in', ['review', 'approved'])])._invalidate('Wallet details changed; prepare a new request.')
        return True

    def _lock(self):
        self.check_access('write')
        self.env.cr.execute('SELECT id FROM chainsql_wallet_approval WHERE id = ANY(%s) FOR UPDATE', [self.ids])
        self.invalidate_recordset()

    def action_approve(self):
        self._authorize()
        self._lock()
        return super().write({'state': 'approved', 'approved_by': self.env.uid, 'approved_at': fields.Datetime.now()})


class Partner(models.Model):
    _inherit = 'res.partner'
    chainsql_wallet_ids = fields.One2many('chainsql.wallet.approval', 'partner_id', groups='chainsql_base.group_operator')
