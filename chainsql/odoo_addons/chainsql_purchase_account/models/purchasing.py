import json
import re
from decimal import Decimal
from datetime import timedelta
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from ..decision import ACTIONS, VERSION, decide, fingerprint


def atomic(value):
    value = Decimal(str(value)) * 1000000
    if value != value.to_integral_value():
        raise UserError('The pilot requires exact six-decimal USD amounts.')
    return str(int(value))


def normalize(value):
    return re.sub(r'\s+', '', (value or '').casefold())


def revoke(bills):
    """Trusted invalidation only: no data is returned to the caller or agent."""
    for bill in bills.sudo():
        for suffix in ('', ':arc', ':x402'):
            bill.env.cr.execute('SELECT chainsql.invalidate_business_v1(%s,%s)',
                                (f'odoo:{bill.env.cr.dbname}:{bill.company_id.id}{suffix}', f'account.move:{bill.id}'))


class Policy(models.Model):
    _name = 'chainsql.purchase.policy'
    _description = 'Company delegated purchasing policy'
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)
    name = fields.Char(default='USD purchasing pilot', required=True)
    enabled = fields.Boolean(default=False)
    limit_atomic = fields.Char(default='10000000', required=True, help='Per-operation USD/USDC atomic limit, six decimals.')
    budget_atomic = fields.Char(default='100000000', required=True, help='Cumulative delegated queue allowance; independent signer budgets still apply.')
    used_atomic = fields.Char(default='0', readonly=True, required=True)
    approval_hours = fields.Integer(default=24, required=True)
    version = fields.Integer(default=1, readonly=True)
    _company_unique = models.Constraint('UNIQUE(company_id)', 'One purchasing policy per company.')

    def _authorize(self):
        if not self.env.user.has_group('chainsql_base.group_approver'):
            raise AccessError('Only an approver can configure delegated policy.')

    @api.constrains('limit_atomic', 'budget_atomic', 'approval_hours')
    def _validate_policy(self):
        for p in self:
            if any(not re.fullmatch(r'(0|[1-9][0-9]{0,17})', v or '') for v in [p.limit_atomic, p.budget_atomic]) or not 1 <= p.approval_hours <= 168:
                raise ValidationError('Use nonnegative integer atomic limits and 1–168 approval hours.')

    @api.model_create_multi
    def create(self, values):
        self._authorize()
        clean = []
        for v in values:
            company = v.get('company_id', self.env.company.id)
            if company not in self.env.companies.ids: raise AccessError('Company is not authorized.')
            if set(v) & {'version', 'used_atomic'}: raise AccessError('Policy counters are controlled.')
            clean.append(dict(v, company_id=company, version=1, used_atomic='0'))
        return super(Policy, self.with_context({})).create(clean)

    def write(self, values):
        self._authorize(); self.check_access('write')
        if set(values) & {'used_atomic', 'version', 'company_id'}: raise AccessError('Policy identity and counters are controlled.')
        self.env.cr.execute('SELECT id FROM chainsql_purchase_policy WHERE id=ANY(%s) ORDER BY id FOR UPDATE', (self.ids,))
        self.invalidate_recordset()
        for p in self:
            super(Policy, p).write(dict(values, version=p.version+1))
            revoke(self.env['account.move'].sudo().search([('company_id', '=', p.company_id.id), ('move_type', '=', 'in_invoice'), ('state', '=', 'posted')]))
        return True

    def unlink(self): raise AccessError('Retain purchasing policy history.')


class Decision(models.Model):
    _name = 'chainsql.purchase.decision'
    _description = 'Purchasing recommendation and enforced outcome'
    _order = 'id desc'
    _check_company_auto = True
    operation_id = fields.Many2one('chainsql.operation', required=True, check_company=True, ondelete='restrict')
    company_id = fields.Many2one('res.company', required=True)
    evidence = fields.Json(required=True)
    evidence_hash = fields.Char(required=True)
    policy_id = fields.Many2one('chainsql.purchase.policy', required=True, check_company=True)
    policy_revision = fields.Integer(required=True)
    model_version = fields.Char(required=True)
    proposed_action = fields.Selection([(x, x.replace('_', ' ').title()) for x in ACTIONS], required=True)
    defer_until = fields.Date()
    justification = fields.Text(required=True)
    baseline = fields.Json(required=True)
    policy_outcome = fields.Selection([(x,x.replace('_',' ').title()) for x in ['blocked','advisory','human_required','delegated_eligible']], required=True)
    policy_version = fields.Char(required=True)
    human_choice = fields.Selection([(x,x.replace('_',' ').title()) for x in ACTIONS])
    human_reason = fields.Text()
    human_by = fields.Many2one('res.users')
    executed = fields.Boolean(default=False)
    execution_reference = fields.Char()
    created_by = fields.Many2one('res.users', required=True)

    @api.model_create_multi
    def create(self, vals): raise AccessError('Use the controlled recommendation action.')
    def write(self, vals): raise AccessError('Decisions are immutable; record a human assessment through its action.')
    def unlink(self): raise AccessError('Retain decision evidence.')

    def action_assess(self, choice, reason):
        self.ensure_one(); self.operation_id._authorize(approver=True); self.check_access('write')
        if choice not in ACTIONS or not isinstance(reason, str) or not 1 <= len(reason) <= 1000: raise UserError('Supply a structured choice and concise reason.')
        self.env.cr.execute('SELECT id FROM chainsql_purchase_decision WHERE id=%s FOR UPDATE', (self.id,))
        self.invalidate_recordset()
        if self.executed: raise UserError('Cannot assess an already executed decision.')
        if self.human_by: raise UserError('Human assessment already recorded. Create a new decision for a new assessment.')
        super().write(dict(human_choice=choice, human_reason=reason, human_by=self.env.uid))
        return True

    def action_human_pay(self):
        return self.action_assess('pay_now', 'Human reviewed the recorded purchasing evidence and chose payment.')

    def action_human_hold(self):
        return self.action_assess('hold', 'Human chose to hold this operation for review.')

    def action_execute(self):
        self.ensure_one(); self.operation_id._authorize(); self.check_access('write')
        self.env.cr.execute('SELECT id FROM chainsql_purchase_decision WHERE id=%s FOR UPDATE', (self.id,))
        self.invalidate_recordset()
        if self.executed: return True
        self._validate_execution()
        op = self.operation_id
        if op.operation_id or op.boundary_transfer_id:
            raise UserError('This operation already has an obligation; reconcile it instead of executing a new decision.')
        # Existing request methods retain independent approval, idempotency, reservation and dispatch gates.
        if op.network == 'mock:local':
            super(Operation, op).action_queue()
            reference = op.operation_id
        else:
            super(Operation, op).action_request_boundary_transfer()
            reference = op.boundary_transfer_id
        if not reference: raise UserError('No committed queue reference was produced.')
        policy = self.policy_id
        super(Policy, policy).write({'used_atomic': str(int(policy.used_atomic)+int(op.amount_atomic))})
        super().write({'executed': True, 'execution_reference': reference})
        return True

    def _validate_execution(self):
        self.operation_id._validate_current()
        p = self.policy_id
        p.check_access('read')
        self.env.cr.execute('SELECT id FROM chainsql_purchase_policy WHERE id=%s FOR UPDATE', (p.id,))
        p.invalidate_recordset()
        fresh = self.operation_id._purchasing_evidence(p)
        if self.policy_revision != p.version or fingerprint(fresh) != self.evidence_hash:
            raise UserError('Evidence, time, budget or policy changed. Generate and review a fresh recommendation.')
        result = decide(fresh, {'enabled':p.enabled, 'limit_atomic':p.limit_atomic})
        if self.proposed_action != 'pay_now' or result['baseline']['action'] != 'pay_now':
            raise UserError('Payment is blocked by purchasing evidence.')
        if self.human_choice and self.human_choice != 'pay_now': raise UserError('Human assessment does not authorize payment.')
        if result['policy_outcome'] != 'delegated_eligible' and not (self.human_choice=='pay_now' and self.human_by):
            raise UserError('An approver must review this threshold exception.')


class Operation(models.Model):
    _inherit = 'chainsql.operation'
    purchase_decision_ids = fields.One2many('chainsql.purchase.decision', 'operation_id', readonly=True)

    def _create_request(self, vals):
        return super()._create_request(dict(vals, purchase_decision_ids=False))

    def _purchasing_evidence(self, policy):
        """Allowlisted ORM evidence only. No sudo, document text, attachment bytes or SQL reads."""
        self.ensure_one(); self._authorize(); self.move_id.check_access('read'); policy.check_access('read')
        bill = self.move_id
        if policy.company_id != self.company_id: raise AccessError('Wrong policy company.')
        lines = bill.invoice_line_ids.filtered(lambda x: x.display_type == 'product')
        lines.check_access('read')
        candidates = self.env['account.move'].search([('company_id','=',bill.company_id.id), ('commercial_partner_id','=',bill.commercial_partner_id.id), ('move_type','=','in_invoice'), ('state','!=','cancel'), ('id','!=',bill.id)])
        duplicates = candidates.filtered(lambda x: normalize(bill.ref) and normalize(x.ref)==normalize(bill.ref))
        purchases=[]; missing=[]; inconsistent=[]; unlinked=[]
        for line in lines:
            po = line.purchase_line_id
            if not po: unlinked.append(line.id); continue
            po.check_access('read'); po.order_id.check_access('read')
            moves = po.move_ids
            moves.check_access('read')
            if (po.company_id != bill.company_id or po.order_id.currency_id != bill.currency_id or
                po.product_uom_id != line.product_uom_id or set(po.tax_ids.ids) != set(line.tax_ids.ids) or po.order_id.state != 'purchase' or
                line.product_id != po.product_id or line.quantity <= 0 or
                po.qty_invoiced > po.product_qty + 0.000001 or
                abs(line.price_subtotal / line.quantity - po.price_subtotal / (po.product_qty or 1)) > bill.currency_id.rounding):
                inconsistent.append(line.id)
            if po.qty_received + 0.000001 < max(po.qty_invoiced, line.quantity): missing.append(line.id)
            purchases.append(dict(bill_line_id=line.id, purchase_line_id=po.id, order_id=po.order_id.id,
                bill_quantity=str(line.quantity), bill_subtotal=str(line.price_subtotal), purchase_subtotal=str(po.price_subtotal), tax_ids=sorted(line.tax_ids.ids),
                ordered=str(po.product_qty), billed=str(po.qty_invoiced), received=str(po.qty_received),
                receipt_moves=[dict(id=m.id, state=m.state, quantity=str(m.quantity)) for m in moves.sorted('id')],
                invoice_status=po.order_id.invoice_status))
        today = fields.Date.context_today(self)
        discount_dates = bill.line_ids.filtered(lambda x: x.discount_date and x.discount_date >= today).mapped('discount_date')
        approved = bool(self.approval_outcome=='approved' and self._current_matches() and self.approved_at and
                        self.approved_at + timedelta(hours=policy.approval_hours) > fields.Datetime.now())
        # Read only through the restricted SQL command, not tables, for independent execution approval validity.
        if self.network != 'mock:local':
            self.env.cr.execute('SELECT * FROM chainsql.approved_transfer_v1(%s,%s)', (self._boundary_tenant(), f'account.move:{bill.id}'))
            authority = self.env.cr.fetchone()
            approved = approved and bool(authority)
        indicators = {name: str(bill[name]) for name in ('should_be_paid',) if name in bill._fields}
        return dict(company_id=bill.company_id.id, bill_id=bill.id, operation_id=self.id,
            operation_fingerprint=self.fingerprint, today=today.isoformat(), due_date=str(bill.invoice_date_due or ''),
            discount_date=str(min(discount_dates)) if discount_dates else None,
            amount_atomic=atomic(bill.amount_residual), available_atomic=str(max(0,int(policy.budget_atomic)-int(policy.used_atomic))),
            budget_source='company_delegated_queue_allowance', existing_obligation=bool(self.operation_id or self.boundary_transfer_id), approval_current=approved,
            eligible_bill=bill.state=='posted' and bill.move_type=='in_invoice' and bill.currency_id.name=='USD' and bill.amount_residual>0 and bill.currency_id.compare_amounts(bill.amount_residual,bill.amount_total)==0,
            duplicate_ids=duplicates.ids, inconsistent=inconsistent, missing_receipts=missing, unlinked_lines=unlinked,
            purchase_lines=purchases, matching_indicators=indicators)

    def action_recommend_purchase(self, proposal=None, model_version=None):
        self.ensure_one(); self._authorize()
        p = self.env['chainsql.purchase.policy'].search([('company_id','=',self.company_id.id)], limit=1)
        if not p: raise UserError('An approver must configure a purchasing policy for this company.')
        e = self._purchasing_evidence(p)
        if proposal is not None and (not isinstance(model_version, str) or not re.fullmatch(r'[A-Za-z0-9._:/-]{1,100}', model_version)):
            raise UserError('Advisory proposals must identify their model and version.')
        try: result = decide(e, {'enabled':p.enabled,'limit_atomic':p.limit_atomic}, proposal)
        except (ValueError, TypeError) as exc: raise UserError(str(exc)) from None
        values = dict(result, operation_id=self.id, company_id=self.company_id.id, evidence=e,
            evidence_hash=fingerprint(e), policy_id=p.id, policy_revision=p.version,
            model_version=model_version if proposal is not None else 'deterministic-planner-v1',
            created_by=self.env.uid, executed=False, execution_reference=False, human_choice=False, human_reason=False, human_by=False)
        d = super(Decision, self.env['chainsql.purchase.decision'].with_context({})).create(values)
        return {'type':'ir.actions.act_window', 'res_model':d._name, 'res_id':d.id, 'view_mode':'form'}

    def action_purchase_evidence(self):
        self.ensure_one(); self._authorize()
        p = self.env['chainsql.purchase.policy'].search([('company_id','=',self.company_id.id)], limit=1)
        if not p: raise UserError('No purchasing policy configured.')
        return self._purchasing_evidence(p)

    def action_queue(self):
        raise UserError('Use the purchasing decision Execute action; evidence must be rechecked.')

    def action_request_boundary_transfer(self):
        raise UserError('Use the purchasing decision Execute action; independent payment approval is still required.')


class PurchaseLine(models.Model):
    _inherit = 'purchase.order.line'
    def write(self, vals):
        result = super().write(vals)
        if set(vals) & {'product_qty','price_unit','discount','tax_ids','product_id','product_uom_id','qty_received','qty_invoiced','order_id'}:
            revoke(self.sudo().invoice_lines.move_id)
        return result


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'
    def write(self, vals):
        result = super().write(vals)
        if set(vals) & {'state','partner_id','currency_id','company_id'}: revoke(self.sudo().order_line.invoice_lines.move_id)
        return result


class StockMove(models.Model):
    _inherit = 'stock.move'
    def write(self, vals):
        old = self.sudo().purchase_line_id.invoice_lines.move_id
        result = super().write(vals)
        if set(vals) & {'state','quantity','product_uom_qty','purchase_line_id','location_id','location_dest_id'}:
            revoke(old | self.sudo().purchase_line_id.invoice_lines.move_id)
        return result


class Bill(models.Model):
    _inherit = 'account.move'

    def _purchase_duplicate_peers(self):
        # Invalidation is privileged, but no peer evidence is disclosed by this helper.
        peers = self.env['account.move'].sudo().browse()
        for b in self.sudo().filtered(lambda x: x.move_type=='in_invoice'):
            if b.ref:
                candidates = peers.search([('company_id','=',b.company_id.id),('commercial_partner_id','=',b.commercial_partner_id.id),('move_type','=','in_invoice')])
                peers |= candidates.filtered(lambda x: normalize(x.ref)==normalize(b.ref))
        return peers

    @api.model_create_multi
    def create(self, values):
        bills = super().create(values)
        revoke(bills._purchase_duplicate_peers())
        return bills

    def write(self, values):
        material = bool(set(values) & {'ref','partner_id','company_id','state','move_type','invoice_line_ids','line_ids','invoice_payment_term_id'})
        peers = self._purchase_duplicate_peers() if material else self.browse()
        result = super().write(values)
        if material: revoke(peers | self._purchase_duplicate_peers() | self)
        return result

    def unlink(self):
        peers = self._purchase_duplicate_peers()
        revoke(peers)
        return super().unlink()


class BillLine(models.Model):
    _inherit = 'account.move.line'

    def write(self, values):
        bills = self.sudo().move_id
        result = super().write(values)
        if set(values) & {'purchase_line_id','product_id','quantity','price_unit','discount','tax_ids','product_uom_id','move_id','date_maturity','discount_date','discount_balance'}:
            revoke(bills | self.sudo().move_id)
        return result

    def unlink(self):
        revoke(self.sudo().move_id)
        return super().unlink()
