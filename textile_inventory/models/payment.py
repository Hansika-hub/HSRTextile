from collections import defaultdict

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError


class TextilePayRate(models.Model):
    """Pay per metre. NO rates are pre-loaded: the owner must confirm them.
    A worker-specific rate wins over the general (all workers) rate; within
    each, the newest 'valid from' on or before the production date is used."""

    _name = 'textile.pay.rate'
    _description = 'Worker Pay Rate (per metre)'
    _order = 'date_from desc, id desc'

    date_from = fields.Date(string='Valid From', required=True,
                            default=fields.Date.context_today)
    worker_id = fields.Many2one(
        'textile.worker', string='Worker',
        help='Leave empty for the general rate that applies to every worker.')
    rate_per_metre = fields.Float(string='Rate per Metre', digits=(12, 3), required=True)
    active = fields.Boolean(default=True)
    notes = fields.Char(string='Notes')

    @api.constrains('rate_per_metre')
    def _check_rate(self):
        for rate in self:
            if rate.rate_per_metre <= 0:
                raise ValidationError('The rate must be greater than zero.')

    @api.model
    def _rate_for(self, worker, date):
        domain = [('date_from', '<=', date)]
        rate = self.search(domain + [('worker_id', '=', worker.id)],
                           order='date_from desc, id desc', limit=1)
        if not rate:
            rate = self.search(domain + [('worker_id', '=', False)],
                               order='date_from desc, id desc', limit=1)
        return rate.rate_per_metre if rate else 0.0


class TextileWorkerPayment(models.Model):
    """Pay sheet of one worker for a period. 'Compute' collects every
    confirmed shift line of the worker in the period that is not already on
    another pay sheet, and freezes the rate used. Damaged, waste and rejected
    metres are PAID (owner's decision): pay is on metres produced."""

    _name = 'textile.worker.payment'
    _description = 'Worker Pay Sheet'
    _inherit = ['mail.thread']
    _order = 'date_to desc, id desc'

    name = fields.Char(string='Pay Sheet', default='New', readonly=True, copy=False)
    worker_id = fields.Many2one('textile.worker', string='Worker', required=True, tracking=True)
    date_from = fields.Date(string='From', required=True, tracking=True)
    date_to = fields.Date(string='To', required=True, tracking=True)
    line_ids = fields.One2many('textile.worker.payment.line', 'payment_id', string='Shifts')
    total_metres = fields.Float(string='Total Metres', compute='_compute_total', store=True)
    total_amount = fields.Float(string='Total Amount', compute='_compute_total', store=True)
    state = fields.Selection(
        [('draft', 'Draft'), ('approved', 'Approved'), ('paid', 'Paid'), ('cancel', 'Cancelled')],
        string='Status', default='draft', readonly=True, copy=False, tracking=True)
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False)
    notes = fields.Text(string='Notes')

    @api.depends('line_ids.metres', 'line_ids.amount')
    def _compute_total(self):
        for pay in self:
            pay.total_metres = sum(pay.line_ids.mapped('metres'))
            pay.total_amount = sum(pay.line_ids.mapped('amount'))

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for pay in self:
            if pay.date_to < pay.date_from:
                raise ValidationError('"To" date cannot be before "From" date.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('textile.worker.payment') or 'New'
        return super().create(vals_list)

    def unlink(self):
        if any(p.state in ('approved', 'paid') for p in self):
            raise UserError('Approved or paid pay sheets cannot be deleted. Cancel them first.')
        return super().unlink()

    def action_compute(self):
        Line = self.env['textile.production.worker']
        for pay in self:
            if pay.state != 'draft':
                raise UserError('Only a draft pay sheet can be recalculated.')
            pay.line_ids.unlink()
            taken = self.env['textile.worker.payment.line'].search([
                ('payment_id.state', '!=', 'cancel'), ('payment_id', '!=', pay.id)
            ]).production_worker_id
            rows = Line.search([
                ('worker_id', '=', pay.worker_id.id),
                ('production_state', '=', 'confirmed'),
                ('date', '>=', pay.date_from), ('date', '<=', pay.date_to),
                ('id', 'not in', taken.ids)], order='date, id')
            missing = []
            vals = []
            for row in rows:
                rate = self.env['textile.pay.rate']._rate_for(pay.worker_id, row.date)
                if not rate:
                    missing.append(str(row.date))
                    continue
                vals.append(Command.create({
                    'production_worker_id': row.id, 'rate': rate}))
            if missing:
                raise UserError(
                    'No pay rate is set for %s on: %s. Add the rate under '
                    'Worker Pay > Pay Rates first.'
                    % (pay.worker_id.name, ', '.join(sorted(set(missing)))))
            pay.line_ids = vals
        return True

    def action_approve(self):
        for pay in self:
            if pay.state != 'draft':
                raise UserError('Only a draft pay sheet can be approved.')
            if not pay.line_ids:
                raise UserError('There are no shifts on this pay sheet. Press Calculate first.')
            pay.write({'state': 'approved', 'approved_by_id': self.env.user.id})
        return True

    def action_paid(self):
        for pay in self:
            if pay.state != 'approved':
                raise UserError('Approve the pay sheet before marking it paid.')
            pay.state = 'paid'
        return True

    def action_cancel(self):
        for pay in self:
            if pay.state == 'paid':
                raise UserError('A paid pay sheet cannot be cancelled.')
            pay.state = 'cancel'
        return True

    def action_draft(self):
        for pay in self:
            if pay.state not in ('approved', 'cancel'):
                raise UserError('Only an approved or cancelled pay sheet can go back to draft.')
            pay.write({'state': 'draft', 'approved_by_id': False})
        return True


class TextileWorkerPaymentLine(models.Model):
    _name = 'textile.worker.payment.line'
    _description = 'Worker Pay Sheet Line'
    _order = 'date, id'

    payment_id = fields.Many2one('textile.worker.payment', required=True, ondelete='cascade')
    production_worker_id = fields.Many2one(
        'textile.production.worker', string='Shift Entry', required=True, ondelete='restrict')
    worker_id = fields.Many2one(related='payment_id.worker_id', store=True)
    pay_state = fields.Selection(related='payment_id.state', store=True)
    date = fields.Date(related='production_worker_id.date', store=True)
    shift = fields.Selection(related='production_worker_id.shift', store=True)
    loom_id = fields.Many2one(related='production_worker_id.loom_id', store=True)
    order_id = fields.Many2one(related='production_worker_id.order_id', store=True)
    metres = fields.Float(related='production_worker_id.payable_metres', store=True,
                          string='Payable Metres')
    rate = fields.Float(string='Rate per Metre', digits=(12, 3), readonly=True)
    amount = fields.Float(string='Amount', compute='_compute_amount', store=True)

    @api.depends('metres', 'rate')
    def _compute_amount(self):
        for line in self:
            line.amount = round(line.metres * line.rate, 2)

    @api.constrains('production_worker_id')
    def _check_unique(self):
        for line in self:
            other = self.search([
                ('production_worker_id', '=', line.production_worker_id.id),
                ('payment_id.state', '!=', 'cancel'), ('id', '!=', line.id)], limit=1)
            if other and line.payment_id.state != 'cancel':
                raise ValidationError(
                    'This shift is already on pay sheet %s.' % other.payment_id.name)
