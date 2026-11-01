from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'textile')
class TestDispatch(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        metre = cls.env.ref('uom.product_uom_meter')
        cls.fabric = cls.env['product.product'].create(
            {'name': 'T5 Fabric', 'is_storable': True, 'uom_id': metre.id})
        cls.vendor = cls.env['res.partner'].create({'name': 'T5 Vendor'})
        cls.loom = cls.env['textile.loom'].create({'name': 'T5 Loom', 'code': 'T5-01'})
        cls.worker = cls.env['textile.worker'].create({'name': 'T5 Worker'})
        cls.finished = cls.env.ref('textile_inventory.location_finished_fabric')
        cls.counter = 0

    def _order(self):
        type(self).counter += 1
        order = self.env['textile.order'].create({
            'order_ref': 'T5-%s' % self.counter, 'partner_id': self.vendor.id,
            'required_fabric_m': 5000})
        order.action_confirm()
        return order

    def _rolls(self, order, lengths):
        type(self).counter += 1
        entry = self.env['textile.production'].create({
            'order_id': order.id, 'loom_id': self.loom.id,
            'line_ids': [Command.create({'worker_id': self.worker.id})],
            'shift': 'day', 'date': '2026-%02d-%02d' % (1 + self.counter // 28 % 12, 1 + self.counter % 28),
            'metres_produced': sum(lengths)})
        entry.action_confirm()
        rolls = self.env['textile.fabric.roll']
        for length in lengths:
            roll = self.env['textile.fabric.roll'].create({
                'order_id': order.id, 'product_id': self.fabric.id,
                'length_m': length, 'production_ids': [Command.set(entry.ids)]})
            roll.action_confirm()
            rolls |= roll
        return rolls

    def _dispatch(self, order, rolls, **kw):
        vals = {'order_id': order.id, 'destination': 'Mill', 'vehicle_no': 'TN01AB1234',
                'roll_ids': [Command.set(rolls.ids)]}
        vals.update(kw)
        return self.env['textile.dispatch'].create(vals)

    def _qty(self):
        return self.env['stock.quant']._get_available_quantity(self.fabric, self.finished)

    # ---- dispatch ------------------------------------------------------
    def test_totals_and_stock_out(self):
        order = self._order()
        rolls = self._rolls(order, [130, 135, 140])
        before = self._qty()
        disp = self._dispatch(order, rolls)
        self.assertEqual((disp.roll_count, disp.total_metres), (3, 405))
        self.assertTrue(disp.name.startswith('DSP/'))
        disp.action_confirm()
        self.assertEqual(disp.state, 'dispatched')
        self.assertEqual(self._qty(), before - 405)
        self.assertEqual(set(rolls.mapped('state')), {'dispatched'})
        self.assertEqual(rolls.mapped('dispatch_id'), disp)
        self.assertEqual(disp.reconciliation_state, 'pending')
        self.assertEqual((order.fabric_dispatched_m, order.fabric_stock_m, order.mill_pending_m),
                         (405, 0, 405))

    def test_rules(self):
        order = self._order()
        rolls = self._rolls(order, [130, 135])
        with self.assertRaises(UserError):
            self._dispatch(order, self.env['textile.fabric.roll']).action_confirm()   # no rolls
        with self.assertRaises(UserError):
            self._dispatch(order, rolls, vehicle_no='  ').action_confirm()            # no vehicle
        other = self._order()
        foreign = self._rolls(other, [132])
        with self.assertRaises(UserError):
            self._dispatch(order, foreign).action_confirm()                           # other order
        draft_roll = self.env['textile.fabric.roll'].create({
            'order_id': order.id, 'product_id': self.fabric.id, 'length_m': 133,
            'production_ids': [Command.set(rolls[0].production_ids.ids)]})
        with self.assertRaises(UserError):
            self._dispatch(order, draft_roll).action_confirm()                        # not in stock
        disp = self._dispatch(order, rolls)
        disp.action_confirm()
        with self.assertRaises(UserError):
            disp.action_confirm()                                                     # twice
        with self.assertRaises(UserError):
            self._dispatch(order, rolls).action_confirm()                             # same rolls again
        with self.assertRaises(UserError):
            disp.write({'roll_ids': [Command.clear()]})                               # locked
        with self.assertRaises(UserError):
            disp.unlink()
        with self.assertRaises(UserError):
            order.action_cancel()

    def test_closed_order_cannot_dispatch(self):
        order = self._order()
        rolls = self._rolls(order, [130])
        disp = self._dispatch(order, rolls)
        order.action_done()
        with self.assertRaises(UserError):
            disp.action_confirm()

    def test_cancel_restores_stock(self):
        order = self._order()
        rolls = self._rolls(order, [130, 140])
        before = self._qty()
        disp = self._dispatch(order, rolls)
        disp.action_confirm()
        disp.action_cancel()
        self.assertEqual(disp.state, 'cancel')
        self.assertEqual(self._qty(), before)
        self.assertEqual(set(rolls.mapped('state')), {'available'})
        self.assertFalse(rolls.mapped('dispatch_id'))
        with self.assertRaises(UserError):
            disp.action_cancel()
        # the rolls can go out again on a new load
        self._dispatch(order, rolls).action_confirm()

    # ---- reconciliation ------------------------------------------------
    def _recon(self, disp, **kw):
        vals = {'dispatch_id': disp.id, 'rolls_received': disp.roll_count,
                'accepted_m': disp.total_metres}
        vals.update(kw)
        return self.env['textile.reconciliation'].create(vals)

    def _sent(self, lengths=(130, 135, 140)):
        order = self._order()
        disp = self._dispatch(order, self._rolls(order, list(lengths)))
        disp.action_confirm()
        return order, disp

    def test_reconciliation_matched(self):
        order, disp = self._sent()
        rec = self._recon(disp)
        self.assertTrue(rec.name.startswith('REC/'))
        self.assertEqual(rec.missing_m, 0)
        rec.action_confirm()
        self.assertEqual(disp.reconciliation_state, 'matched')
        self.assertEqual((order.mill_accepted_m, order.mill_pending_m, order.mill_missing_m), (405, 0, 0))

    def test_reconciliation_discrepancy_and_history(self):
        order, disp = self._sent()
        first = self._recon(disp, rolls_received=2, accepted_m=260, rejected_m=10)
        self.assertEqual((first.missing_m, first.missing_rolls), (135, 1))
        first.action_confirm()
        self.assertEqual(disp.reconciliation_state, 'discrepancy')
        self.assertEqual((disp.mill_accepted_m, disp.mill_rejected_m, disp.mill_missing_m), (260, 10, 135))
        self.assertEqual(order.mill_missing_m, 135)
        # a correction supersedes the first, which stays as history
        second = self._recon(disp, rolls_received=3, accepted_m=395, rejected_m=10)
        second.action_confirm()
        self.assertEqual(first.state, 'superseded')
        self.assertEqual(second.state, 'confirmed')
        self.assertEqual(disp.reconciliation_count, 2)
        self.assertEqual(disp.mill_missing_m, 0)
        self.assertEqual(disp.reconciliation_state, 'discrepancy')   # rejected metres remain
        with self.assertRaises(UserError):
            first.write({'accepted_m': 1})
        with self.assertRaises(UserError):
            second.unlink()
        with self.assertRaises(UserError):
            disp.action_cancel()                                     # mill check confirmed

    def test_reconciliation_validation(self):
        order, disp = self._sent()
        with self.assertRaises(ValidationError):
            self._recon(disp, accepted_m=-1)
        rec = self._recon(disp, accepted_m=500)                      # more than sent
        self.assertEqual(rec.missing_m, -95)
        self.assertTrue(rec.has_discrepancy)
        draft_disp = self._dispatch(order, self.env['textile.fabric.roll'])
        with self.assertRaises(Exception):
            self._recon(draft_disp).action_confirm()

    # ---- reports -------------------------------------------------------
    def test_reports_render(self):
        order, disp = self._sent()
        rec = self._recon(disp)
        rec.action_confirm()
        for xmlid, rec_ in (
                ('textile_inventory.report_dispatch', disp),
                ('textile_inventory.report_reconciliation', rec)):
            html, _ = self.env['ir.actions.report']._render_qweb_html(xmlid, rec_.ids)
            self.assertIn(rec_.name.encode(), html)
        self.assertIn(b'DSP/', self.env['ir.actions.report']._render_qweb_html(
            'textile_inventory.report_dispatch', disp.ids)[0])

    # ---- permissions ---------------------------------------------------
    def test_permissions(self):
        def user(login, xmlid):
            return self.env['res.users'].with_context(no_reset_password=True).create({
                'name': login, 'login': login,
                'group_ids': [Command.set([self.env.ref(xmlid).id])]})
        manager = user('t5_inv', 'textile_inventory.group_textile_inventory')
        accountant = user('t5_acc', 'textile_inventory.group_textile_accountant')
        supervisor = user('t5_sup', 'textile_inventory.group_textile_supervisor')
        order = self._order()
        rolls = self._rolls(order, [130])
        vals = {'order_id': order.id, 'destination': 'Mill', 'vehicle_no': 'TN01',
                'roll_ids': [Command.set(rolls.ids)]}
        disp = self.env['textile.dispatch'].with_user(manager).create(vals)
        with self.assertRaises(AccessError):
            self.env['textile.dispatch'].with_user(accountant).create(dict(vals))
        with self.assertRaises(AccessError):
            self.env['textile.dispatch'].with_user(supervisor).create(dict(vals))
        disp.with_user(manager).action_confirm()
        disp.with_user(supervisor).read(['name'])
        rec = self.env['textile.reconciliation'].with_user(accountant).create({
            'dispatch_id': disp.id, 'rolls_received': 1, 'accepted_m': 130})
        rec.with_user(accountant).action_confirm()
        with self.assertRaises(AccessError):
            self.env['textile.reconciliation'].with_user(supervisor).create({
                'dispatch_id': disp.id, 'rolls_received': 1, 'accepted_m': 130})
