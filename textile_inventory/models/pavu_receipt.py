from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class PavuReceipt(models.Model):
    """Pavu is supplied by the vendor. One receipt can hold several roll
    lengths, e.g. 5 x 1200 m + 3 x 1000 m = 9000 m."""

    _name = 'textile.pavu.receipt'
    _description = 'Pavu Receipt'
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
    order_ref = fields.Char(string='Vendor Order Ref.', tracking=True)
    vehicle_no = fields.Char(string='Vehicle No.')
    product_id = fields.Many2one(
        'product.product', string='Pavu Product', required=True,
        tracking=True, domain=[('is_storable', '=', True)],
    )
    line_ids = fields.One2many(
        'textile.pavu.receipt.line', 'receipt_id', string='Roll Lengths',
    )
    total_rolls = fields.Integer(
        string='Total Rolls', compute='_compute_totals', store=True,
    )
    total_metres = fields.Float(
        string='Total Metres', compute='_compute_totals', store=True,
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

    @api.depends('line_ids.number_of_rolls', 'line_ids.total_metres')
    def _compute_totals(self):
        for record in self:
            record.total_rolls = sum(record.line_ids.mapped('number_of_rolls'))
            record.total_metres = sum(record.line_ids.mapped('total_metres'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('textile.pavu.receipt')
                    or 'New'
                )
        return super().create(vals_list)

    def unlink(self):
        if any(record.state == 'done' for record in self):
            raise UserError(
                'A received Pavu receipt cannot be deleted because stock '
                'has already been added.'
            )
        return super().unlink()

    def action_receive(self):
        self._textile_lock()
        for record in self:
            if record.state == 'done':
                raise UserError('This Pavu receipt has already been received.')
            uom = record._textile_check_product(
                record.product_id, 'uom.product_uom_meter', 'm'
            )
            if not record.line_ids:
                raise UserError('Add at least one roll length line.')
            if record.total_metres <= 0:
                raise UserError('Total metres must be greater than zero.')

            warehouse = record._textile_warehouse()
            picking_type = warehouse.in_type_id
            origin = record.name
            if record.order_ref:
                origin = '%s / %s' % (record.name, record.order_ref)
            picking = record._textile_transfer(
                picking_type, record.partner_id, origin, record.product_id,
                record.total_metres, uom,
                picking_type.default_location_src_id,
                picking_type.default_location_dest_id,
            )
            record.write({'picking_id': picking.id, 'state': 'done'})
        return True


class PavuReceiptLine(models.Model):
    _name = 'textile.pavu.receipt.line'
    _description = 'Pavu Receipt Line (one roll length)'
    _order = 'receipt_id, roll_length desc'

    receipt_id = fields.Many2one(
        'textile.pavu.receipt', string='Receipt', required=True,
        ondelete='cascade',
    )
    roll_length = fields.Float(string='Roll Length (m)', required=True)
    number_of_rolls = fields.Integer(
        string='Number of Rolls', required=True, default=1,
    )
    total_metres = fields.Float(
        string='Metres', compute='_compute_total_metres', store=True,
    )

    @api.depends('roll_length', 'number_of_rolls')
    def _compute_total_metres(self):
        for line in self:
            line.total_metres = line.roll_length * line.number_of_rolls

    @api.constrains('roll_length', 'number_of_rolls')
    def _check_positive(self):
        for line in self:
            if line.roll_length <= 0 or line.number_of_rolls <= 0:
                raise ValidationError(
                    'Roll length and number of rolls must be greater than zero.'
                )

    def _check_receipt_open(self):
        if any(line.receipt_id.state == 'done' for line in self):
            raise UserError('A received Pavu receipt cannot be changed.')

    @api.model_create_multi
    def create(self, vals_list):
        receipts = self.env['textile.pavu.receipt'].browse(
            [v['receipt_id'] for v in vals_list if v.get('receipt_id')]
        )
        if any(r.state == 'done' for r in receipts):
            raise UserError('A received Pavu receipt cannot be changed.')
        return super().create(vals_list)

    def write(self, vals):
        self._check_receipt_open()
        return super().write(vals)

    def unlink(self):
        self._check_receipt_open()
        return super().unlink()
