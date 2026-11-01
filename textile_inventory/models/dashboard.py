from datetime import date

from odoo import api, fields, models


class TextileDashboard(models.TransientModel):
    """Management dashboard: every figure is calculated live from the
    confirmed business records and the Odoo stock quantities."""

    _name = 'textile.dashboard'
    _description = 'Management Dashboard'

    name = fields.Char(default='Management Dashboard')
    # stock
    yarn_stock_kg = fields.Float(string='Yarn in Godown (kg)', compute='_compute')
    yarn_on_looms_kg = fields.Float(string='Yarn Issued to Looms (kg)', compute='_compute')
    pavu_stock_m = fields.Float(string='Pavu in Godown (m)', compute='_compute')
    fabric_stock_m = fields.Float(string='Finished Fabric in Stock (m)', compute='_compute')
    fabric_stock_rolls = fields.Integer(string='Finished Rolls in Stock', compute='_compute')
    # looms
    loom_total = fields.Integer(string='Active Looms', compute='_compute')
    loom_breakdown = fields.Integer(string='Looms in Breakdown', compute='_compute')
    loom_worked_today = fields.Integer(string='Looms That Wove Today', compute='_compute')
    loom_utilisation = fields.Float(string='Loom Utilisation Today (%)', compute='_compute')
    # production
    prod_today_m = fields.Float(string='Produced Today (m)', compute='_compute')
    prod_today_good_m = fields.Float(string='Good Today (m)', compute='_compute')
    prod_month_m = fields.Float(string='Produced This Month (m)', compute='_compute')
    prod_month_good_m = fields.Float(string='Good This Month (m)', compute='_compute')
    prod_month_loss_m = fields.Float(string='Damaged + Waste + Rejected This Month (m)', compute='_compute')
    # orders
    order_open = fields.Integer(string='Pending Orders', compute='_compute')
    order_fabric_pending_m = fields.Float(string='Fabric Still To Weave (m)', compute='_compute')
    # dispatch
    dispatch_month_count = fields.Integer(string='Dispatches This Month', compute='_compute')
    dispatch_month_m = fields.Float(string='Dispatched This Month (m)', compute='_compute')
    dispatch_awaiting = fields.Integer(string='Loads Awaiting Mill Check', compute='_compute')
    dispatch_awaiting_m = fields.Float(string='Metres Awaiting Mill Check', compute='_compute')
    recon_discrepancies = fields.Integer(string='Loads With Difference', compute='_compute')
    recon_missing_m = fields.Float(string='Missing at Mill (m)', compute='_compute')
    recon_rejected_m = fields.Float(string='Rejected by Mill (m)', compute='_compute')
    # worker pay (shown to accountant / administrator only)
    pay_to_pay = fields.Float(string='Approved, Not Yet Paid', compute='_compute')
    pay_paid_month = fields.Float(string='Paid This Month', compute='_compute')
    pay_draft = fields.Float(string='In Draft Pay Sheets', compute='_compute')

    def _compute(self):
        env = self.env
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1)
        warehouse = env['stock.warehouse'].sudo().search(
            [('company_id', '=', env.company.id)], limit=1)
        godown = warehouse.lot_stock_id
        looms_loc = env.ref('textile_inventory.location_loom_allocation')
        finished = env.ref('textile_inventory.location_finished_fabric')
        kg = env.ref('uom.product_uom_kgm')
        metre = env.ref('uom.product_uom_meter')
        Quant = env['stock.quant'].sudo()

        def stock(location, uom):
            quants = Quant.search([('location_id', 'child_of', location.id),
                                   ('product_id.uom_id', '=', uom.id)])
            return sum(quants.mapped('quantity'))

        Prod = env['textile.production'].sudo()
        confirmed = [('state', '=', 'confirmed')]
        today_prod = Prod.search(confirmed + [('date', '=', today)])
        month_prod = Prod.search(confirmed + [('date', '>=', month_start), ('date', '<=', today)])
        looms = env['textile.loom'].sudo().search([('active', '=', True)])
        Disp = env['textile.dispatch'].sudo()
        sent = Disp.search([('state', '=', 'dispatched')])
        month_sent = sent.filtered(lambda d: month_start <= d.date <= today)
        awaiting = sent.filtered(lambda d: d.reconciliation_state == 'pending')
        diff = sent.filtered(lambda d: d.reconciliation_state == 'discrepancy')
        Pay = env['textile.worker.payment'].sudo()
        open_orders = env['textile.order'].sudo().search([('state', '=', 'open')])

        for dash in self:
            dash.yarn_stock_kg = stock(godown, kg)
            dash.yarn_on_looms_kg = stock(looms_loc, kg)
            dash.pavu_stock_m = stock(godown, metre)
            dash.fabric_stock_m = stock(finished, metre)
            dash.fabric_stock_rolls = env['textile.fabric.roll'].sudo().search_count(
                [('state', '=', 'available')])
            dash.loom_total = len(looms)
            dash.loom_breakdown = len(looms.filtered(lambda l: l.status == 'breakdown'))
            worked = today_prod.loom_id & looms
            dash.loom_worked_today = len(worked)
            dash.loom_utilisation = (len(worked) * 100.0 / len(looms)) if looms else 0.0
            dash.prod_today_m = sum(today_prod.mapped('metres_produced'))
            dash.prod_today_good_m = sum(today_prod.mapped('good_metres'))
            dash.prod_month_m = sum(month_prod.mapped('metres_produced'))
            dash.prod_month_good_m = sum(month_prod.mapped('good_metres'))
            dash.prod_month_loss_m = dash.prod_month_m - dash.prod_month_good_m
            dash.order_open = len(open_orders)
            dash.order_fabric_pending_m = sum(open_orders.mapped('fabric_pending_m'))
            dash.dispatch_month_count = len(month_sent)
            dash.dispatch_month_m = sum(month_sent.mapped('total_metres'))
            dash.dispatch_awaiting = len(awaiting)
            dash.dispatch_awaiting_m = sum(awaiting.mapped('total_metres'))
            dash.recon_discrepancies = len(diff)
            dash.recon_missing_m = sum(diff.mapped('mill_missing_m'))
            dash.recon_rejected_m = sum(diff.mapped('mill_rejected_m'))
            if env.user.has_group('textile_inventory.group_textile_accountant') or \
                    env.user.has_group('textile_inventory.group_textile_admin'):
                dash.pay_to_pay = sum(Pay.search([('state', '=', 'approved')]).mapped('total_amount'))
                dash.pay_paid_month = sum(Pay.search([
                    ('state', '=', 'paid'), ('date_to', '>=', month_start)]).mapped('total_amount'))
                dash.pay_draft = sum(Pay.search([('state', '=', 'draft')]).mapped('total_amount'))
            else:
                dash.pay_to_pay = dash.pay_paid_month = dash.pay_draft = 0.0

    @api.model
    def action_open(self):
        rec = self.create({})
        return {
            'type': 'ir.actions.act_window', 'name': 'Dashboard',
            'res_model': self._name, 'res_id': rec.id, 'view_mode': 'form',
            'target': 'current', 'context': {'form_view_initial_mode': 'readonly'},
        }

    def _go(self, name, model, domain):
        return {'type': 'ir.actions.act_window', 'name': name, 'res_model': model,
                'view_mode': 'list,form', 'domain': domain}

    def action_orders(self):
        return self._go('Pending Orders', 'textile.order', [('state', '=', 'open')])

    def action_awaiting(self):
        return self._go('Awaiting Mill Check', 'textile.dispatch',
                        [('reconciliation_state', '=', 'pending')])

    def action_differences(self):
        return self._go('Loads With Difference', 'textile.dispatch',
                        [('reconciliation_state', '=', 'discrepancy')])

    def action_rolls(self):
        return self._go('Finished Rolls in Stock', 'textile.fabric.roll',
                        [('state', '=', 'available')])

    def action_looms(self):
        return self._go('Looms', 'textile.loom', [])

    def action_pay_due(self):
        return self._go('Pay Sheets To Pay', 'textile.worker.payment',
                        [('state', '=', 'approved')])
