from odoo import models, fields, api
from odoo.exceptions import UserError


class YarnBagLine(models.Model):
    _name = 'textile.yarn.bag.line'
    _description = 'Yarn Bag Details'

    product_id = fields.Many2one(
        'product.product',
        string='Yarn Product',
        required=True,
        domain=[('type', '=', 'consu')],
    )

    bag_size = fields.Float(
        string='Bag Size (kg)',
        required=True,
    )

    number_of_bags = fields.Integer(
        string='Number of Bags',
        required=True,
        default=1,
    )

    total_weight = fields.Float(
        string='Total Weight (kg)',
        compute='_compute_total_weight',
        store=True,
    )

    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('done', 'Received'),
        ],
        string='Status',
        default='draft',
        readonly=True,
    )

    @api.depends('bag_size', 'number_of_bags')
    def _compute_total_weight(self):
        for record in self:
            record.total_weight = (
                record.bag_size * record.number_of_bags
            )

    def action_receive(self):
        """
        Receive yarn bags into Odoo stock.

        Example:
        2 bags × 50 kg = 100 kg
        """

        for record in self:

            # -------------------------------------------------
            # 1. VALIDATION
            # -------------------------------------------------

            if record.state == 'done':
                raise UserError(
                    'This yarn receipt has already been received.'
                )

            if not record.product_id:
                raise UserError(
                    'Please select a yarn product.'
                )

            if record.number_of_bags <= 0:
                raise UserError(
                    'Number of bags must be greater than zero.'
                )

            if record.bag_size <= 0:
                raise UserError(
                    'Bag size must be greater than zero.'
                )

            if record.total_weight <= 0:
                raise UserError(
                    'Total weight must be greater than zero.'
                )

            # -------------------------------------------------
            # 2. FIND INTERNAL STOCK LOCATION
            # -------------------------------------------------

            stock_location = self.env['stock.location'].search(
                [
                    ('usage', '=', 'internal'),
                    '|',
                    ('company_id', '=', self.env.company.id),
                    ('company_id', '=', False),
                ],
                order='id',
                limit=1,
            )

            if not stock_location:
                raise UserError(
                    'Could not find an internal stock location.'
                )

            # -------------------------------------------------
            # 3. FIND SUPPLIER LOCATION
            # -------------------------------------------------

            supplier_location = self.env['stock.location'].search(
                [
                    ('usage', '=', 'supplier'),
                ],
                order='id',
                limit=1,
            )

            if not supplier_location:
                raise UserError(
                    'Could not find a supplier location.'
                )

            # -------------------------------------------------
            # 4. CREATE STOCK MOVE
            # -------------------------------------------------

            move = self.env['stock.move'].create({
                'product_id': record.product_id.id,
                'product_uom_qty': record.total_weight,
                'product_uom': record.product_id.uom_id.id,
                'location_id': supplier_location.id,
                'location_dest_id': stock_location.id,
            })

            # -------------------------------------------------
            # 5. CONFIRM MOVE
            # -------------------------------------------------

            move._action_confirm()

            # -------------------------------------------------
            # 6. ASSIGN MOVE
            # -------------------------------------------------

            move._action_assign()

            # -------------------------------------------------
            # 7. SET ACTUAL RECEIVED QUANTITY
            # -------------------------------------------------

            if not move.move_line_ids:
                raise UserError(
                    'Odoo could not create a stock move line.'
                )

            move.move_line_ids.write({
                'quantity': record.total_weight,
            })

            # -------------------------------------------------
            # 8. MARK AS PICKED
            # -------------------------------------------------

            move.picked = True

            # -------------------------------------------------
            # 9. COMPLETE STOCK MOVE
            # -------------------------------------------------

            move._action_done()

            # -------------------------------------------------
            # 10. VERIFY MOVE
            # -------------------------------------------------

            if move.state != 'done':
                raise UserError(
                    'The stock movement could not be completed.'
                )

            # -------------------------------------------------
            # 11. MARK YARN RECEIPT AS RECEIVED
            # -------------------------------------------------

            record.state = 'done'

        return True
