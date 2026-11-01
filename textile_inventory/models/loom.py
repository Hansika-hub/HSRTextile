from odoo import models, fields


class TextileLoom(models.Model):
    _name = 'textile.loom'
    _description = 'Textile Loom'

    name = fields.Char(
        string='Loom Name',
        required=True,
    )

    code = fields.Char(
        string='Loom Code',
        required=True,
    )

    active = fields.Boolean(
        string='Active',
        default=True,
    )

    notes = fields.Text(
        string='Notes',
    )
