from odoo import models, fields, api
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
        """Move yarn from Godown stock to Loom Allocation stock."""

        for record in self:

            # ---------------------------------------------
            # 1. VALIDATIONS
            # ---------------------------------------------

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

            # ---------------------------------------------
            # 2. GODOWN / MAIN STOCK LOCATION
            # ---------------------------------------------

            source_location = self.env.ref(
                'stock.stock_location_stock'
            )

            # ---------------------------------------------
            # 3. LOOM ALLOCATION LOCATION
            # ---------------------------------------------

            destination_location = self.env.ref(
                'textile_inventory.location_loom_allocation'
            )

            # ---------------------------------------------
            # 4. CHECK AVAILABLE STOCK
            # ---------------------------------------------

            available_qty = self.env['stock.quant']._get_available_quantity(
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

            # ---------------------------------------------
            # 5. CREATE INTERNAL STOCK MOVE
            # ---------------------------------------------

            move = self.env['stock.move'].create({
                'product_id': record.product_id.id,
                'product_uom_qty': record.quantity,
                'product_uom': record.product_id.uom_id.id,
                'location_id': source_location.id,
                'location_dest_id': destination_location.id,
            })

            # ---------------------------------------------
            # 6. CONFIRM
            # ---------------------------------------------

            move._action_confirm()

            # ---------------------------------------------
            # 7. ASSIGN
            # ---------------------------------------------

            move._action_assign()

            # ---------------------------------------------
            # 8. SET ACTUAL QUANTITY
            # ---------------------------------------------

            if not move.move_line_ids:
                raise UserError(
                    'Odoo could not create a stock move line.'
                )

            move.move_line_ids.write({
                'quantity': record.quantity,
            })

            # ---------------------------------------------
            # 9. MARK PICKED
            # ---------------------------------------------

            move.picked = True

            # ---------------------------------------------
            # 10. COMPLETE TRANSFER
            # ---------------------------------------------

            move._action_done()
