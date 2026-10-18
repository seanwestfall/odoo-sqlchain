from decimal import Decimal, ROUND_HALF_UP
import re
from odoo import api, fields, models, Command
from odoo.exceptions import UserError, ValidationError

class Configuration(models.Model):
    _name='chainsql.arc.journal'
    _description='Arc testnet demonstration accounting configuration'
    _check_company_auto=True
    name=fields.Char(required=True,default='Arc test USDC = demonstration USD')
    company_id=fields.Many2one('res.company',required=True,default=lambda s:s.env.company)
    journal_id=fields.Many2one('account.journal',required=True,check_company=True)
    method_id=fields.Many2one('account.payment.method.line',required=True,check_company=True)
    fee_journal_id=fields.Many2one('account.journal',required=True,check_company=True)
    fee_expense_id=fields.Many2one('account.account',required=True,check_company=True)
    fee_clearing_id=fields.Many2one('account.account',required=True,check_company=True)
    _company_unique=models.Constraint('UNIQUE(company_id)','One Arc pilot configuration per company.')

    @api.constrains('company_id','journal_id','method_id','fee_journal_id','fee_expense_id','fee_clearing_id')
    def _check_mapping(self):
        for c in self:
            if (c.company_id.currency_id.name!='USD' or c.journal_id.type!='bank'
                or (c.journal_id.currency_id and c.journal_id.currency_id.name!='USD')
                or c.method_id.journal_id!=c.journal_id or c.method_id.payment_type!='outbound'
                or c.method_id.code!='manual' or c.method_id.payment_account_id.account_type!='asset_current'
                or not c.method_id.payment_account_id.reconcile
                or c.fee_journal_id.type!='general' or c.fee_expense_id.account_type!='expense'
                or c.fee_clearing_id.account_type!='asset_current' or c.fee_expense_id==c.fee_clearing_id):
                raise ValidationError('Use USD, a bank journal with manual outbound payments and a reconcilable current-asset outstanding account, plus a general fee journal and separate expense/current-asset fee accounts.')

def _prevent_arc_removal(records):
    if records:raise UserError('Retain Arc wallet history; this addon cannot be removed while Arc wallets exist.')

class Wallet(models.Model):
    _inherit='chainsql.wallet.approval'
    network=fields.Selection(selection_add=[('eip155:5042002','Arc testnet — test USDC')],ondelete={'eip155:5042002':_prevent_arc_removal})
    recipient=fields.Char(help='Approved recipient; Arc requires a hexadecimal EVM address.')
    @api.constrains('network','recipient')
    def _check_arc_address(self):
        for w in self:
            if w.network=='eip155:5042002' and (not re.fullmatch(r'0x[0-9a-fA-F]{40}',w.recipient or '') or int(w.recipient,16)==0):
                raise ValidationError('Arc requires a nonzero EVM recipient address.')

class Bill(models.Model):
    _inherit='account.move'
    def _get_invoice_in_payment_state(self):
        if self.sudo().chainsql_operation_ids.filtered('arc_payment_id'):
            return 'in_payment'
        return super()._get_invoice_in_payment_state()

    def _chainsql_snapshot(self):
        s=super()._chainsql_snapshot()
        if s['network']=='eip155:5042002':s['policy_version']='arc-test-usd-v1'
        return s

class Operation(models.Model):
    _inherit='chainsql.operation'
    arc_payment_id=fields.Many2one('account.payment',readonly=True,copy=False,check_company=True)
    arc_fee_move_id=fields.Many2one('account.move',readonly=True,copy=False,check_company=True)
    arc_accounting_state=fields.Char(readonly=True,copy=False)
    arc_accounting_mapping=fields.Json(readonly=True,copy=False)
    arc_fee_atomic=fields.Char(readonly=True,copy=False)
    arc_fee_rounding=fields.Char(readonly=True,copy=False)

    def _boundary_tenant(self):
        tenant=super()._boundary_tenant()
        return tenant+':arc' if self.network=='eip155:5042002' else tenant

    def _create_request(self,vals):
        op=super()._create_request(dict(vals,arc_payment_id=False,arc_fee_move_id=False,arc_accounting_state=False,
                                       arc_accounting_mapping=False,arc_fee_atomic=False,arc_fee_rounding=False))
        if op.network=='eip155:5042002':
            op._update({'recommendation':'Arc testnet transfer; independent policy approval required',
                'explanation':'Test USDC only. Chain observation does not post accounting entries. Review the USD demonstration journal mapping before recording payment.'})
        return op

    def action_queue(self):
        if any(o.network=='eip155:5042002' for o in self):raise UserError('Use the transfer boundary for Arc; this button runs local simulation only.')
        return super().action_queue()

    def action_record_arc_payment(self):
        self.ensure_one();self._authorize(approver=True)
        if not self.env.user.has_group('account.group_account_manager'):raise UserError('An accounting manager must review this payment mapping.')
        self.env.cr.execute('SELECT id FROM chainsql_operation WHERE id=%s FOR UPDATE',[self.id]);self.invalidate_recordset()
        if self.arc_payment_id:return self._arc_open_payment()
        self.action_sync_boundary()
        e=(self.boundary_status or {}).get('arc_observation') or {}
        if self.network!='eip155:5042002' or e.get('state')!='confirmed':raise UserError('A confirmed Arc token receipt is required. Reverted or uncertain transfers cannot pay a bill.')
        self._validate_current()
        if self.approval_outcome!='approved':raise UserError('The bill approval is no longer current. Reconcile manually; do not initiate another transfer.')
        c=self.env['chainsql.arc.journal'].search([('company_id','=',self.company_id.id)],limit=1)
        if not c:raise UserError('Configure the explicit Arc demonstration journals first.')
        c._check_mapping()
        bill=self.move_id
        amount=Decimal(self.amount_atomic)/Decimal(10**6)
        if Decimal(str(bill.amount_residual))!=amount or bill.currency_id!=self.company_id.currency_id:
            raise UserError('Only an exact full USD payment is supported; changed amounts, FX and partial payments require manual accounting review.')
        lines=bill.line_ids.filtered(lambda l:l.account_id.account_type=='liability_payable' and not l.reconciled)
        if not lines or len(lines.account_id)!=1:raise UserError('Bill must have one payable account.')
        payment=self.env['account.payment'].with_company(self.company_id).create({
            'company_id':self.company_id.id,'journal_id':c.journal_id.id,'payment_method_line_id':c.method_id.id,
            'payment_type':'outbound','partner_type':'supplier','partner_id':bill.partner_id.id,
            'currency_id':bill.currency_id.id,'amount':float(amount),'date':fields.Date.context_today(self),
            'destination_account_id':lines.account_id.id,'memo':'Arc TEST '+e['txHash']})
        payment.action_post()
        payable=payment.move_id.line_ids.filtered(lambda l:l.account_id==lines.account_id and not l.reconciled)
        if not payable or payment.state=='paid':raise UserError('Journal mapping did not produce an outstanding payment; review the configuration.')
        self._update({'arc_payment_id':payment.id})
        (payable|lines).reconcile()
        bill.matched_payment_ids=[Command.link(payment.id)]
        fee=Decimal(e['feeAtomic'])/Decimal(10**18)
        rounded=fee.quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
        fee_move=self.env['account.move']
        if rounded:
            fee_move=fee_move.with_company(self.company_id).create({'move_type':'entry','journal_id':c.fee_journal_id.id,
                'date':payment.date,'ref':'Arc TEST gas '+e['txHash'],'line_ids':[
                    Command.create({'name':'Arc test gas (USD demonstration)','account_id':c.fee_expense_id.id,'debit':float(rounded)}),
                    Command.create({'name':'Arc test gas clearing','account_id':c.fee_clearing_id.id,'credit':float(rounded)})]})
            fee_move.action_post()
        self._update({'arc_payment_id':payment.id,'arc_fee_move_id':fee_move.id,'arc_accounting_state':'Recorded; outstanding clearing requires review',
            'arc_accounting_mapping':{'version':'arc-test-usd-v1','journal_id':c.journal_id.id,'method_id':c.method_id.id,
                'outstanding_account_id':c.method_id.payment_account_id.id,'fee_expense_id':c.fee_expense_id.id,'fee_clearing_id':c.fee_clearing_id.id,
                'mapping':'1 test USDC = 1 demonstration USD; no FX','receipt':e['txHash']},
            'arc_fee_atomic':e['feeAtomic'],'arc_fee_rounding':str(fee-rounded)+' USD retained as sub-cent audit remainder (half-up per transaction)'})
        return self._arc_open_payment()

    def _arc_open_payment(self):
        return {'type':'ir.actions.act_window','res_model':'account.payment','res_id':self.arc_payment_id.id,'view_mode':'form','target':'current'}
