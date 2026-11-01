from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

LOCKED_AFTER_CONFIRM = (
    'date', 'shift', 'loom_id', 'worker_id', 'order_id', 'metres_produced',
    'metres_damaged', 'metres_waste', 'metres_rejected',
)


class TextileWorker(models.Model):
    _name = 'textile.worker'
    _description = 'Weaving Worker'
    _order = 'name'

    name = fields.Char(string='Worker Name', required=True)
    code = fields.Char(string='Worker Code')
    phone = fields.Char(string='Phone')
    active = fields.Boolean(default=True)
    notes = fields.Char(string='Notes')


class TextileProduction(models.Model):
    """One entry = one loom, one shift, one worker.
    Day shift 7 AM - 7 PM, night shift 7 PM - 7 AM. A night shift is
    recorded on the date it STARTED.
    ASSUMPTION (to be confirmed by the owner): damaged, waste and rejected
    metres are part of the metres produced, so good metres = produced -
    damaged - waste - rejected."""

    _name = 'textile.production'
    _description = 'Shift Production Entry'
    _inherit = ['mail.thread']
    _order = 'date desc, shift, loom_id'

    name = fields.Char(
        string='Entry No.', default='New', readonly=True, copy=False,
    )
    date = fields.Date(
        string='Shift Date', required=True, tracking=True,
        default=fields.Date.context_today,
        help='For the night shift use the date the shift started.',
    )
    shift = fields.Selection(
        [('day', 'Day (7 AM - 7 PM)'), ('night', 'Night (7 PM - 7 AM)')],
        string='Shift', required=True, tracking=True, default='day',
    )
    loom_id = fields.Many2one(
        'textile.loom', string='Loom', required=True, tracking=True,
    )
    worker_id = fields.Many2one(
        'textile.worker', string='Worker', required=True, tracking=True,
    )
    order_id = fields.Many2one(
        'textile.order', string='Vendor Order', required=True, tracking=True,
        domain=[('state', '=', 'open')],
    )
    metres_produced = fields.Float(string='Produced (m)', required=True, tracking=True)
    metres_damaged = fields.Float(string='Damaged (m)', tracking=True)
    metres_waste = fields.Float(string='Waste (m)', tracking=True)
    metres_rejected = fields.Float(string='Rejected (m)', tracking=True)
    good_metres = fields.Float(
        string='Good Fabric (m)', compute='_compute_good_metres', store=True,
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('confirmed', 'Confirmed')],
        string='Status', default='draft', readonly=True, copy=False,
        tracking=True,
    )
    confirmed_by_id = fields.Many2one(
        'res.users', string='Confirmed By', readonly=True, copy=False,
    )
    confirmed_date = fields.Datetime(string='Confirmed On', readonly=True, copy=False)
    notes = fields.Text(string='Notes')
    roll_ids = fields.Many2many(
        'textile.fabric.roll', 'textile_fabric_roll_production_rel',
        'production_id', 'roll_id', string='Fabric Rolls',
    )
    roll_count = fields.Integer(compute='_compute_roll_count')

    _loom_shift_uniq = models.Constraint(
        'UNIQUE(date, shift, loom_id)',
        'This loom already has a production entry for that date and shift.',
    )

    @api.depends('metres_produced', 'metres_damaged', 'metres_waste', 'metres_rejected')
    def _compute_good_metres(self):
        for record in self:
            record.good_metres = (
                record.metres_produced - record.metres_damaged
                - record.metres_waste - record.metres_rejected)

    @api.depends('roll_ids')
    def _compute_roll_count(self):
        for record in self:
            record.roll_count = len(record.roll_ids)

    @api.constrains('metres_produced', 'metres_damaged', 'metres_waste', 'metres_rejected')
    def _check_metres(self):
        for record in self:
            if record.metres_produced <= 0:
                raise ValidationError('Metres produced must be greater than zero.')
            if min(record.metres_damaged, record.metres_waste, record.metres_rejected) < 0:
                raise ValidationError('Damaged, waste and rejected metres cannot be negative.')
            if record.good_metres < 0:
                raise ValidationError(
                    'Damaged + waste + rejected metres cannot be more than '
                    'the metres produced.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('textile.production') or 'New')
        return super().create(vals_list)

    def write(self, vals):
        if any(r.state == 'confirmed' for r in self) and set(vals) & set(LOCKED_AFTER_CONFIRM):
            raise UserError(
                'A confirmed production entry cannot be changed. Ask an '
                'Administrator to set it back to draft first.')
        return super().write(vals)

    def unlink(self):
        if any(r.state == 'confirmed' for r in self):
            raise UserError('A confirmed production entry cannot be deleted.')
        return super().unlink()

    def action_confirm(self):
        self._textile_lock_rows()
        for record in self:
            if record.state != 'draft':
                raise UserError('This production entry is already confirmed.')
            if record.order_id.state != 'open':
                raise UserError(
                    'Order %s is not open. Production can only be confirmed '
                    'for an open order.' % record.order_id.name)
            record.write({
                'state': 'confirmed',
                'confirmed_by_id': self.env.user.id,
                'confirmed_date': fields.Datetime.now(),
            })
        return True

    def action_draft(self):
        if not self.env.user.has_group('textile_inventory.group_textile_admin'):
            raise UserError('Only an Administrator can set a confirmed entry back to draft.')
        for record in self:
            if record.state != 'confirmed':
                continue
            if record.roll_ids.filtered(lambda r: r.state != 'cancel'):
                raise UserError(
                    'Fabric rolls are already linked to this entry. Cancel '
                    'those rolls first.')
            record.write({'state': 'draft', 'confirmed_by_id': False,
                          'confirmed_date': False})
        return True

    def _textile_lock_rows(self):
        if not self.ids:
            return
        self.env.cr.execute(
            'SELECT id FROM "%s" WHERE id IN %%s FOR UPDATE NOWAIT' % self._table,
            (tuple(self.ids),))
        self.invalidate_recordset()

    def action_view_rolls(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': 'Fabric Rolls',
            'res_model': 'textile.fabric.roll', 'view_mode': 'list,form',
            'domain': [('production_ids', 'in', self.id)],
        }
