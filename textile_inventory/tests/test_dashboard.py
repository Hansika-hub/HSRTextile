from odoo import Command, fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'textile')
class TestDashboard(TransactionCase):

    def test_dashboard_matches_records(self):
        vendor = self.env['res.partner'].create({'name': 'T7 Vendor'})
        loom = self.env['textile.loom'].create({'name': 'T7 Loom', 'code': 'T7-01'})
        worker = self.env['textile.worker'].create({'name': 'T7 W'})
        order = self.env['textile.order'].create({
            'order_ref': 'T7-1', 'partner_id': vendor.id, 'required_fabric_m': 1000})
        order.action_confirm()
        Dash = self.env['textile.dashboard']
        base = Dash.create({})
        base.read(['prod_today_m', 'prod_today_good_m', 'loom_worked_today', 'order_open', 'order_fabric_pending_m'])
        entry = self.env['textile.production'].create({
            'order_id': order.id, 'loom_id': loom.id, 'shift': 'day',
            'date': fields.Date.context_today(Dash),
            'metres_produced': 100, 'metres_damaged': 10,
            'line_ids': [Command.create({'worker_id': worker.id})]})
        entry.action_confirm()
        now = Dash.create({})
        self.assertEqual(now.prod_today_m - base.prod_today_m, 100)
        self.assertEqual(now.prod_today_good_m - base.prod_today_good_m, 90)
        self.assertEqual(now.loom_worked_today - base.loom_worked_today, 1)
        self.assertGreaterEqual(now.order_open, 1)
        self.assertEqual(now.order_fabric_pending_m - base.order_fabric_pending_m, -90)   # 90 good metres woven
        self.assertEqual(Dash.action_open()['res_model'], 'textile.dashboard')

    def test_dashboard_for_each_role(self):
        for xmlid in ('supervisor', 'inventory', 'accountant', 'admin'):
            user = self.env['res.users'].with_context(no_reset_password=True).create({
                'name': 't7_' + xmlid, 'login': 't7_' + xmlid,
                'group_ids': [Command.set([self.env.ref('textile_inventory.group_textile_' + xmlid).id])]})
            dash = self.env['textile.dashboard'].with_user(user).create({})
            dash.read(['yarn_stock_kg', 'pay_to_pay', 'dispatch_awaiting'])
            if xmlid in ('supervisor', 'inventory'):
                self.assertEqual(dash.pay_to_pay, 0)
