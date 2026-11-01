from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class TextileOrder(models.Model):
    """Vendor order: the spine that receipts, allocation, production and
    dispatch will all link to."""

    _name = 'textile.order'
    _description = 'Vendor Order'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(
        string='Order No.', default='New', readonly=True, copy=False,
    )
    order_ref = fields.Char(
        string='Vendor Order Ref.', required=True, tracking=True,
        help='The order number given by the vendor / main mill.',
    )
    partner_id = fields.Many2one(
        'res.partner', string='Vendor', required=True, tracking=True,
    )
    order_date = fields.Date(
        string='Order Date', required=True, tracking=True,
        default=fields.Date.context_today,
    )
    expected_date = fields.Date(string='Expected Completion', tracking=True)
    required_fabric_m = fields.Float(
        string='Required Fabric (m)', required=True, tracking=True,
    )
    expected_yarn_kg = fields.Float(string='Expected Yarn (kg)', tracking=True)
    expected_pavu_m = fields.Float(string='Expected Pavu (m)', tracking=True)
    roll_length_min = fields.Float(
        string='Fabric Roll Min Length (m)', default=130.0,
        help='Approximate finished roll length. Configurable per order.',
    )
    roll_length_max = fields.Float(
        string='Fabric Roll Max Length (m)', default=140.0,
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('open', 'Open'),
         ('done', 'Completed'), ('cancel', 'Cancelled')],
        string='Status', default='draft', readonly=True, copy=False,
        tracking=True,
    )
    notes = fields.Text(string='Notes')

    yarn_receipt_ids = fields.One2many(
        'textile.yarn.bag.line', 'order_id', string='Yarn Receipts')
    pavu_receipt_ids = fields.One2many(
        'textile.pavu.receipt', 'order_id', string='Pavu Receipts')
    allocation_ids = fields.One2many(
        'textile.yarn.allocation', 'order_id', string='Yarn Allocations')

    yarn_received_kg = fields.Float(
        string='Yarn Received (kg)', compute='_compute_progress')
    yarn_pending_kg = fields.Float(
        string='Yarn Pending (kg)', compute='_compute_progress')
    yarn_allocated_kg = fields.Float(
        string='Yarn on Looms (kg)', compute='_compute_progress')
    pavu_received_m = fields.Float(
        string='Pavu Received (m)', compute='_compute_progress')
    pavu_pending_m = fields.Float(
        string='Pavu Pending (m)', compute='_compute_progress')

    production_ids = fields.One2many(
        'textile.production', 'order_id', string='Production Entries')
    roll_ids = fields.One2many(
        'textile.fabric.roll', 'order_id', string='Fabric Rolls')
    fabric_produced_m = fields.Float(
        string='Good Fabric Produced (m)', compute='_compute_progress')
    fabric_damaged_m = fields.Float(
        string='Damaged (m)', compute='_compute_progress')
    fabric_waste_m = fields.Float(
        string='Waste (m)', compute='_compute_progress')
    fabric_rejected_m = fields.Float(
        string='Rejected (m)', compute='_compute_progress')
    fabric_pending_m = fields.Float(
        string='Fabric Still To Weave (m)', compute='_compute_progress')
    fabric_rolled_m = fields.Float(
        string='Finished Rolls (m)', compute='_compute_progress',
        help='Total length of confirmed fabric rolls.')
    fabric_unrolled_m = fields.Float(
        string='Woven, Not Yet Rolled (m)', compute='_compute_progress',
        help='Good fabric produced minus finished rolls. A negative value '
             'means more was rolled than was recorded as produced.')
    dispatch_ids = fields.One2many('textile.dispatch', 'order_id', string='Dispatches')
    fabric_stock_m = fields.Float(
        string='Finished Stock (m)', compute='_compute_progress',
        help='Confirmed rolls still in the godown (not yet dispatched).')
    fabric_dispatched_m = fields.Float(
        string='Dispatched (m)', compute='_compute_progress')
    mill_accepted_m = fields.Float(
        string='Mill Accepted (m)', compute='_compute_progress')
    mill_rejected_m = fields.Float(
        string='Mill Rejected (m)', compute='_compute_progress')
    mill_missing_m = fields.Float(
        string='Missing at Mill (m)', compute='_compute_progress')
    mill_pending_m = fields.Float(
        string='Not Yet Checked by Mill (m)', compute='_compute_progress')
    dispatch_count = fields.Integer(compute='_compute_counts')
    production_count = fields.Integer(compute='_compute_counts')
    roll_count = fields.Integer(compute='_compute_counts')
    yarn_receipt_count = fields.Integer(compute='_compute_counts')
    pavu_receipt_count = fields.Integer(compute='_compute_counts')
    allocation_count = fields.Integer(compute='_compute_counts')

    _ref_partner_uniq = models.Constraint(
        'UNIQUE(partner_id, order_ref)',
        'This vendor already has an order with the same reference.',
    )

    @api.depends(
        'yarn_receipt_ids.state', 'yarn_receipt_ids.total_weight',
        'pavu_receipt_ids.state', 'pavu_receipt_ids.total_metres',
        'allocation_ids.state', 'allocation_ids.quantity',
        'expected_yarn_kg', 'expected_pavu_m', 'required_fabric_m',
        'production_ids.state', 'production_ids.good_metres',
        'production_ids.metres_damaged', 'production_ids.metres_waste',
        'production_ids.metres_rejected',
        'roll_ids.state', 'roll_ids.length_m',
        'dispatch_ids.state', 'dispatch_ids.total_metres',
        'dispatch_ids.reconciliation_state', 'dispatch_ids.mill_accepted_m',
        'dispatch_ids.mill_rejected_m', 'dispatch_ids.mill_missing_m',
    )
    def _compute_progress(self):
        for order in self:
            yarn = order.yarn_receipt_ids.filtered(lambda r: r.state == 'done')
            pavu = order.pavu_receipt_ids.filtered(lambda r: r.state == 'done')
            alloc = order.allocation_ids.filtered(lambda a: a.state == 'allocated')
            order.yarn_received_kg = sum(yarn.mapped('total_weight'))
            order.pavu_received_m = sum(pavu.mapped('total_metres'))
            order.yarn_allocated_kg = sum(alloc.mapped('quantity'))
            order.yarn_pending_kg = max(
                order.expected_yarn_kg - order.yarn_received_kg, 0.0)
            order.pavu_pending_m = max(
                order.expected_pavu_m - order.pavu_received_m, 0.0)
            prod = order.production_ids.filtered(lambda p: p.state == 'confirmed')
            rolls = order.roll_ids.filtered(
                lambda r: r.state in ('available', 'dispatched'))
            order.fabric_produced_m = sum(prod.mapped('good_metres'))
            order.fabric_damaged_m = sum(prod.mapped('metres_damaged'))
            order.fabric_waste_m = sum(prod.mapped('metres_waste'))
            order.fabric_rejected_m = sum(prod.mapped('metres_rejected'))
            order.fabric_pending_m = max(
                order.required_fabric_m - order.fabric_produced_m, 0.0)
            order.fabric_rolled_m = sum(rolls.mapped('length_m'))
            order.fabric_unrolled_m = order.fabric_produced_m - order.fabric_rolled_m
            order.fabric_stock_m = sum(
                rolls.filtered(lambda r: r.state == 'available').mapped('length_m'))
            sent = order.dispatch_ids.filtered(lambda d: d.state == 'dispatched')
            checked = sent.filtered(lambda d: d.reconciliation_state in ('matched', 'discrepancy'))
            order.fabric_dispatched_m = sum(sent.mapped('total_metres'))
            order.mill_accepted_m = sum(checked.mapped('mill_accepted_m'))
            order.mill_rejected_m = sum(checked.mapped('mill_rejected_m'))
            order.mill_missing_m = sum(checked.mapped('mill_missing_m'))
            order.mill_pending_m = sum(
                (sent - checked).mapped('total_metres'))

    @api.depends('yarn_receipt_ids', 'pavu_receipt_ids', 'allocation_ids',
                 'production_ids', 'roll_ids', 'dispatch_ids')
    def _compute_counts(self):
        for order in self:
            order.production_count = len(order.production_ids)
            order.roll_count = len(order.roll_ids)
            order.dispatch_count = len(order.dispatch_ids)
            order.yarn_receipt_count = len(order.yarn_receipt_ids)
            order.pavu_receipt_count = len(order.pavu_receipt_ids)
            order.allocation_count = len(order.allocation_ids)

    @api.constrains('required_fabric_m', 'expected_yarn_kg', 'expected_pavu_m',
                    'roll_length_min', 'roll_length_max')
    def _check_quantities(self):
        for order in self:
            if order.required_fabric_m <= 0:
                raise ValidationError('Required fabric must be greater than zero.')
            if order.expected_yarn_kg < 0 or order.expected_pavu_m < 0:
                raise ValidationError('Expected quantities cannot be negative.')
            if order.roll_length_min <= 0 or order.roll_length_max < order.roll_length_min:
                raise ValidationError(
                    'Fabric roll length: minimum must be above zero and not '
                    'more than the maximum.')

    @api.constrains('order_date', 'expected_date')
    def _check_dates(self):
        for order in self:
            if order.expected_date and order.expected_date < order.order_date:
                raise ValidationError(
                    'Expected completion cannot be before the order date.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('textile.order') or 'New')
        return super().create(vals_list)

    def unlink(self):
        self.check_access('unlink')
        if any(order.state not in ('draft', 'cancel') for order in self):
            raise UserError('Only draft or cancelled orders can be deleted.')
        if any(order.yarn_receipt_ids or order.pavu_receipt_ids
               or order.allocation_ids or order.production_ids
               or order.roll_ids or order.dispatch_ids for order in self):
            raise UserError('This order already has receipts or allocations.')
        return super().unlink()

    # ---- status buttons -------------------------------------------------
    def action_confirm(self):
        for order in self:
            if order.state != 'draft':
                raise UserError('Only a draft order can be confirmed.')
            order.state = 'open'
        return True

    def action_done(self):
        for order in self:
            if order.state != 'open':
                raise UserError('Only an open order can be completed.')
            order.state = 'done'
        return True

    def action_cancel(self):
        for order in self:
            if order.state in ('done', 'cancel'):
                raise UserError('This order is already closed.')
            if (order.yarn_receipt_ids.filtered(lambda r: r.state == 'done')
                    or order.pavu_receipt_ids.filtered(lambda r: r.state == 'done')
                    or order.allocation_ids.filtered(lambda a: a.state == 'allocated')
                    or order.production_ids.filtered(lambda p: p.state == 'confirmed')
                    or order.dispatch_ids.filtered(lambda d: d.state == 'dispatched')
                    or order.roll_ids.filtered(lambda r: r.state != 'cancel')):
                raise UserError(
                    'Stock has already been received or allocated for this '
                    'order, so it cannot be cancelled. Complete it instead.')
            order.state = 'cancel'
        return True

    def action_draft(self):
        for order in self:
            if order.state != 'cancel':
                raise UserError('Only a cancelled order can be set back to draft.')
            order.state = 'draft'
        return True

    # ---- stat buttons ---------------------------------------------------
    def _open_list(self, title, model):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': title, 'res_model': model,
            'view_mode': 'list,form',
            'domain': [('order_id', '=', self.id)],
            'context': {'default_order_id': self.id,
                        'default_partner_id': self.partner_id.id},
        }

    def action_view_yarn_receipts(self):
        return self._open_list('Yarn Receipts', 'textile.yarn.bag.line')

    def action_view_pavu_receipts(self):
        return self._open_list('Pavu Receipts', 'textile.pavu.receipt')

    def action_view_allocations(self):
        return self._open_list('Yarn Allocations', 'textile.yarn.allocation')

    def action_view_production(self):
        return self._open_list('Production Entries', 'textile.production')

    def action_view_dispatches(self):
        return self._open_list('Dispatches', 'textile.dispatch')

    def action_view_rolls(self):
        return self._open_list('Fabric Rolls', 'textile.fabric.roll')
