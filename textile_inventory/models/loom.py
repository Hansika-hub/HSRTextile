from odoo import api, fields, models


class TextileLoom(models.Model):
    _name = 'textile.loom'
    _description = 'Textile Loom'
    _inherit = ['mail.thread']
    _order = 'code'

    name = fields.Char(string='Loom Name', required=True, tracking=True)
    code = fields.Char(string='Loom Code', required=True, tracking=True)
    active = fields.Boolean(string='Active', default=True)
    notes = fields.Text(string='Notes')
    allocation_ids = fields.One2many(
        'textile.yarn.allocation', 'loom_id', string='Yarn Allocations',
    )
    allocation_count = fields.Integer(compute='_compute_allocation_count')

    _code_uniq = models.Constraint(
        'UNIQUE(code)', 'Each loom must have a unique code.'
    )

    @api.depends('allocation_ids')
    def _compute_allocation_count(self):
        for loom in self:
            loom.allocation_count = len(loom.allocation_ids)

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
