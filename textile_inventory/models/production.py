from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero, float_round

LOCKED_AFTER_CONFIRM = (
    'date', 'shift', 'loom_id', 'line_ids', 'order_id', 'metres_produced',
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
    """One entry = one loom, one shift. One or more workers share it.
    Day shift 7 AM - 7 PM, night shift 7 PM - 7 AM. A night shift is
    recorded on the date it STARTED.
    Confirmed by the owner: damaged, waste and rejected metres are part of
    the metres produced, so good metres = produced - damaged - waste -
    rejected. Each worker gets a share of the GOOD metres (equal split by
    default, or the supervisor can enter each worker's share)."""

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
    line_ids = fields.One2many(
        'textile.production.worker', 'production_id', string='Workers',
        copy=True,
    )
    worker_ids = fields.Many2many(
        'textile.worker', string='Workers', compute='_compute_worker_ids',
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

    @api.depends('line_ids.worker_id')
    def _compute_worker_ids(self):
        for record in self:
            record.worker_ids = record.line_ids.worker_id

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

    def _split_worker_shares(self):
        """Fill or check each worker's share of the good metres."""
        self.ensure_one()
        lines = self.line_ids
        if not lines:
            raise UserError('Add at least one worker to this production entry.')
        total = sum(lines.mapped('share_metres'))
        if float_is_zero(total, precision_digits=2):
            each = float_round(self.good_metres / len(lines), precision_digits=2)
            remaining = self.good_metres
            for line in lines[:-1]:
                line.share_metres = each
                remaining -= each
            lines[-1].share_metres = float_round(remaining, precision_digits=2)
        elif float_compare(total, self.good_metres, precision_digits=2) != 0:
            raise UserError(
                'The workers\' shares (%.2f m) must add up to the good fabric '
                '(%.2f m). Leave all shares at 0 for an equal split.'
                % (total, self.good_metres))

    def action_confirm(self):
        self._textile_lock_rows()
        for record in self:
            if record.state != 'draft':
                raise UserError('This production entry is already confirmed.')
            if record.order_id.state != 'open':
                raise UserError(
                    'Order %s is not open. Production can only be confirmed '
                    'for an open order.' % record.order_id.name)
            record._split_worker_shares()
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


class TextileProductionWorker(models.Model):
    """A worker's share of one shift entry (the basis for worker pay)."""

    _name = 'textile.production.worker'
    _description = 'Production Entry Worker'
    _order = 'production_id, id'

    production_id = fields.Many2one(
        'textile.production', string='Production Entry', required=True,
        ondelete='cascade',
    )
    worker_id = fields.Many2one(
        'textile.worker', string='Worker', required=True,
    )
    share_metres = fields.Float(
        string='Share of Good Fabric (m)',
        help='Leave at 0 on every worker for an equal split when the entry '
             'is confirmed.',
    )
    # copies of the entry's data, so worker-wise reports are simple
    date = fields.Date(related='production_id.date', store=True)
    shift = fields.Selection(related='production_id.shift', store=True)
    loom_id = fields.Many2one(related='production_id.loom_id', store=True)
    order_id = fields.Many2one(related='production_id.order_id', store=True)
    production_state = fields.Selection(related='production_id.state', store=True)

    _worker_uniq = models.Constraint(
        'UNIQUE(production_id, worker_id)',
        'This worker is already listed on the entry.',
    )

    @api.constrains('share_metres')
    def _check_share(self):
        for line in self:
            if line.share_metres < 0:
                raise ValidationError('A worker\'s share cannot be negative.')

    def _check_open(self):
        if any(line.production_id.state == 'confirmed' for line in self):
            raise UserError('The workers of a confirmed production entry cannot be changed.')

    @api.model_create_multi
    def create(self, vals_list):
        entries = self.env['textile.production'].browse(
            [v['production_id'] for v in vals_list if v.get('production_id')])
        if any(e.state == 'confirmed' for e in entries):
            raise UserError('The workers of a confirmed production entry cannot be changed.')
        return super().create(vals_list)

    def write(self, vals):
        if set(vals) - {'production_state'}:
            self._check_open()
        return super().write(vals)

    def unlink(self):
        self._check_open()
        return super().unlink()
