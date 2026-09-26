# -*- coding: utf-8 -*-
# Part of StockSense Hackathon Module. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from ..services.steward_engine import StewardEngine


class StocksenseAdjustmentRequest(models.Model):
    """
    Guarded Inventory Adjustment model.
    Intercepts suspicious inventory adjustments and enforces Human-in-the-Loop review.
    """
    _name = 'stocksense.adjustment.request'
    _description = 'StockSense Adjustment Request'
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Reference', required=True, copy=False, default=lambda self: _('New'))
    product_id = fields.Many2one('product.product', string='Product', required=True, index=True)
    location_id = fields.Many2one('stock.location', string='Location', required=True, index=True,
                                  domain="[('usage', '=', 'internal')]")
    quantity_change = fields.Float(string='Quantity Change (Δ)', required=True, digits='Product Unit of Measure',
                                   help='Negative for shrinkage/loss, positive for surplus.')
    current_quantity = fields.Float(string='Current Stock', compute='_compute_quantities', store=True)
    new_quantity = fields.Float(string='Resulting Stock', compute='_compute_quantities', store=True)
    reason = fields.Char(string='Reason / Justification')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('pending_approval', 'Pending Manager Review'),
        ('approved', 'Approved & Applied'),
        ('rejected', 'Rejected'),
    ], string='Status', default='draft', required=True, index=True)

    risk_score = fields.Float(string='Risk Score (0-100)', digits=(5, 1), readonly=True)
    severity = fields.Selection([
        ('normal', 'Normal'),
        ('attention', 'Attention'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ], string='Severity', default='normal', readonly=True)
    z_score = fields.Float(string='Deviation (Z-Score)', digits=(6, 2), readonly=True)
    baseline_mean = fields.Float(string='Historical Mean (μ)', digits=(12, 2), readonly=True)
    baseline_std = fields.Float(string='Baseline Std (σ)', digits=(12, 2), readonly=True)
    is_anomalous = fields.Boolean(string='Is Anomalous', readonly=True)
    explanation = fields.Text(string='Steward Explanation', readonly=True)
    evidence = fields.Text(string='Statistical Evidence', readonly=True)
    recommended_action = fields.Text(string='Recommended Action', readonly=True)

    watchlist_id = fields.Many2one('stocksense.watchlist.item', string='Linked Watchlist Alert', ondelete='set null')
    requested_by = fields.Many2one('res.users', string='Requested By', default=lambda self: self.env.user, readonly=True)
    reviewed_by = fields.Many2one('res.users', string='Reviewed By', readonly=True)
    stock_move_id = fields.Many2one('stock.move', string='Applied Stock Move', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('stocksense.adjustment.request') or f"ADJ-{fields.Datetime.now().strftime('%Y%m%d%H%M%S')}"
        return super().create(vals_list)

    @api.depends('product_id', 'location_id', 'quantity_change')
    def _compute_quantities(self):
        for record in self:
            if record.product_id and record.location_id:
                quants = self.env['stock.quant'].search([
                    ('product_id', '=', record.product_id.id),
                    ('location_id', '=', record.location_id.id),
                ])
                current = sum(quants.mapped('quantity'))
            else:
                current = 0.0
            record.current_quantity = current
            record.new_quantity = current + record.quantity_change

    def action_submit(self):
        """
        Submits adjustment request through the Steward Intelligence Gate.
        """
        for record in self:
            eval_res = StewardEngine.evaluate_adjustment(
                self.env, record.product_id, record.location_id, record.quantity_change
            )

            record.write({
                'is_anomalous': eval_res['is_anomalous'],
                'z_score': eval_res['z_score'],
                'risk_score': eval_res['risk_score'],
                'severity': eval_res['severity'],
                'baseline_mean': eval_res['mean'],
                'baseline_std': eval_res['std'],
                'explanation': eval_res['explanation'],
                'evidence': eval_res['evidence'],
                'recommended_action': eval_res['recommended_action'],
            })

            if eval_res['is_anomalous']:
                # Intercept! Route to Pending Manager Review
                watchlist_vals = {
                    'name': f"Suspicious Adjustment: {record.product_id.name} ({record.quantity_change:g} units @ {record.location_id.name})",
                    'rule_type': 'shrinkage_anomaly',
                    'related_model': 'stocksense.adjustment.request',
                    'related_res_id': record.id,
                    'product_id': record.product_id.id,
                    'location_id': record.location_id.id,
                    'score': eval_res['risk_score'],
                    'severity': eval_res['severity'],
                    'actual_value': record.quantity_change,
                    'baseline_mean': eval_res['mean'],
                    'baseline_std': eval_res['std'],
                    'z_score': eval_res['z_score'],
                    'explanation': eval_res['explanation'],
                    'evidence': eval_res['evidence'],
                    'recommended_action': eval_res['recommended_action'],
                    'state': 'new',
                }
                watchlist_item = self.env['stocksense.watchlist.item'].sudo().create(watchlist_vals)
                record.write({
                    'state': 'pending_approval',
                    'watchlist_id': watchlist_item.id,
                })
            else:
                # Normal adjustment: safe to apply
                record._apply_inventory_change()
                record.write({
                    'state': 'approved',
                    'reviewed_by': self.env.user.id,
                })

    def action_approve(self):
        """
        Manager approval: validates the adjustment and updates native inventory.
        """
        # Server-side security enforcement
        if not self.env.user.has_group('stocksense_hackathon.group_stocksense_manager') and not self.env.is_superuser():
            raise UserError(_("Access Denied: Only Inventory Managers can approve suspicious adjustments."))

        for record in self:
            if record.state != 'pending_approval':
                raise UserError(_("Only pending adjustments can be approved."))
            record._apply_inventory_change()
            record.write({
                'state': 'approved',
                'reviewed_by': self.env.user.id,
            })
            if record.watchlist_id:
                record.watchlist_id.action_resolve()

    def action_reject(self):
        """
        Manager rejection: prevents stock change.
        """
        if not self.env.user.has_group('stocksense_hackathon.group_stocksense_manager') and not self.env.is_superuser():
            raise UserError(_("Access Denied: Only Inventory Managers can reject adjustments."))

        for record in self:
            if record.state != 'pending_approval':
                raise UserError(_("Only pending adjustments can be rejected."))
            record.write({
                'state': 'rejected',
                'reviewed_by': self.env.user.id,
            })
            if record.watchlist_id:
                record.watchlist_id.action_dismiss()

    def _apply_inventory_change(self):
        """
        Executes native Odoo 17 stock move for inventory adjustment.
        """
        self.ensure_one()
        inventory_location = self.product_id.with_company(self.env.company).property_stock_inventory
        if not inventory_location:
            inventory_location = self.env['stock.location'].search([
                ('usage', '=', 'inventory'),
                ('company_id', 'in', [self.env.company.id, False]),
            ], limit=1)

        diff = self.quantity_change
        if diff < 0:
            src_loc = self.location_id
            dest_loc = inventory_location
            qty = abs(diff)
        else:
            src_loc = inventory_location
            dest_loc = self.location_id
            qty = diff

        quant = self.env['stock.quant'].search([
            ('product_id', '=', self.product_id.id),
            ('location_id', '=', self.location_id.id),
        ], limit=1)
        if not quant:
            quant = self.env['stock.quant'].sudo().create({
                'product_id': self.product_id.id,
                'location_id': self.location_id.id,
                'quantity': 0.0,
            })

        move_vals = quant._get_inventory_move_values(qty, src_loc, dest_loc)
        move_vals['name'] = f"StockSense Adjustment: {self.name} ({self.reason or 'Inventory Correction'})"
        move = self.env['stock.move'].sudo().with_context(inventory_mode=False).create(move_vals)
        move._action_done()
        self.stock_move_id = move.id
