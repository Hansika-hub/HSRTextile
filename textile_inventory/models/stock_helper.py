from odoo import Command, models
from odoo.exceptions import UserError
from odoo.tools import float_compare


class TextileStockMixin(models.AbstractModel):
    """Shared helpers so every textile document uses Odoo's standard
    stock documents (stock.picking) instead of hand-made stock moves."""

    _name = 'textile.stock.mixin'
    _description = 'Textile stock helpers'

    def _textile_lock(self):
        """Lock the records so a double click or a second user cannot
        process the same document twice, then reload fresh values."""
        if not self.ids:
            return
        try:
            self.env.cr.execute(
                'SELECT id FROM "%s" WHERE id IN %%s FOR UPDATE NOWAIT'
                % self._table,
                (tuple(self.ids),),
            )
        except Exception as error:
            if getattr(error, 'pgcode', None) == '55P03':
                raise UserError(
                    'Another user (or a second click) is already '
                    'processing this document. Please wait and refresh.'
                ) from error
            raise
        self.invalidate_recordset()

    def _textile_warehouse(self):
        warehouse = self.env['stock.warehouse'].search(
            [('company_id', '=', self.env.company.id)], limit=1
        )
        if not warehouse:
            raise UserError('No warehouse (godown) is set up for this company.')
        return warehouse

    def _textile_check_product(self, product, uom_xmlid, uom_label):
        """Yarn must be in kg, Pavu / fabric in metres, and the product
        must be a tracked (storable) product so quantities are kept."""
        if not product:
            raise UserError('Please select a product.')
        if not product.is_storable:
            raise UserError(
                'Product "%s" is not set to track inventory. Open the '
                'product and turn on "Track Inventory".' % product.display_name
            )
        uom = self.env.ref(uom_xmlid)
        if product.uom_id != uom:
            raise UserError(
                'Product "%s" must use the unit "%s" (it uses "%s").'
                % (product.display_name, uom_label, product.uom_id.name)
            )
        return uom

    def _textile_transfer(self, picking_type, partner, origin, product,
                          qty, uom, source, dest):
        """Create, reserve and validate one standard transfer.
        Raises UserError (which rolls everything back) if stock is short."""
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'partner_id': partner.id if partner else False,
            'origin': origin,
            'location_id': source.id,
            'location_dest_id': dest.id,
            'move_ids': [Command.create({
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': uom.id,
                'location_id': source.id,
                'location_dest_id': dest.id,
            })],
        })
        picking.action_confirm()
        picking.action_assign()
        if picking.state != 'assigned':
            raise UserError(
                'Not enough stock of "%s" in %s to move %.2f %s.'
                % (product.display_name, source.complete_name, qty, uom.name)
            )
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        picking.with_context(
            skip_backorder=True, skip_sms=True, skip_expired=True
        ).button_validate()
        if picking.state != 'done':
            raise UserError(
                'The stock transfer %s could not be completed.' % picking.name
            )
        done_qty = sum(picking.move_ids.mapped('quantity'))
        if float_compare(done_qty, qty, precision_digits=3) != 0:
            raise UserError('The transferred quantity does not match.')
        return picking
