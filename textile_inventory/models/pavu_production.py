from odoo import models, fields
from odoo.exceptions import UserError


class YarnAllocation(models.Model):
    _name = 'textile.yarn.allocation'
    _description = 'Yarn Allocation to Loom'
    _order = 'id desc'

    product_id = fields.Many2one(
        'product.product',
        string='Yarn Product',
        required=True,
        domain=[('type', '=', 'consu')],
    )

    loom_id = fields.Many2one(
        'textile.loom',
        string='Loom',
        required=True,
    )

    quantity = fields.Float(
        string='Quantity (kg)',
        required=True,
    )

    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('allocated', 'Allocated'),
        ],
        string='Status',
        default='draft',
        readonly=True,
    )

    allocation_date = fields.Datetime(
        string='Allocation Date',
        default=fields.Datetime.now,
        readonly=True,
    )

    notes = fields.Text(
        string='Notes',
    )

    def action_allocate(self):
        """Move yarn from main Godown stock to Loom Allocation stock."""

        for record in self:

            # -------------------------------------------------
            # 1. VALIDATIONS
            # -------------------------------------------------

            if record.state == 'allocated':
                raise UserError(
                    'This yarn allocation has already been completed.'
                )

            if not record.product_id:
                raise UserError(
                    'Please select a yarn product.'
                )

            if not record.loom_id:
                raise UserError(
                    'Please select a loom.'
                )

            if record.quantity <= 0:
                raise UserError(
                    'Allocation quantity must be greater than zero.'
                )

            # -------------------------------------------------
            # 2. MAIN GODOWN / STOCK LOCATION
            # -------------------------------------------------

            source_location = self.env['stock.location'].search([
                ('usage', '=', 'internal'),
                ('company_id', '=', self.env.company.id),
            ], order='id', limit=1)

            if not source_location:
                raise UserError(
                    'Could not find the main internal stock location.'
                )

            # -------------------------------------------------
            # 3. LOOM ALLOCATION LOCATION
            # -------------------------------------------------

            destination_location = self.env['stock.location'].search([
                ('name', '=', 'Loom Allocation'),
                ('usage', '=', 'internal'),
                ('company_id', '=', self.env.company.id),
            ], limit=1)

            if not destination_location:
                raise UserError(
                    'Loom Allocation location was not found.\n\n'
                    'Please make sure the Loom Allocation stock location '
                    'has been created.'
                )

            # -------------------------------------------------
            # 4. CHECK AVAILABLE YARN
            # -------------------------------------------------

            available_qty = self.env[
                'stock.quant'
            ]._get_available_quantity(
                record.product_id,
                source_location,
            )

            if available_qty < record.quantity:
                raise UserError(
                    f'Not enough yarn available in Godown.\n\n'
                    f'Product: {record.product_id.name}\n'
                    f'Available: {available_qty:.2f} kg\n'
                    f'Requested: {record.quantity:.2f} kg'
                )

            # -------------------------------------------------
            # 5. CREATE INTERNAL STOCK MOVE
            # -------------------------------------------------

            move = self.env['stock.move'].create({
                'product_id': record.product_id.id,
                'product_uom_qty': record.quantity,
                'product_uom': record.product_id.uom_id.id,
                'location_id': source_location.id,
                'location_dest_id': destination_location.id,
            })

            # -------------------------------------------------
            # 6. CONFIRM MOVE
            # -------------------------------------------------

            move._action_confirm()

            # -------------------------------------------------
            # 7. ASSIGN MOVE
            # -------------------------------------------------

            move._action_assign()

            # -------------------------------------------------
            # 8. SET ACTUAL QUANTITY
            # -------------------------------------------------

            move.quantity = record.quantity

            # -------------------------------------------------
            # 9. MARK PICKED
            # -------------------------------------------------

            move.picked = True

            # -------------------------------------------------
            # 10. COMPLETE STOCK MOVE
            # -------------------------------------------------

            move._action_done()

            # -------------------------------------------------
            # 11. VERIFY
            # -------------------------------------------------

            if move.state != 'done':
                raise UserError(
                    'The yarn transfer could not be completed.'
                )

            # -------------------------------------------------
            # 12. MARK ALLOCATION COMPLETE
            # -------------------------------------------------

            record.state = 'allocated'

        return True
