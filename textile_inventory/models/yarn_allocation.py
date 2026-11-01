from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class YarnAllocation(models.Model):
    _name = 'textile.yarn.allocation'
    _description = 'Yarn Allocation to Loom'
    _inherit = ['mail.thread', 'textile.stock.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Allocation No.', default='New', readonly=True, copy=False,
    )
    product_id = fields.Many2one(
        'product.product', string='Yarn Product', required=True,
        tracking=True, domain=[('is_storable', '=', True)],
    )
    loom_id = fields.Many2one(
        'textile.loom', string='Loom', required=True, tracking=True,
    )
    quantity = fields.Float(string='Quantity (kg)', required=True, tracking=True)
    state = fields.Selection(
        [('draft', 'Draft'), ('allocated', 'Allocated')],
        string='Status', default='draft', readonly=True, copy=False,
        tracking=True,
    )
    allocation_date = fields.Datetime(
        string='Allocation Date', readonly=True, copy=False,
    )
    picking_id = fields.Many2one(
        'stock.picking', string='Stock Transfer', readonly=True, copy=False,
    )
    notes = fields.Text(string='Notes')

    @api.constrains('quantity')
    def _check_quantity(self):
        for record in self:
            if record.quantity <= 0:
                raise ValidationError(
                    'Allocation quantity must be greater than zero.'
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('textile.yarn.allocation')
                    or 'New'
                )
        return super().create(vals_list)

    def unlink(self):
        if any(record.state == 'allocated' for record in self):
            raise UserError(
                'A completed allocation cannot be deleted because stock '
                'has already been moved.'
            )
        return super().unlink()

    def action_allocate(self):
        """Move yarn from the godown to the Loom Allocation location with
        a standard internal transfer. Never allows negative stock."""
        self._textile_lock()
        for record in self:
            if record.state == 'allocated':
                raise UserError('This yarn allocation has already been completed.')
            uom = record._textile_check_product(
                record.product_id, 'uom.product_uom_kgm', 'kg'
            )
            warehouse = record._textile_warehouse()
            source = warehouse.lot_stock_id
            dest = self.env.ref(
                'textile_inventory.location_loom_allocation',
                raise_if_not_found=False,
            )
            if not dest:
                raise UserError('The "Loom Allocation" stock location is missing.')

            available = self.env['stock.quant']._get_available_quantity(
                record.product_id, source
            )
            if available < record.quantity:
                raise UserError(
                    'Not enough yarn available in the godown.\n\n'
                    'Product: %s\nAvailable: %.2f kg\nRequested: %.2f kg'
                    % (record.product_id.display_name, available, record.quantity)
                )

            picking = record._textile_transfer(
                warehouse.int_type_id, False,
                '%s / %s' % (record.name, record.loom_id.code),
                record.product_id, record.quantity, uom, source, dest,
            )
            record.write({
                'picking_id': picking.id,
                'state': 'allocated',
                'allocation_date': fields.Datetime.now(),
            })
        return True
