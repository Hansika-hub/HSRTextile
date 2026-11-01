# Run inside the Odoo shell:
#   python odoo-bin shell -c odoo.conf -d <DB> < custom-addons/scripts/cancel_unfinished_moves.py
# Cancels stock moves that were left half-finished (never validated) by the
# earlier prototype code. Uses Odoo's own cancel, so reservations are released.
# It does NOT touch finished (done) moves.
open_states = ('assigned', 'confirmed', 'partially_available', 'waiting')
moves = env['stock.move'].search([('state', 'in', open_states)])
print('Unfinished moves found:', moves.ids)
for m in moves:
    print(' ', m.id, m.product_id.display_name, m.product_uom_qty, m.location_id.complete_name, '->', m.location_dest_id.complete_name, m.state)
moves._action_cancel()
env.cr.commit()
left = env['stock.move'].search_count([('state', 'in', open_states)])
print('Unfinished moves left:', left)
for q in env['stock.quant'].search([('location_id.usage', '=', 'internal')]):
    print('QUANT', q.product_id.display_name, q.location_id.complete_name, 'qty', q.quantity, 'reserved', q.reserved_quantity)
