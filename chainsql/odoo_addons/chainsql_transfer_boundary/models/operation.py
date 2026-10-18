import json
from odoo import fields, models
from odoo.exceptions import UserError


class Operation(models.Model):
    _inherit = 'chainsql.operation'

    boundary_transfer_id = fields.Char(readonly=True, copy=False)
    boundary_state = fields.Char(readonly=True, copy=False)
    boundary_status = fields.Json(readonly=True, copy=False)

    def _create_request(self, vals):
        # Inherited base blocks ordinary create/write; also reject forged context defaults.
        return super()._create_request(dict(vals, boundary_transfer_id=False,
                                            boundary_state=False, boundary_status=False))

    def _boundary_tenant(self):
        self.ensure_one()
        return f'odoo:{self.env.cr.dbname}:{self.company_id.id}'

    def action_request_boundary_transfer(self):
        self.ensure_one()
        self._authorize()
        self._validate_current()
        if self.boundary_transfer_id:
            return self.action_sync_boundary()
        if self.approval_outcome != 'approved':
            raise UserError('Approve the current bill request first.')
        tenant = self._boundary_tenant()
        business = f'account.move:{self.move_id.id}'
        self.env.cr.execute('SELECT * FROM chainsql.approved_transfer_v1(%s,%s)', (tenant, business))
        row = self.env.cr.fetchone()
        if not row:
            raise UserError('An independent policy administrator must approve this exact transfer snapshot. Odoo cannot grant that authority.')
        approval_id, snapshot = row
        expected = dict(tenant=tenant, business_reference=business, request_revision=str(self.revision),
                        destination=self.recipient, network=self.network, asset=self.asset,
                        amount_atomic=self.amount_atomic)
        if any(snapshot.get(key) != value for key, value in expected.items()):
            raise UserError('The independent approval does not match the current bill request.')
        self.env.cr.execute('SELECT chainsql.request_transfer_v1(%s,%s::jsonb,%s)::text',
                            (approval_id, json.dumps(snapshot), f'odoo-transfer:{self.id}:{self.fingerprint}'))
        transfer_id = self.env.cr.fetchone()[0]
        self._update({'boundary_transfer_id': transfer_id})
        return self.action_sync_boundary()

    def action_sync_boundary(self):
        self.ensure_one()
        self._authorize()
        if self.boundary_transfer_id:
            self.env.cr.execute('SELECT chainsql.transfer_status_v1(%s)', (self.boundary_transfer_id,))
            status = self.env.cr.fetchone()[0]
            self._update({'boundary_status': status, 'boundary_state': status['state']})
        return True

    def action_cancel_boundary(self):
        self.ensure_one()
        self._authorize()
        if not self.boundary_transfer_id:
            raise UserError('No boundary transfer exists.')
        self.env.cr.execute('SELECT chainsql.cancel_transfer_v1(%s)', (self.boundary_transfer_id,))
        return self.action_sync_boundary()
