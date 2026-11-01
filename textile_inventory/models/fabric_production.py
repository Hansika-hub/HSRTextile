from odoo import models, fields, api
from odoo.exceptions import UserError


class FabricProduction(models.Model):
    _name = 'textile.fabric.production'
    _description = 'Woven Fabric Production'
    _order = 'id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        default='New',
        readonly=True,
    )

    date = fields.Date(
        string='Production Date',
        required=True,
        default=fields.Date.context_today,
    )

    pavu_product_id = fields.Many2one(
        'product.product',
        string='Pavu Used',
        required=True,
        domain=[('name', 'ilike', 'Pavu')],
    )

    pavu_quantity = fields.Float(
        string='Pavu Used (m)',
        required=True,
    )

    fabric_product_id = fields.Many2one(
        'product.product',
        string='Woven Fabric Produced',
        required=True,
        domain=[('name', 'ilike', 'Woven Fabric')],
    )

    fabric_quantity = fields.Float(
        string='Fabric Produced (m)',
        required=True,
    )

    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('done', 'Produced'),
        ],
        string='Status',
        default='draft',
        readonly=True,
    )

    notes = fields.Text(
        string='Notes',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'textile.fabric.production'
                ) or 'FAB/NEW'

        return super().create(vals_list)

    def action_produce(self):
        """Consume Pavu and add produced woven fabric to stock."""

        for record in self:

            # -------------------------------------------------
            # 1. VALIDATIONS
            # -------------------------------------------------

            if record.state == 'done':
                raise UserError(
                    'This fabric production entry has already been completed.'
                )

            if not record.pavu_product_id:
                raise UserError(
                    'Please select the Pavu used.'
                )

            if not record.fabric_product_id:
                raise UserError(
                    'Please select the woven fabric product.'
                )

            if record.pavu_quantity <= 0:
                raise UserError(
                    'Pavu quantity must be greater than zero.'
                )

            if record.fabric_quantity <= 0:
                raise UserError(
                    'Fabric quantity must be greater than zero.'
                )

            # -------------------------------------------------
            # 2. FIND COMPANY STOCK LOCATION
            # -------------------------------------------------

            stock_location = self.env['stock.location'].search([
                ('usage', '=', 'internal'),
                ('company_id', '=', self.env.company.id),
            ], order='id', limit=1)

            if not stock_location:
                raise UserError(
                    'Could not find the company stock location.'
                )

            # -------------------------------------------------
            # 3. CHECK AVAILABLE PAVU
            # -------------------------------------------------

            available_pavu = self.env['stock.quant']._get_available_quantity(
                record.pavu_product_id,
                stock_location,
            )

            if available_pavu < record.pavu_quantity:
                raise UserError(
                    f'Not enough Pavu in stock.\n\n'
                    f'Available: {available_pavu:.2f} m\n'
                    f'Required: {record.pavu_quantity:.2f} m'
                )

            # -------------------------------------------------
            # 4. FIND OR CREATE PRODUCTION LOCATION
            # -------------------------------------------------

            production_location = self.env['stock.location'].search([
                ('usage', '=', 'production'),
                ('company_id', '=', self.env.company.id),
            ], order='id', limit=1)

            if not production_location:
                production_location = self.env['stock.location'].create({
                    'name': 'Textile Production',
                    'usage': 'production',
                    'location_id': stock_location.id,
                    'company_id': self.env.company.id,
                })

            # -------------------------------------------------
            # 5. CONSUME PAVU
            # -------------------------------------------------

            pavu_move = self.env['stock.move'].create({
                'product_id': record.pavu_product_id.id,
                'product_uom_qty': record.pavu_quantity,
                'product_uom': record.pavu_product_id.uom_id.id,
                'location_id': stock_location.id,
                'location_dest_id': production_location.id,
            })

            pavu_move._action_confirm()
            pavu_move._action_assign()

            pavu_move.quantity = record.pavu_quantity

            pavu_move._action_done()

            # -------------------------------------------------
            # 6. ADD WOVEN FABRIC TO STOCK
            # -------------------------------------------------

            fabric_move = self.env['stock.move'].create({
                'product_id': record.fabric_product_id.id,
                'product_uom_qty': record.fabric_quantity,
                'product_uom': record.fabric_product_id.uom_id.id,
                'location_id': production_location.id,
                'location_dest_id': stock_location.id,
            })

            fabric_move._action_confirm()

            fabric_move.quantity = record.fabric_quantity

            fabric_move._action_done()

            # -------------------------------------------------
            # 7. MARK AS PRODUCED
            # -------------------------------------------------

            record.state = 'done'

        return True
