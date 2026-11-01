from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'textile')
class TestPayment(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env['res.partner'].create({'name': 'T6 Vendor'})
        cls.loom = cls.env['textile.loom'].create({'name': 'T6 Loom', 'code': 'T6-01'})
        cls.w1 = cls.env['textile.worker'].create({'name': 'T6 W1'})
        cls.w2 = cls.env['textile.worker'].create({'name': 'T6 W2'})
        cls.order = cls.env['textile.order'].create({
            'order_ref': 'T6-1', 'partner_id': cls.vendor.id, 'required_fabric_m': 9000})
        cls.order.action_confirm()
        cls.env['textile.pay.rate'].search([]).unlink()   # no rates until configured

    def _entry(self, date, workers, produced=200, damaged=0, shift='day', shares=None):
        entry = self.env['textile.production'].create({
            'order_id': self.order.id, 'loom_id': self.loom.id, 'date': date,
            'shift': shift, 'metres_produced': produced, 'metres_damaged': damaged,
            'line_ids': [Command.create({'worker_id': w.id, 'share_metres': (shares or {}).get(w.id, 0)})
                         for w in workers]})
        entry.action_confirm()
        return entry

    def _sheet(self, worker, d1='2026-11-01', d2='2026-11-30'):
        return self.env['textile.worker.payment'].create(
            {'worker_id': worker.id, 'date_from': d1, 'date_to': d2})

    def test_no_rate_blocks_calculation(self):
        self._entry('2026-11-02', self.w1)
        sheet = self._sheet(self.w1)
        with self.assertRaises(UserError):
            sheet.action_compute()

    def test_paid_on_produced_including_damaged(self):
        self._entry('2026-11-03', self.w1 | self.w2, produced=200, damaged=20)
        self.env['textile.pay.rate'].create({'rate_per_metre': 2.5, 'date_from': '2026-01-01'})
        sheet = self._sheet(self.w1)
        sheet.action_compute()
        self.assertEqual(sheet.total_metres, 100)           # half of 200 produced, damaged included
        self.assertEqual(sheet.total_amount, 250)
        self.assertTrue(sheet.name.startswith('PAY/'))

    def test_unequal_shares_follow_ratio(self):
        self._entry('2026-11-04', self.w1 | self.w2, produced=200, damaged=20,
                    shares={self.w1.id: 120, self.w2.id: 60})   # good = 180
        self.env['textile.pay.rate'].create({'rate_per_metre': 1, 'date_from': '2026-01-01'})
        s1, s2 = self._sheet(self.w1), self._sheet(self.w2)
        s1.action_compute()
        s2.action_compute()
        self.assertAlmostEqual(s1.total_metres, 200 * 120 / 180, 2)
        self.assertAlmostEqual(s1.total_metres + s2.total_metres, 200, 2)

    def test_worker_rate_and_history(self):
        Rate = self.env['textile.pay.rate']
        Rate.create({'rate_per_metre': 2, 'date_from': '2026-01-01'})
        Rate.create({'rate_per_metre': 3, 'date_from': '2026-11-10'})
        Rate.create({'rate_per_metre': 5, 'date_from': '2026-01-01', 'worker_id': self.w2.id})
        self.assertEqual(Rate._rate_for(self.w1, '2026-11-09'), 2)
        self.assertEqual(Rate._rate_for(self.w1, '2026-11-10'), 3)
        self.assertEqual(Rate._rate_for(self.w2, '2026-11-20'), 5)   # specific wins
        with self.assertRaises(ValidationError):
            Rate.create({'rate_per_metre': 0, 'date_from': '2026-01-01'})

    def test_rate_change_does_not_touch_approved_sheet(self):
        self._entry('2026-11-05', self.w1, produced=100)
        rate = self.env['textile.pay.rate'].create({'rate_per_metre': 2, 'date_from': '2026-01-01'})
        sheet = self._sheet(self.w1)
        sheet.action_compute()
        sheet.action_approve()
        rate.rate_per_metre = 9
        self.assertEqual(sheet.total_amount, 200)

    def test_no_double_payment_and_workflow(self):
        self._entry('2026-11-06', self.w1, produced=100)
        self.env['textile.pay.rate'].create({'rate_per_metre': 2, 'date_from': '2026-01-01'})
        first = self._sheet(self.w1)
        first.action_compute()
        second = self._sheet(self.w1)
        second.action_compute()
        self.assertEqual(second.total_metres, 0)            # already on first sheet
        with self.assertRaises(UserError):
            second.action_approve()
        first.action_approve()
        first.action_paid()
        with self.assertRaises(UserError):
            first.unlink()
        with self.assertRaises(UserError):
            first.action_cancel()
        with self.assertRaises(UserError):
            first.action_compute()
        # a cancelled sheet frees its shifts
        third = self._sheet(self.w2)
        third.action_cancel()

    def test_period_and_unconfirmed_excluded(self):
        self._entry('2026-10-30', self.w1, produced=100)    # outside period
        draft = self.env['textile.production'].create({
            'order_id': self.order.id, 'loom_id': self.loom.id, 'date': '2026-11-07',
            'shift': 'night', 'metres_produced': 50,
            'line_ids': [Command.create({'worker_id': self.w1.id})]})
        self.env['textile.pay.rate'].create({'rate_per_metre': 2, 'date_from': '2026-01-01'})
        sheet = self._sheet(self.w1)
        sheet.action_compute()
        self.assertEqual(sheet.total_metres, 0)
        self.assertEqual(draft.state, 'draft')
        with self.assertRaises(ValidationError):
            self._sheet(self.w1, '2026-12-01', '2026-11-01')

    def test_report_renders(self):
        self._entry('2026-11-08', self.w1, produced=100)
        self.env['textile.pay.rate'].create({'rate_per_metre': 2, 'date_from': '2026-01-01'})
        sheet = self._sheet(self.w1)
        sheet.action_compute()
        html, _ = self.env['ir.actions.report']._render_qweb_html(
            'textile_inventory.report_worker_payment', sheet.ids)
        self.assertIn(sheet.name.encode(), html)

    def test_permissions(self):
        def user(login, xmlid):
            return self.env['res.users'].with_context(no_reset_password=True).create({
                'name': login, 'login': login,
                'group_ids': [Command.set([self.env.ref(xmlid).id])]})
        acc = user('t6_acc', 'textile_inventory.group_textile_accountant')
        sup = user('t6_sup', 'textile_inventory.group_textile_supervisor')
        inv = user('t6_inv', 'textile_inventory.group_textile_inventory')
        self.env['textile.pay.rate'].with_user(acc).create({'rate_per_metre': 2, 'date_from': '2026-01-01'})
        self.env['textile.worker.payment'].with_user(acc).create(
            {'worker_id': self.w1.id, 'date_from': '2026-11-01', 'date_to': '2026-11-30'})
        for u in (sup, inv):
            with self.assertRaises(AccessError):
                self.env['textile.pay.rate'].with_user(u).search([])
            with self.assertRaises(AccessError):
                self.env['textile.worker.payment'].with_user(u).search([])
