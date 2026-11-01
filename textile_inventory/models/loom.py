from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class TextileLoom(models.Model):
    _name = 'textile.loom'
    _description = 'Textile Loom'
    _inherit = ['mail.thread']
    _order = 'code'

    name = fields.Char(string='Loom Name', required=True, tracking=True)
    code = fields.Char(string='Loom Code', required=True, tracking=True)
    active = fields.Boolean(string='Active', default=True)
    notes = fields.Text(string='Notes')
    working_state = fields.Selection(
        [('idle', 'Idle'), ('running', 'Running')],
        string='Working Status', default='idle', required=True, tracking=True,
    )
    status = fields.Selection(
        [('idle', 'Idle'), ('running', 'Running'), ('breakdown', 'Breakdown')],
        string='Status', compute='_compute_status', store=True,
        help='Shows Breakdown whenever the loom has an unresolved breakdown.',
    )
    allocation_ids = fields.One2many(
        'textile.yarn.allocation', 'loom_id', string='Yarn Allocations',
    )
    breakdown_ids = fields.One2many(
        'textile.loom.breakdown', 'loom_id', string='Breakdowns',
    )
    allocation_count = fields.Integer(compute='_compute_counts')
    breakdown_count = fields.Integer(compute='_compute_counts')

    _code_uniq = models.Constraint(
        'UNIQUE(code)', 'Each loom must have a unique code.'
    )

    @api.depends('working_state', 'breakdown_ids.end_datetime')
    def _compute_status(self):
        for loom in self:
            if loom.breakdown_ids.filtered(lambda b: not b.end_datetime):
                loom.status = 'breakdown'
            else:
                loom.status = loom.working_state

    @api.depends('allocation_ids', 'breakdown_ids')
    def _compute_counts(self):
        for loom in self:
            loom.allocation_count = len(loom.allocation_ids)
            loom.breakdown_count = len(loom.breakdown_ids)

    def action_view_allocations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Yarn Allocations',
            'res_model': 'textile.yarn.allocation',
            'view_mode': 'list,form',
            'domain': [('loom_id', '=', self.id)],
            'context': {'default_loom_id': self.id},
        }

    def action_view_breakdowns(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Breakdowns',
            'res_model': 'textile.loom.breakdown',
            'view_mode': 'list,form',
            'domain': [('loom_id', '=', self.id)],
            'context': {'default_loom_id': self.id},
        }


class TextileLoomBreakdown(models.Model):
    _name = 'textile.loom.breakdown'
    _description = 'Loom Breakdown'
    _order = 'start_datetime desc'

    loom_id = fields.Many2one(
        'textile.loom', string='Loom', required=True, ondelete='restrict',
    )
    start_datetime = fields.Datetime(
        string='Breakdown Started', required=True, default=fields.Datetime.now,
    )
    end_datetime = fields.Datetime(string='Repaired / Back in Use')
    reason = fields.Char(string='Reason', required=True)
    reported_by_id = fields.Many2one(
        'res.users', string='Reported By',
        default=lambda self: self.env.user, readonly=True,
    )
    duration_hours = fields.Float(
        string='Downtime (hours)', compute='_compute_duration',
    )
    is_open = fields.Boolean(string='Still Broken', compute='_compute_duration')

    @api.depends('start_datetime', 'end_datetime')
    def _compute_duration(self):
        now = fields.Datetime.now()
        for record in self:
            record.is_open = not record.end_datetime
            if record.start_datetime:
                end = record.end_datetime or now
                record.duration_hours = (
                    (end - record.start_datetime).total_seconds() / 3600.0)
            else:
                record.duration_hours = 0.0

    @api.constrains('start_datetime', 'end_datetime', 'loom_id')
    def _check_breakdown(self):
        for record in self:
            if record.end_datetime and record.end_datetime < record.start_datetime:
                raise ValidationError('Repair time cannot be before the breakdown time.')
            if not record.end_datetime:
                others = self.search_count([
                    ('loom_id', '=', record.loom_id.id),
                    ('end_datetime', '=', False),
                    ('id', '!=', record.id),
                ])
                if others:
                    raise ValidationError(
                        'This loom already has an unresolved breakdown. '
                        'Mark it as repaired first.')

    def action_resolve(self):
        for record in self:
            if record.end_datetime:
                raise UserError('This breakdown is already resolved.')
            record.end_datetime = fields.Datetime.now()
        return True
