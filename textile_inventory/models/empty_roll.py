from odoo import api, fields, models
from odoo.exceptions import ValidationError


class EmptyRollLog(models.Model):
    """Simple ledger for empty Pavu rolls: collected after use, then reused
    for winding yarn or returned to the vendor.
    Record-only: it does not move Odoo stock. How the business counts empty
    rolls is still an open question for the owner."""

    _name = 'textile.empty.roll.log'
    _description = 'Empty Roll Log'
    _order = 'date desc, id desc'

    date = fields.Date(
        string='Date', required=True, default=fields.Date.context_today,
    )
    action = fields.Selection(
        [('collected', 'Collected (empty after use)'),
         ('reused', 'Reused for winding'),
         ('returned', 'Returned to vendor')],
        string='Action', required=True, default='collected',
    )
    quantity = fields.Integer(string='Number of Rolls', required=True, default=1)
    order_id = fields.Many2one('textile.order', string='Vendor Order')
    partner_id = fields.Many2one('res.partner', string='Vendor')
    notes = fields.Char(string='Notes')
    signed_quantity = fields.Integer(
        string='Balance Effect', compute='_compute_signed', store=True,
        help='+ for collected rolls, - for reused or returned rolls.',
    )

    @api.depends('action', 'quantity')
    def _compute_signed(self):
        for record in self:
            record.signed_quantity = (
                record.quantity if record.action == 'collected'
                else -record.quantity)

    @api.constrains('quantity')
    def _check_quantity(self):
        for record in self:
            if record.quantity <= 0:
                raise ValidationError('Number of rolls must be greater than zero.')

    @api.onchange('order_id')
    def _onchange_order_id(self):
        if self.order_id:
            self.partner_id = self.order_id.partner_id
