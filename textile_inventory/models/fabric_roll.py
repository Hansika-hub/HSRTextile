from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

LOCKED_AFTER_CONFIRM = ('order_id', 'product_id', 'length_m', 'production_ids', 'date')


class FabricRoll(models.Model):
    """A finished, cut and folded roll of fabric (about 130-140 m).
    Confirming a roll adds its length (metres) to the 'Finished Fabric'
    stock location through a standard Odoo stock transfer."""

    _name = 'textile.fabric.roll'
    _description = 'Finished Fabric Roll'
    _inherit = ['mail.thread', 'textile.stock.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Roll No.', default='New', readonly=True, copy=False,
    )
    date = fields.Date(
        string='Date', required=True, default=fields.Date.context_today,
    )
    order_id = fields.Many2one(
        'textile.order', string='Vendor Order', required=True, tracking=True,
        domain=[('state', '=', 'open')],
    )
    product_id = fields.Many2one(
        'product.product', string='Fabric Product', required=True,
        domain=[('is_storable', '=', True)],
        default=lambda self: self.env['product.product'].search(
            [('name', '=', 'Woven fabric'), ('is_storable', '=', True)], limit=1),
    )
    length_m = fields.Float(string='Length (m)', required=True, tracking=True)
    out_of_range = fields.Boolean(
        string='Outside Normal Length', compute='_compute_out_of_range',
        help="Outside the roll length range set on the order.",
    )
    production_ids = fields.Many2many(
        'textile.production', 'textile_fabric_roll_production_rel',
        'roll_id', 'production_id', string='Production Entries',
        help='The shift entries this roll was woven in (a roll can span a '
             'day and a night shift).',
    )
    picking_id = fields.Many2one(
        'stock.picking', string='Stock Transfer', readonly=True, copy=False,
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('available', 'In Stock'),
         ('dispatched', 'Dispatched'), ('cancel', 'Cancelled')],
        string='Status', default='draft', readonly=True, copy=False,
        tracking=True,
    )
    notes = fields.Char(string='Notes')

    _name_uniq = models.Constraint('UNIQUE(name)', 'Roll number must be unique.')

    @api.depends('length_m', 'order_id.roll_length_min', 'order_id.roll_length_max')
    def _compute_out_of_range(self):
        for roll in self:
            order = roll.order_id
            roll.out_of_range = bool(order) and not (
                order.roll_length_min <= roll.length_m <= order.roll_length_max)

    @api.constrains('length_m')
    def _check_length(self):
        for roll in self:
            if roll.length_m <= 0:
                raise ValidationError('Roll length must be greater than zero.')

    @api.onchange('order_id')
    def _onchange_order_id(self):
        if self.order_id and not self.length_m:
            self.length_m = (self.order_id.roll_length_min + self.order_id.roll_length_max) / 2

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('textile.fabric.roll') or 'New')
        return super().create(vals_list)

    def write(self, vals):
        if any(r.state != 'draft' for r in self) and set(vals) & set(LOCKED_AFTER_CONFIRM):
            raise UserError('A confirmed roll cannot be changed.')
        return super().write(vals)

    def unlink(self):
        if any(r.state not in ('draft', 'cancel') for r in self):
            raise UserError('Only draft or cancelled rolls can be deleted.')
        return super().unlink()

    def _fabric_locations(self):
        finished = self.env.ref('textile_inventory.location_finished_fabric',
                                raise_if_not_found=False)
        if not finished:
            raise UserError('The "Finished Fabric" stock location is missing.')
        production = self.env['stock.location'].search([
            ('usage', '=', 'production'),
            ('company_id', 'in', [self.env.company.id, False]),
        ], limit=1)
        if not production:
            raise UserError('No production (virtual) stock location was found.')
        return production, finished

    def action_confirm(self):
        """Add this roll's metres to Finished Fabric stock."""
        self._textile_lock()
        for roll in self:
            if roll.state != 'draft':
                raise UserError('This roll is already confirmed.')
            roll._textile_check_order(roll.order_id, False)
            uom = roll._textile_check_product(
                roll.product_id, 'uom.product_uom_meter', 'm')
            if not roll.production_ids:
                raise UserError(
                    'Link the roll to the production entries it was woven in.')
            if roll.production_ids.filtered(lambda p: p.state != 'confirmed'):
                raise UserError('All linked production entries must be confirmed.')
            if roll.production_ids.filtered(lambda p: p.order_id != roll.order_id):
                raise UserError('A linked production entry belongs to a different order.')
            production, finished = roll._fabric_locations()
            picking = roll._textile_transfer(
                roll._textile_warehouse().int_type_id, False,
                '%s / %s' % (roll.name, roll.order_id.name),
                roll.product_id, roll.length_m, uom, production, finished)
            roll.write({'picking_id': picking.id, 'state': 'available'})
        return True

    def action_cancel(self):
        """Remove a roll that was entered by mistake (reverses the stock)."""
        self._textile_lock()
        for roll in self:
            if roll.state != 'available':
                raise UserError('Only a roll that is in stock can be cancelled.')
            uom = roll.product_id.uom_id
            production, finished = roll._fabric_locations()
            roll._textile_transfer(
                roll._textile_warehouse().int_type_id, False,
                'Cancel %s' % roll.name, roll.product_id, roll.length_m, uom,
                finished, production)
            roll.state = 'cancel'
        return True
