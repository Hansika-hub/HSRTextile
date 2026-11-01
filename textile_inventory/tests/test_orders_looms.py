from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install', 'textile')
class TestOrdersLooms(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        kg = cls.env.ref('uom.product_uom_kgm')
        metre = cls.env.ref('uom.product_uom_meter')
        Product = cls.env['product.product']
        cls.yarn = Product.create({'name': 'T3 Yarn', 'is_storable': True, 'uom_id': kg.id})
        cls.pavu = Product.create({'name': 'T3 Pavu', 'is_storable': True, 'uom_id': metre.id})
        cls.vendor = cls.env['res.partner'].create({'name': 'T3 Vendor'})
        cls.other_vendor = cls.env['res.partner'].create({'name': 'T3 Other Vendor'})
        cls.loom = cls.env['textile.loom'].create({'name': 'T3 Loom', 'code': 'T3-01'})
        cls.godown = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1).lot_stock_id

    def _order(self, confirm=True, **kw):
        vals = {'order_ref': 'V-%s' % self.env['ir.sequence'].next_by_code('textile.order'),
                'partner_id': self.vendor.id, 'required_fabric_m': 5000,
                'expected_yarn_kg': 1000, 'expected_pavu_m': 10000}
        vals.update(kw)
        order = self.env['textile.order'].create(vals)
        if confirm:
            order.action_confirm()
        return order

    def _yarn(self, order, bags=2, size=50.0, **kw):
        vals = {'order_id': order.id, 'partner_id': order.partner_id.id,
                'product_id': self.yarn.id, 'bag_size': size, 'number_of_bags': bags}
        vals.update(kw)
        return self.env['textile.yarn.bag.line'].create(vals)

    # ---- orders --------------------------------------------------------
    def test_order_defaults_and_numbering(self):
        order = self._order(confirm=False)
        self.assertTrue(order.name.startswith('ORD/'))
        self.assertEqual(order.state, 'draft')
        self.assertEqual((order.roll_length_min, order.roll_length_max), (130, 140))

    def test_order_validation(self):
        with self.assertRaises(ValidationError):
            self._order(required_fabric_m=0)
        with self.assertRaises(ValidationError):
            self._order(order_date='2026-11-10', expected_date='2026-11-01')
        with self.assertRaises(ValidationError):
            self._order(roll_length_min=150, roll_length_max=140)

    def test_duplicate_vendor_order_ref_blocked(self):
        self._order(order_ref='DUP-1')
        with self.assertRaises(Exception), mute_logger('odoo.sql_db'):
            self._order(order_ref='DUP-1')

    def test_order_progress_counts_only_received(self):
        order = self._order()
        r1 = self._yarn(order, bags=5, size=50)       # 250
        r2 = self._yarn(order, bags=2, size=60)       # 120, stays draft
        r1.action_receive()
        pavu = self.env['textile.pavu.receipt'].create({
            'order_id': order.id, 'partner_id': self.vendor.id,
            'product_id': self.pavu.id,
            'line_ids': [Command.create({'roll_length': 1200, 'number_of_rolls': 5}),
                         Command.create({'roll_length': 1000, 'number_of_rolls': 3})]})
        pavu.action_receive()
        self.assertEqual(order.yarn_received_kg, 250)
        self.assertEqual(order.yarn_pending_kg, 750)
        self.assertEqual(order.pavu_received_m, 9000)
        self.assertEqual(order.pavu_pending_m, 1000)
        self.assertEqual(order.yarn_receipt_count, 2)
        self.assertEqual(r2.state, 'draft')

    def test_receipt_needs_open_order_of_same_vendor(self):
        draft_order = self._order(confirm=False)
        with self.assertRaises(UserError):
            self._yarn(draft_order).action_receive()
        order = self._order()
        no_order = self.env['textile.yarn.bag.line'].create({
            'product_id': self.yarn.id, 'bag_size': 50, 'number_of_bags': 1})
        with self.assertRaises(UserError):
            no_order.action_receive()
        wrong_vendor = self._yarn(order, partner_id=self.other_vendor.id)
        with self.assertRaises(UserError):
            wrong_vendor.action_receive()
        self.assertEqual(wrong_vendor.state, 'draft')

    def test_order_cancel_and_close_rules(self):
        order = self._order()
        self._yarn(order).action_receive()
        with self.assertRaises(UserError):
            order.action_cancel()
        order.action_done()
        self.assertEqual(order.state, 'done')
        with self.assertRaises(UserError):
            self._yarn(order).action_receive()   # closed order takes no stock
        empty = self._order()
        empty.action_cancel()
        self.assertEqual(empty.state, 'cancel')
        empty.unlink()

    def test_pavu_totals_per_length_view_data(self):
        order = self._order()
        receipt = self.env['textile.pavu.receipt'].create({
            'order_id': order.id, 'partner_id': self.vendor.id, 'product_id': self.pavu.id,
            'line_ids': [Command.create({'roll_length': 800, 'number_of_rolls': 4})]})
        receipt.action_receive()
        lines = self.env['textile.pavu.receipt.line'].search(
            [('order_id', '=', order.id), ('state', '=', 'done')])
        self.assertEqual(sum(lines.mapped('total_metres')), 3200)
        self.assertEqual(lines.partner_id, self.vendor)

    # ---- looms ---------------------------------------------------------
    def test_loom_status_follows_breakdown(self):
        loom = self.env['textile.loom'].create({'name': 'S', 'code': 'T3-S'})
        self.assertEqual(loom.status, 'idle')
        loom.working_state = 'running'
        self.assertEqual(loom.status, 'running')
        breakdown = self.env['textile.loom.breakdown'].create(
            {'loom_id': loom.id, 'reason': 'Belt snapped'})
        self.assertEqual(loom.status, 'breakdown')
        breakdown.action_resolve()
        self.assertEqual(loom.status, 'running')
        with self.assertRaises(UserError):
            breakdown.action_resolve()

    def test_breakdown_rules(self):
        loom = self.env['textile.loom'].create({'name': 'R', 'code': 'T3-R'})
        start = fields.Datetime.now() - timedelta(hours=5)
        closed = self.env['textile.loom.breakdown'].create({
            'loom_id': loom.id, 'reason': 'Motor', 'start_datetime': start,
            'end_datetime': start + timedelta(hours=3)})
        self.assertAlmostEqual(closed.duration_hours, 3.0, places=2)
        with self.assertRaises(ValidationError):
            self.env['textile.loom.breakdown'].create({
                'loom_id': loom.id, 'reason': 'Bad dates', 'start_datetime': start,
                'end_datetime': start - timedelta(hours=1)})
        self.env['textile.loom.breakdown'].create({'loom_id': loom.id, 'reason': 'Open 1'})
        with self.assertRaises(ValidationError):
            self.env['textile.loom.breakdown'].create({'loom_id': loom.id, 'reason': 'Open 2'})

    def test_no_allocation_to_broken_loom(self):
        order = self._order()
        self._yarn(order, bags=2, size=50).action_receive()
        self.env['textile.loom.breakdown'].create({'loom_id': self.loom.id, 'reason': 'Shuttle'})
        allocation = self.env['textile.yarn.allocation'].create({
            'order_id': order.id, 'product_id': self.yarn.id,
            'loom_id': self.loom.id, 'quantity': 10})
        with self.assertRaises(UserError):
            allocation.action_allocate()
        self.assertEqual(allocation.state, 'draft')
        self.loom.breakdown_ids.action_resolve()
        allocation.action_allocate()
        self.assertEqual(allocation.state, 'allocated')
        self.assertEqual(order.yarn_allocated_kg, 10)

    # ---- empty rolls ---------------------------------------------------
    def test_empty_roll_balance(self):
        Log = self.env['textile.empty.roll.log']
        before = sum(Log.search([]).mapped('signed_quantity'))
        Log.create({'action': 'collected', 'quantity': 10})
        Log.create({'action': 'reused', 'quantity': 4})
        Log.create({'action': 'returned', 'quantity': 2})
        self.assertEqual(sum(Log.search([]).mapped('signed_quantity')) - before, 4)
        with self.assertRaises(ValidationError):
            Log.create({'action': 'collected', 'quantity': 0})

    # ---- permissions ---------------------------------------------------
    def test_order_permissions(self):
        def user(login, xmlid):
            return self.env['res.users'].with_context(no_reset_password=True).create({
                'name': login, 'login': login,
                'group_ids': [Command.set([self.env.ref(xmlid).id])]})
        accountant = user('t3_acc', 'textile_inventory.group_textile_accountant')
        supervisor = user('t3_sup', 'textile_inventory.group_textile_supervisor')
        manager = user('t3_inv', 'textile_inventory.group_textile_inventory')
        order = self._order()
        self.assertEqual(order.with_user(accountant).name, order.name)
        with self.assertRaises(AccessError):
            order.with_user(accountant).write({'notes': 'x'})
        with self.assertRaises(AccessError):
            order.with_user(supervisor).write({'notes': 'x'})
        order.with_user(manager).write({'notes': 'ok'})
        with self.assertRaises(AccessError):
            order.with_user(manager).unlink()
        # supervisor can report a breakdown
        self.env['textile.loom.breakdown'].with_user(supervisor).create(
            {'loom_id': self.env['textile.loom'].create({'name': 'P', 'code': 'T3-P'}).id,
             'reason': 'Reported by supervisor'})
