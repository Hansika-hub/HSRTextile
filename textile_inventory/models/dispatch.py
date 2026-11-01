from collections import defaultdict

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_is_zero

DISPATCH_LOCKED = ('partner_id', 'roll_ids')
RECON_LOCKED = ('dispatch_id', 'date', 'rolls_received', 'accepted_m', 'rejected_m')


class TextileDispatch(models.Model):
    """One vehicle load of finished fabric rolls going to the mill.
    A load belongs to ONE vendor but may carry rolls of several of that
    vendor's orders (confirmed by the owner)."""

    _name = 'textile.dispatch'
    _description = 'Fabric Dispatch'
    _inherit = ['mail.thread', 'textile.stock.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string='Dispatch No.', default='New', readonly=True, copy=False)
    date = fields.Date(
        string='Dispatch Date', required=True, tracking=True,
        default=fields.Date.context_today,
    )
    partner_id = fields.Many2one(
        'res.partner', string='Vendor / Mill', required=True, tracking=True)
    order_ids = fields.Many2many(
        'textile.order', string='Orders in this Load', compute='_compute_orders')
    order_names = fields.Char(string='Orders', compute='_compute_orders')
    destination = fields.Char(string='Destination', required=True, tracking=True)
    vehicle_no = fields.Char(string='Vehicle No.', required=True, tracking=True)
    driver_name = fields.Char(string='Driver Name', tracking=True)
    driver_phone = fields.Char(string='Driver Phone')
    roll_ids = fields.Many2many(
        'textile.fabric.roll', 'textile_dispatch_roll_rel', 'dispatch_id', 'roll_id',
        string='Fabric Rolls',
    )
    roll_count = fields.Integer(
        string='Number of Rolls', compute='_compute_totals', store=True)
    total_metres = fields.Float(
        string='Total Metres', compute='_compute_totals', store=True)
    picking_ids = fields.Many2many(
        'stock.picking', 'textile_dispatch_picking_rel', 'dispatch_id', 'picking_id',
        string='Stock Transfers', readonly=True, copy=False)
    state = fields.Selection(
        [('draft', 'Draft'), ('dispatched', 'Dispatched'), ('cancel', 'Cancelled')],
        string='Status', default='draft', readonly=True, copy=False, tracking=True)
    notes = fields.Text(string='Notes')

    reconciliation_ids = fields.One2many(
        'textile.reconciliation', 'dispatch_id', string='Mill Reconciliations')
    reconciliation_count = fields.Integer(compute='_compute_reconciliation_count')
    reconciliation_state = fields.Selection(
        [('none', 'Not dispatched'), ('pending', 'Awaiting mill'),
         ('matched', 'Matched'), ('discrepancy', 'Discrepancy')],
        string='Mill Check', compute='_compute_reconciliation', store=True)
    mill_accepted_m = fields.Float(
        string='Mill Accepted (m)', compute='_compute_reconciliation', store=True)
    mill_rejected_m = fields.Float(
        string='Mill Rejected (m)', compute='_compute_reconciliation', store=True)
    mill_missing_m = fields.Float(
        string='Missing (m)', compute='_compute_reconciliation', store=True)

    @api.depends('roll_ids.order_id')
    def _compute_orders(self):
        for dispatch in self:
            orders = dispatch.roll_ids.order_id
            dispatch.order_ids = orders
            dispatch.order_names = ', '.join(orders.mapped('name'))

    @api.depends('roll_ids.length_m')
    def _compute_totals(self):
        for dispatch in self:
            dispatch.roll_count = len(dispatch.roll_ids)
            dispatch.total_metres = sum(dispatch.roll_ids.mapped('length_m'))

    @api.depends('reconciliation_ids')
    def _compute_reconciliation_count(self):
        for dispatch in self:
            dispatch.reconciliation_count = len(dispatch.reconciliation_ids)

    @api.depends('state', 'total_metres', 'reconciliation_ids.state',
                 'reconciliation_ids.accepted_m', 'reconciliation_ids.rejected_m',
                 'reconciliation_ids.missing_m', 'reconciliation_ids.has_discrepancy')
    def _compute_reconciliation(self):
        for dispatch in self:
            current = dispatch.reconciliation_ids.filtered(
                lambda r: r.state == 'confirmed')[:1]
            dispatch.mill_accepted_m = current.accepted_m if current else 0.0
            dispatch.mill_rejected_m = current.rejected_m if current else 0.0
            dispatch.mill_missing_m = current.missing_m if current else 0.0
            if dispatch.state != 'dispatched':
                dispatch.reconciliation_state = 'none'
            elif not current:
                dispatch.reconciliation_state = 'pending'
            else:
                dispatch.reconciliation_state = (
                    'discrepancy' if current.has_discrepancy else 'matched')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('textile.dispatch') or 'New')
        return super().create(vals_list)

    def write(self, vals):
        if any(r.state != 'draft' for r in self) and set(vals) & set(DISPATCH_LOCKED):
            raise UserError('The order and rolls of a confirmed dispatch cannot be changed.')
        return super().write(vals)

    def unlink(self):
        if any(r.state == 'dispatched' for r in self):
            raise UserError('A dispatched load cannot be deleted. Cancel it first.')
        return super().unlink()

    def action_confirm(self):
        """Take the rolls out of finished stock and mark them dispatched."""
        self._textile_lock()
        for dispatch in self:
            if dispatch.state != 'draft':
                raise UserError('This dispatch is already confirmed.')
            if not dispatch.roll_ids:
                raise UserError('Add at least one fabric roll to the dispatch.')
            for order in dispatch.roll_ids.order_id:
                dispatch._textile_check_order(order, dispatch.partner_id)
            if not (dispatch.vehicle_no or '').strip():
                raise UserError('The vehicle number is required.')
            dispatch.roll_ids._textile_lock()
            bad = dispatch.roll_ids.filtered(
                lambda r: r.state != 'available' or r.order_id.partner_id != dispatch.partner_id)
            if bad:
                raise UserError(
                    'These rolls are not in stock or belong to another vendor: %s'
                    % ', '.join(bad.mapped('name')))
            finished = self.env.ref('textile_inventory.location_finished_fabric')
            customers = self.env.ref('stock.stock_location_customers')
            warehouse = dispatch._textile_warehouse()
            per_product = defaultdict(float)
            for roll in dispatch.roll_ids:
                per_product[roll.product_id] += roll.length_m
            pickings = self.env['stock.picking']
            for product, qty in per_product.items():
                uom = dispatch._textile_check_product(
                    product, 'uom.product_uom_meter', 'm')
                pickings |= dispatch._textile_transfer(
                    warehouse.out_type_id, dispatch.partner_id,
                    dispatch.name,
                    product, qty, uom, finished, customers)
            dispatch.roll_ids.write({'state': 'dispatched', 'dispatch_id': dispatch.id})
            dispatch.write({'state': 'dispatched',
                            'picking_ids': [Command.set(pickings.ids)]})
        return True

    def action_cancel(self):
        """Undo a dispatch (e.g. entered by mistake): rolls go back in stock."""
        self._textile_lock()
        for dispatch in self:
            if dispatch.state != 'dispatched':
                raise UserError('Only a dispatched load can be cancelled.')
            if dispatch.reconciliation_ids.filtered(lambda r: r.state == 'confirmed'):
                raise UserError(
                    'The mill check of this load is already confirmed, so it '
                    'cannot be cancelled.')
            dispatch.roll_ids._textile_lock()
            finished = self.env.ref('textile_inventory.location_finished_fabric')
            customers = self.env.ref('stock.stock_location_customers')
            warehouse = dispatch._textile_warehouse()
            per_product = defaultdict(float)
            for roll in dispatch.roll_ids:
                per_product[roll.product_id] += roll.length_m
            for product, qty in per_product.items():
                dispatch._textile_transfer(
                    warehouse.int_type_id, False, 'Cancel %s' % dispatch.name,
                    product, qty, product.uom_id, customers, finished)
            dispatch.roll_ids.write({'state': 'available', 'dispatch_id': False})
            dispatch.reconciliation_ids.filtered(lambda r: r.state == 'draft').unlink()
            dispatch.state = 'cancel'
        return True

    def action_view_reconciliations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': 'Mill Reconciliation',
            'res_model': 'textile.reconciliation', 'view_mode': 'list,form',
            'domain': [('dispatch_id', '=', self.id)],
            'context': {'default_dispatch_id': self.id},
        }

    def action_new_reconciliation(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': 'Mill Reconciliation',
            'res_model': 'textile.reconciliation', 'view_mode': 'form',
            'context': {'default_dispatch_id': self.id,
                        'default_rolls_received': self.roll_count,
                        'default_accepted_m': self.total_metres},
        }


class TextileReconciliation(models.Model):
    """What the main mill reports for ONE load (totals only, not per roll).
    Several entries per dispatch are kept as history; only the latest
    confirmed one counts, earlier ones become 'superseded'.
    missing = dispatched - accepted - rejected (a negative value means the
    mill reports more than was sent)."""

    _name = 'textile.reconciliation'
    _description = 'Mill Reconciliation'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(string='Reference', default='New', readonly=True, copy=False)
    dispatch_id = fields.Many2one(
        'textile.dispatch', string='Dispatch', required=True, tracking=True,
        domain=[('state', '=', 'dispatched')], ondelete='restrict')
    order_names = fields.Char(related='dispatch_id.order_names', string='Orders')
    partner_id = fields.Many2one(related='dispatch_id.partner_id', store=True)
    date = fields.Date(
        string='Mill Receipt Date', required=True, tracking=True,
        default=fields.Date.context_today)
    mill_ref = fields.Char(string='Mill Receipt / Challan No.', tracking=True)
    dispatched_rolls = fields.Integer(
        related='dispatch_id.roll_count', string='Dispatched Rolls', store=True)
    dispatched_m = fields.Float(
        related='dispatch_id.total_metres', string='Dispatched (m)', store=True)
    rolls_received = fields.Integer(string='Rolls Received by Mill', tracking=True)
    accepted_m = fields.Float(string='Accepted (m)', tracking=True)
    rejected_m = fields.Float(string='Rejected (m)', tracking=True)
    missing_m = fields.Float(
        string='Missing (m)', compute='_compute_missing', store=True)
    missing_rolls = fields.Integer(
        string='Missing Rolls', compute='_compute_missing', store=True)
    has_discrepancy = fields.Boolean(
        string='Has Discrepancy', compute='_compute_missing', store=True)
    state = fields.Selection(
        [('draft', 'Draft'), ('confirmed', 'Confirmed'),
         ('superseded', 'Superseded (corrected later)')],
        string='Status', default='draft', readonly=True, copy=False, tracking=True)
    remarks = fields.Text(string='Remarks / Reason for Difference')

    @api.depends('dispatched_m', 'dispatched_rolls', 'accepted_m',
                 'rejected_m', 'rolls_received')
    def _compute_missing(self):
        for rec in self:
            rec.missing_m = rec.dispatched_m - rec.accepted_m - rec.rejected_m
            rec.missing_rolls = rec.dispatched_rolls - rec.rolls_received
            rec.has_discrepancy = (
                not float_is_zero(rec.missing_m, precision_digits=2)
                or not float_is_zero(rec.rejected_m, precision_digits=2)
                or rec.missing_rolls != 0)

    @api.constrains('rolls_received', 'accepted_m', 'rejected_m')
    def _check_values(self):
        for rec in self:
            if rec.rolls_received < 0 or rec.accepted_m < 0 or rec.rejected_m < 0:
                raise ValidationError('Mill quantities cannot be negative.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('textile.reconciliation') or 'New')
        return super().create(vals_list)

    def write(self, vals):
        if any(r.state != 'draft' for r in self) and set(vals) & set(RECON_LOCKED):
            raise UserError(
                'A confirmed mill reconciliation cannot be changed. Enter a '
                'new reconciliation to correct it; the old one stays in the history.')
        return super().write(vals)

    def unlink(self):
        if any(r.state != 'draft' for r in self):
            raise UserError('Only a draft reconciliation can be deleted.')
        return super().unlink()

    def action_confirm(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError('This reconciliation is already confirmed.')
            dispatch = rec.dispatch_id
            dispatch._textile_lock()
            if dispatch.state != 'dispatched':
                raise UserError('The dispatch must be in "Dispatched" status.')
            dispatch.reconciliation_ids.filtered(
                lambda r: r.state == 'confirmed' and r != rec
            ).write({'state': 'superseded'})
            rec.state = 'confirmed'
        return True
