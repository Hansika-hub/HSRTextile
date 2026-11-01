from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install', 'textile')
class TestProductionRolls(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        kg = cls.env.ref('uom.product_uom_kgm')
        metre = cls.env.ref('uom.product_uom_meter')
        unit = cls.env.ref('uom.product_uom_unit')
        Product = cls.env['product.product']
        cls.fabric = Product.create({'name': 'T4 Fabric', 'is_storable': True, 'uom_id': metre.id})
        cls.bad_fabric = Product.create({'name': 'T4 Fabric units', 'is_storable': True, 'uom_id': unit.id})
        cls.vendor = cls.env['res.partner'].create({'name': 'T4 Vendor'})
        cls.loom = cls.env['textile.loom'].create({'name': 'T4 Loom', 'code': 'T4-01'})
        cls.loom2 = cls.env['textile.loom'].create({'name': 'T4 Loom 2', 'code': 'T4-02'})
        cls.worker = cls.env['textile.worker'].create({'name': 'T4 Worker'})
        cls.worker2 = cls.env['textile.worker'].create({'name': 'T4 Worker 2'})
        cls.worker3 = cls.env['textile.worker'].create({'name': 'T4 Worker 3'})
        cls.finished = cls.env.ref('textile_inventory.location_finished_fabric')
        cls.counter = 0

    def _order(self, **kw):
        type(self).counter += 1
        vals = {'order_ref': 'T4-%s' % self.counter, 'partner_id': self.vendor.id,
                'required_fabric_m': 5000}
        vals.update(kw)
        order = self.env['textile.order'].create(vals)
        order.action_confirm()
        return order

    def _entry(self, order, produced=200, damaged=0, waste=0, rejected=0,
               loom=None, shift='day', date='2026-11-01', workers=None, confirm=True):
        entry = self.env['textile.production'].create({
            'order_id': order.id, 'loom_id': (loom or self.loom).id,
            'line_ids': [Command.create({'worker_id': w.id}) for w in (workers or self.worker)],
            'shift': shift, 'date': date,
            'metres_produced': produced, 'metres_damaged': damaged,
            'metres_waste': waste, 'metres_rejected': rejected})
        if confirm:
            entry.action_confirm()
        return entry

    def _roll(self, order, entries, length=135, product=None, confirm=True):
        roll = self.env['textile.fabric.roll'].create({
            'order_id': order.id, 'product_id': (product or self.fabric).id,
            'length_m': length, 'production_ids': [Command.set(entries.ids)]})
        if confirm:
            roll.action_confirm()
        return roll

    def _qty(self, product, location):
        return self.env['stock.quant']._get_available_quantity(product, location)

    # ---- production entries -------------------------------------------
    def test_good_metres_and_confirm(self):
        order = self._order()
        entry = self._entry(order, produced=200, damaged=5, waste=3, rejected=2)
        self.assertEqual(entry.good_metres, 190)
        self.assertEqual(entry.state, 'confirmed')
        self.assertEqual(entry.confirmed_by_id, self.env.user)
        self.assertTrue(entry.name.startswith('PRD/'))

    def test_metres_validation(self):
        order = self._order()
        with self.assertRaises(ValidationError):
            self._entry(order, produced=0, confirm=False)
        with self.assertRaises(ValidationError):
            self._entry(order, produced=100, damaged=-1, confirm=False)
        with self.assertRaises(ValidationError):
            self._entry(order, produced=100, damaged=60, waste=30, rejected=20, confirm=False)

    def test_one_entry_per_loom_per_shift(self):
        order = self._order()
        self._entry(order, confirm=False)
        with self.assertRaises(Exception), mute_logger('odoo.sql_db'):
            self._entry(order, confirm=False)
        self._entry(order, shift='night', confirm=False)             # other shift ok
        self._entry(order, loom=self.loom2, confirm=False)           # other loom ok
        self._entry(order, date='2026-11-02', confirm=False)         # other day ok

    def test_confirmed_entry_is_locked(self):
        order = self._order()
        entry = self._entry(order)
        with self.assertRaises(UserError):
            entry.metres_produced = 500
        with self.assertRaises(UserError):
            entry.unlink()
        with self.assertRaises(UserError):
            entry.action_confirm()
        entry.notes = 'notes may still change'
        entry.action_draft()
        self.assertEqual(entry.state, 'draft')
        entry.metres_produced = 250
        self.assertEqual(entry.good_metres, 250)

    def test_confirm_needs_open_order(self):
        order = self._order()
        entry = self._entry(order, confirm=False)
        order.action_done()
        with self.assertRaises(UserError):
            entry.action_confirm()

    # ---- fabric rolls ---------------------------------------------------
    def test_roll_adds_finished_stock(self):
        order = self._order()
        entry = self._entry(order, produced=300)
        roll = self._roll(order, entry, length=135)
        self.assertEqual(roll.state, 'available')
        self.assertEqual(roll.picking_id.state, 'done')
        self.assertTrue(roll.name.startswith('ROLL/'))
        self.assertEqual(self._qty(self.fabric, self.finished), 135)
        roll2 = self._roll(order, entry, length=138)
        self.assertNotEqual(roll.name, roll2.name)
        self.assertEqual(self._qty(self.fabric, self.finished), 273)

    def test_roll_rules(self):
        order = self._order()
        other = self._order()
        entry = self._entry(order)
        draft_entry = self._entry(order, loom=self.loom2, confirm=False)
        foreign = self._entry(other, loom=self.loom2, shift='night')
        with self.assertRaises(UserError):
            self._roll(order, self.env['textile.production'])          # no production
        with self.assertRaises(UserError):
            self._roll(order, draft_entry)                              # unconfirmed
        with self.assertRaises(UserError):
            self._roll(order, foreign)                                  # other order
        with self.assertRaises(UserError):
            self._roll(order, entry, product=self.bad_fabric)           # wrong unit
        with self.assertRaises(ValidationError):
            self._roll(order, entry, length=0, confirm=False)
        self.assertEqual(self._qty(self.fabric, self.finished), 0)

    def test_roll_length_range_flag(self):
        order = self._order()
        entry = self._entry(order)
        self.assertFalse(self._roll(order, entry, length=135, confirm=False).out_of_range)
        self.assertTrue(self._roll(order, entry, length=150, confirm=False).out_of_range)
        order.write({'roll_length_min': 120, 'roll_length_max': 160})
        self.assertFalse(self._roll(order, entry, length=150, confirm=False).out_of_range)

    def test_roll_cancel_reverses_stock_and_locks(self):
        order = self._order()
        entry = self._entry(order)
        roll = self._roll(order, entry, length=135)
        with self.assertRaises(UserError):
            roll.length_m = 140                     # locked once in stock
        with self.assertRaises(UserError):
            roll.unlink()
        roll.action_cancel()
        self.assertEqual(roll.state, 'cancel')
        self.assertEqual(self._qty(self.fabric, self.finished), 0)
        with self.assertRaises(UserError):
            roll.action_cancel()
        with self.assertRaises(UserError):
            roll.action_confirm()

    def test_cannot_confirm_roll_twice(self):
        order = self._order()
        roll = self._roll(order, self._entry(order))
        with self.assertRaises(UserError):
            roll.action_confirm()
        self.assertEqual(self._qty(self.fabric, self.finished), 135)

    def test_entry_with_active_roll_cannot_go_back_to_draft(self):
        order = self._order()
        entry = self._entry(order)
        roll = self._roll(order, entry)
        with self.assertRaises(UserError):
            entry.action_draft()
        roll.action_cancel()
        entry.action_draft()
        self.assertEqual(entry.state, 'draft')

    # ---- order totals ---------------------------------------------------
    def test_order_production_and_roll_totals(self):
        order = self._order(required_fabric_m=1000)
        e1 = self._entry(order, produced=200, damaged=5, waste=3, rejected=2)   # 190 good
        e2 = self._entry(order, produced=100, shift='night')                    # 100 good
        self._entry(order, produced=999, loom=self.loom2, confirm=False)        # draft: ignored
        self._roll(order, e1 + e2, length=135)
        self._roll(order, e1 + e2, length=135)
        self.assertEqual(order.fabric_produced_m, 290)
        self.assertEqual(order.fabric_damaged_m, 5)
        self.assertEqual(order.fabric_waste_m, 3)
        self.assertEqual(order.fabric_rejected_m, 2)
        self.assertEqual(order.fabric_pending_m, 710)
        self.assertEqual(order.fabric_rolled_m, 270)
        self.assertEqual(order.fabric_unrolled_m, 20)
        self.assertEqual((order.production_count, order.roll_count), (3, 2))
        with self.assertRaises(UserError):
            order.action_cancel()                    # has confirmed production
        # cancelled rolls no longer count
        order.roll_ids[0].action_cancel()
        self.assertEqual(order.fabric_rolled_m, 135)

    # ---- permissions ----------------------------------------------------
    def test_permissions(self):
        def user(login, xmlid):
            return self.env['res.users'].with_context(no_reset_password=True).create({
                'name': login, 'login': login,
                'group_ids': [Command.set([self.env.ref(xmlid).id])]})
        supervisor = user('t4_sup', 'textile_inventory.group_textile_supervisor')
        accountant = user('t4_acc', 'textile_inventory.group_textile_accountant')
        manager = user('t4_inv', 'textile_inventory.group_textile_inventory')
        order = self._order()
        vals = {'order_id': order.id, 'loom_id': self.loom.id,
                'line_ids': [Command.create({'worker_id': self.worker.id})],
                'metres_produced': 120, 'date': '2026-12-01'}
        entry = self.env['textile.production'].with_user(supervisor).create(vals)
        entry.action_confirm()
        self.assertEqual(entry.confirmed_by_id, supervisor)
        with self.assertRaises(UserError):
            entry.action_draft()                      # only administrators
        with self.assertRaises(AccessError):
            self.env['textile.production'].with_user(accountant).create(dict(vals, date='2026-12-02'))
        with self.assertRaises(AccessError):
            self.env['textile.production'].with_user(manager).create(dict(vals, date='2026-12-03'))
        roll = self.env['textile.fabric.roll'].with_user(manager).create({
            'order_id': order.id, 'product_id': self.fabric.id, 'length_m': 135,
            'production_ids': [Command.set(entry.ids)]})
        roll.action_confirm()
        self.assertEqual(roll.state, 'available')
        with self.assertRaises(AccessError):
            roll.with_user(accountant).write({'notes': 'x'})

    # ---- two or more workers share a loom --------------------------------
    def test_two_workers_equal_split(self):
        order = self._order()
        entry = self._entry(order, produced=200, damaged=10,
                            workers=self.worker + self.worker2)
        self.assertEqual(sorted(entry.line_ids.mapped('share_metres')), [95, 95])
        self.assertEqual(entry.worker_ids, self.worker + self.worker2)

    def test_odd_split_adds_up_exactly(self):
        order = self._order()
        entry = self._entry(order, produced=190,
                            workers=self.worker + self.worker2 + self.worker3)
        self.assertAlmostEqual(sum(entry.line_ids.mapped('share_metres')), 190, places=2)

    def test_manual_split_is_kept(self):
        order = self._order()
        entry = self.env['textile.production'].create({
            'order_id': order.id, 'loom_id': self.loom.id, 'date': '2026-11-05',
            'metres_produced': 200,
            'line_ids': [Command.create({'worker_id': self.worker.id, 'share_metres': 120}),
                         Command.create({'worker_id': self.worker2.id, 'share_metres': 80})]})
        entry.action_confirm()
        self.assertEqual(entry.line_ids.filtered(
            lambda l: l.worker_id == self.worker).share_metres, 120)

    def test_split_must_match_good_metres(self):
        order = self._order()
        entry = self.env['textile.production'].create({
            'order_id': order.id, 'loom_id': self.loom.id, 'date': '2026-11-06',
            'metres_produced': 200,
            'line_ids': [Command.create({'worker_id': self.worker.id, 'share_metres': 100}),
                         Command.create({'worker_id': self.worker2.id, 'share_metres': 50})]})
        with self.assertRaises(UserError):
            entry.action_confirm()
        self.assertEqual(entry.state, 'draft')

    def test_entry_needs_a_worker_and_no_duplicates(self):
        order = self._order()
        empty = self.env['textile.production'].create({
            'order_id': order.id, 'loom_id': self.loom.id, 'date': '2026-11-07',
            'metres_produced': 100})
        with self.assertRaises(UserError):
            empty.action_confirm()
        with self.assertRaises(Exception), mute_logger('odoo.sql_db'):
            self.env['textile.production'].create({
                'order_id': order.id, 'loom_id': self.loom.id, 'date': '2026-11-08',
                'metres_produced': 100,
                'line_ids': [Command.create({'worker_id': self.worker.id}),
                             Command.create({'worker_id': self.worker.id})]})

    def test_confirmed_worker_lines_are_locked(self):
        order = self._order()
        entry = self._entry(order, workers=self.worker + self.worker2)
        line = entry.line_ids[0]
        with self.assertRaises(UserError):
            line.share_metres = 1
        with self.assertRaises(UserError):
            line.unlink()
        with self.assertRaises(UserError):
            self.env['textile.production.worker'].create(
                {'production_id': entry.id, 'worker_id': self.worker3.id})
        with self.assertRaises(UserError):
            entry.write({'line_ids': [Command.delete(line.id)]})

    def test_worker_wise_production_summary(self):
        order = self._order()
        self._entry(order, produced=200, workers=self.worker + self.worker2)             # 100 each
        self._entry(order, produced=90, shift='night', workers=self.worker)               # 90
        self._entry(order, produced=500, loom=self.loom2, workers=self.worker2, confirm=False)  # draft
        Line = self.env['textile.production.worker']
        mine = Line.search([('worker_id', '=', self.worker.id), ('production_state', '=', 'confirmed')])
        other = Line.search([('worker_id', '=', self.worker2.id), ('production_state', '=', 'confirmed')])
        self.assertEqual(sum(mine.mapped('share_metres')), 190)
        self.assertEqual(sum(other.mapped('share_metres')), 100)
        self.assertEqual(set(mine.mapped('shift')), {'day', 'night'})
