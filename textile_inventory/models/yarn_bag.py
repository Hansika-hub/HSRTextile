from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class YarnBagLine(models.Model):
    _name = 'textile.yarn.bag.line'
    _description = 'Yarn Receipt'
    _inherit = ['mail.thread', 'textile.stock.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Receipt No.', default='New', readonly=True, copy=False,
    )
    date = fields.Date(
        string='Receipt Date', required=True, tracking=True,
        default=fields.Date.context_today,
    )
    partner_id = fields.Many2one(
        'res.partner', string='Vendor', tracking=True,
    )
    order_ref = fields.Char(
        string='Vendor Order Ref.', tracking=True,
        help='Vendor order number. A proper Order record comes in a later phase.',
    )
    vehicle_no = fields.Char(string='Vehicle No.')
    product_id = fields.Many2one(
        'product.product', string='Yarn Product', required=True,
        tracking=True, domain=[('is_storable', '=', True)],
    )
    bag_size = fields.Float(string='Bag Size (kg)', required=True, tracking=True)
    number_of_bags = fields.Integer(
        string='Number of Bags', required=True, default=1, tracking=True,
    )
    total_weight = fields.Float(
        string='Total Weight (kg)', compute='_compute_total_weight', store=True,
    )
    picking_id = fields.Many2one(
        'stock.picking', string='Stock Receipt', readonly=True, copy=False,
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('done', 'Received')],
        string='Status', default='draft', readonly=True, copy=False,
        tracking=True,
    )
    notes = fields.Text(string='Notes')

    @api.depends('bag_size', 'number_of_bags')
    def _compute_total_weight(self):
        for record in self:
            record.total_weight = record.bag_size * record.number_of_bags

    @api.constrains('bag_size', 'number_of_bags')
    def _check_positive(self):
        for record in self:
            if record.bag_size <= 0:
                raise ValidationError('Bag size must be greater than zero.')
            if record.number_of_bags <= 0:
                raise ValidationError('Number of bags must be greater than zero.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('textile.yarn.receipt')
                    or 'New'
                )
        return super().create(vals_list)

    def unlink(self):
        if any(record.state == 'done' for record in self):
            raise UserError(
                'A received yarn receipt cannot be deleted because stock '
                'has already been added.'
            )
        return super().unlink()

    def action_receive(self):
        """Receive yarn into the godown with a standard Odoo receipt.
        Example: 5 bags x 50 kg = 250 kg."""
        self._textile_lock()
        for record in self:
            if record.state == 'done':
                raise UserError('This yarn receipt has already been received.')
            uom = record._textile_check_product(
                record.product_id, 'uom.product_uom_kgm', 'kg'
            )
            if record.total_weight <= 0:
                raise UserError('Total weight must be greater than zero.')

            warehouse = record._textile_warehouse()
            picking_type = warehouse.in_type_id
            origin = record.name
            if record.order_ref:
                origin = '%s / %s' % (record.name, record.order_ref)
            picking = record._textile_transfer(
                picking_type, record.partner_id, origin, record.product_id,
                record.total_weight, uom,
                picking_type.default_location_src_id,
                picking_type.default_location_dest_id,
            )
            record.write({'picking_id': picking.id, 'state': 'done'})
        return True
