from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install', 'textile')
class TestTextileFlows(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1
        )
        cls.godown = cls.warehouse.lot_stock_id
        cls.loom_loc = cls.env.ref('textile_inventory.location_loom_allocation')
        kg = cls.env.ref('uom.product_uom_kgm')
        metre = cls.env.ref('uom.product_uom_meter')
        unit = cls.env.ref('uom.product_uom_unit')
        Product = cls.env['product.product']
        cls.yarn = Product.create(
            {'name': 'TEST Yarn', 'is_storable': True, 'uom_id': kg.id})
        cls.pavu = Product.create(
            {'name': 'TEST Pavu', 'is_storable': True, 'uom_id': metre.id})
        cls.wrong_unit = Product.create(
            {'name': 'TEST Yarn in units', 'is_storable': True, 'uom_id': unit.id})
        cls.vendor = cls.env['res.partner'].create({'name': 'TEST Vendor'})
        cls.loom = cls.env['textile.loom'].create(
            {'name': 'Test Loom 1', 'code': 'TL-01'})
        cls.order = cls.env['textile.order'].create({
            'order_ref': 'PO-TEST', 'partner_id': cls.vendor.id,
            'required_fabric_m': 5000, 'expected_yarn_kg': 1000,
            'expected_pavu_m': 10000})
        cls.order.action_confirm()

    # ---- helpers -------------------------------------------------------
    def _qty(self, product, location):
        return self.env['stock.quant']._get_available_quantity(product, location)

    def _yarn_receipt(self, bags=5, size=50.0, product=None):
        return self.env['textile.yarn.bag.line'].create({
            'product_id': (product or self.yarn).id,
            'partner_id': self.vendor.id,
            'order_id': self.order.id,
            'bag_size': size,
            'number_of_bags': bags,
        })

    def _user(self, login, group_xmlid):
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login,
            'group_ids': [Command.set([self.env.ref(group_xmlid).id])],
        })

    # ---- yarn receipts -------------------------------------------------
    def test_yarn_receipt_calculates_and_updates_stock(self):
        receipt = self._yarn_receipt(bags=5, size=50)
        self.assertEqual(receipt.total_weight, 250)
        self.assertTrue(receipt.name.startswith('YRN/'))
        receipt.action_receive()
        self.assertEqual(receipt.state, 'done')
        self.assertEqual(receipt.picking_id.state, 'done')
        self.assertEqual(self._qty(self.yarn, self.godown), 250)

    def test_yarn_receipt_60kg_bags(self):
        receipt = self._yarn_receipt(bags=3, size=60)
        self.assertEqual(receipt.total_weight, 180)
        receipt.action_receive()
        self.assertEqual(self._qty(self.yarn, self.godown), 180)

    def test_duplicate_receive_blocked_stock_unchanged(self):
        receipt = self._yarn_receipt()
        receipt.action_receive()
        with self.assertRaises(UserError):
            receipt.action_receive()
        self.assertEqual(self._qty(self.yarn, self.godown), 250)

    def test_invalid_inputs_rejected(self):
        with self.assertRaises(ValidationError):
            self._yarn_receipt(size=0)
        with self.assertRaises(ValidationError):
            self._yarn_receipt(bags=0)
        wrong = self._yarn_receipt(product=self.wrong_unit)
        with self.assertRaises(UserError):
            wrong.action_receive()
        self.assertEqual(wrong.state, 'draft')

    def test_received_receipt_cannot_be_deleted(self):
        receipt = self._yarn_receipt()
        receipt.action_receive()
        with self.assertRaises(UserError):
            receipt.unlink()

    # ---- pavu receipts -------------------------------------------------
    def _pavu_receipt(self, lines):
        return self.env['textile.pavu.receipt'].create({
            'product_id': self.pavu.id,
            'partner_id': self.vendor.id,
            'order_id': self.order.id,
            'line_ids': [Command.create(
                {'roll_length': length, 'number_of_rolls': n})
                for length, n in lines],
        })

    def test_pavu_mixed_roll_lengths(self):
        receipt = self._pavu_receipt([(1200, 5), (1000, 3)])
        self.assertEqual(receipt.total_rolls, 8)
        self.assertEqual(receipt.total_metres, 9000)
        receipt.action_receive()
        self.assertEqual(receipt.state, 'done')
        self.assertEqual(self._qty(self.pavu, self.godown), 9000)

    def test_pavu_needs_lines_and_is_locked_after_receive(self):
        empty = self._pavu_receipt([])
        with self.assertRaises(UserError):
            empty.action_receive()
        receipt = self._pavu_receipt([(800, 2)])
        receipt.action_receive()
        with self.assertRaises(UserError):
            receipt.line_ids[0].number_of_rolls = 5
        with self.assertRaises(UserError):
            receipt.unlink()

    # ---- allocation ----------------------------------------------------
    def _allocation(self, qty):
        return self.env['textile.yarn.allocation'].create({
            'order_id': self.order.id,
            'product_id': self.yarn.id, 'loom_id': self.loom.id, 'quantity': qty,
        })

    def test_allocation_moves_stock_to_loom(self):
        self._yarn_receipt(bags=2, size=50).action_receive()  # 100 kg
        allocation = self._allocation(40)
        allocation.action_allocate()
        self.assertEqual(allocation.state, 'allocated')
        self.assertEqual(self._qty(self.yarn, self.loom_loc), 40)
        self.assertEqual(self._qty(self.yarn, self.godown), 60)

    def test_allocation_cannot_run_twice(self):
        self._yarn_receipt(bags=2, size=50).action_receive()
        allocation = self._allocation(40)
        allocation.action_allocate()
        with self.assertRaises(UserError):
            allocation.action_allocate()
        self.assertEqual(self._qty(self.yarn, self.loom_loc), 40)
        self.assertEqual(self._qty(self.yarn, self.godown), 60)

    def test_over_allocation_blocked_no_negative_stock(self):
        self._yarn_receipt(bags=2, size=50).action_receive()
        allocation = self._allocation(500)
        with self.assertRaises(UserError):
            allocation.action_allocate()
        self.assertEqual(allocation.state, 'draft')
        self.assertEqual(self._qty(self.yarn, self.godown), 100)
        self.assertEqual(self._qty(self.yarn, self.loom_loc), 0)

    def test_loom_code_unique(self):
        with self.assertRaises(Exception), mute_logger('odoo.sql_db'):
            self.env['textile.loom'].create({'name': 'Dup', 'code': 'TL-01'})

    # ---- permissions ---------------------------------------------------
    def test_accountant_is_read_only(self):
        user = self._user('t_accountant', 'textile_inventory.group_textile_accountant')
        receipt = self._yarn_receipt()
        self.assertEqual(receipt.with_user(user).name, receipt.name)  # can read
        with self.assertRaises(AccessError):
            receipt.with_user(user).write({'notes': 'x'})
        with self.assertRaises(AccessError):
            self.env['textile.yarn.bag.line'].with_user(user).create({
                'product_id': self.yarn.id, 'bag_size': 50, 'number_of_bags': 1})

    def test_inventory_manager_can_receive(self):
        user = self._user('t_inventory', 'textile_inventory.group_textile_inventory')
        receipt = self.env['textile.yarn.bag.line'].with_user(user).create({
            'order_id': self.order.id,
            'product_id': self.yarn.id, 'bag_size': 50, 'number_of_bags': 2})
        receipt.action_receive()
        self.assertEqual(self._qty(self.yarn, self.godown), 100)

    def test_supervisor_can_allocate_but_not_receive_yarn(self):
        self._yarn_receipt(bags=2, size=50).action_receive()
        user = self._user('t_supervisor', 'textile_inventory.group_textile_supervisor')
        with self.assertRaises(AccessError):
            self.env['textile.yarn.bag.line'].with_user(user).create({
                'product_id': self.yarn.id, 'bag_size': 50, 'number_of_bags': 1})
        allocation = self.env['textile.yarn.allocation'].with_user(user).create({
            'order_id': self.order.id,
            'product_id': self.yarn.id, 'loom_id': self.loom.id, 'quantity': 10})
        allocation.action_allocate()
        self.assertEqual(self._qty(self.yarn, self.loom_loc), 10)
