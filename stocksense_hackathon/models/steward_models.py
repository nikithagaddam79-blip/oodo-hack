# -*- coding: utf-8 -*-
# Part of StockSense Hackathon Module. See LICENSE file for full copyright and licensing details.

from datetime import datetime
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from ..services.steward_engine import StewardEngine


class StocksenseBaselineStat(models.Model):
    """
    Stores precomputed and historical baseline metrics for statistical anomaly detection.
    """
    _name = 'stocksense.baseline.stat'
    _description = 'StockSense Baseline Statistic'
    _order = 'last_computed desc, id desc'

    product_id = fields.Many2one('product.product', string='Product', ondelete='cascade', index=True)
    location_id = fields.Many2one('stock.location', string='Location', ondelete='cascade', index=True)
    metric_type = fields.Selection([
        ('adjustment_magnitude', 'Adjustment Magnitude'),
        ('processing_time', 'Processing Time (Hours)'),
        ('stock_variance', 'Stock Variance'),
    ], string='Metric Type', required=True, default='adjustment_magnitude')
    mean_value = fields.Float(string='Historical Mean (μ)', digits=(12, 4), required=True, default=0.0)
    std_value = fields.Float(string='Standard Deviation (σ)', digits=(12, 4), required=True, default=1.0)
    sample_count = fields.Integer(string='Sample Count (N)', required=True, default=0)
    last_computed = fields.Datetime(string='Last Computed', default=fields.Datetime.now)
    active = fields.Boolean(string='Active', default=True)

    @api.depends('product_id', 'location_id', 'metric_type')
    def _compute_display_name(self):
        for record in self:
            prod = record.product_id.name or 'All Products'
            loc = record.location_id.name or 'All Locations'
            record.display_name = f"[{record.metric_type}] {prod} @ {loc}"


class StocksenseRuleConfig(models.Model):
    """
    Configurable detection parameters and sensitivity thresholds per rule type.
    Warehouse managers can adapt thresholds without hardcoded parameters.
    """
    _name = 'stocksense.rule.config'
    _description = 'StockSense Rule Configuration'

    name = fields.Char(string='Rule Name', required=True)
    rule_type = fields.Selection([
        ('shrinkage_anomaly', 'Shrinkage Anomaly'),
        ('delay_risk', 'Operation Delay Risk'),
        ('stock_variance', 'Stock Variance'),
    ], string='Rule Type', required=True)
    sensitivity_threshold = fields.Float(string='Sensitivity Threshold (σ)', default=3.0, required=True,
                                         help='Z-score cutoff above which an event is classified as anomalous.')
    min_sample_size = fields.Integer(string='Minimum Sample Size', default=10, required=True,
                                     help='Minimum historical observations required to establish a valid baseline.')
    dismiss_streak = fields.Integer(string='Dismiss Streak', default=0, readonly=True,
                                    help='Consecutive false positive dismissals used for threshold adaptation.')
    active = fields.Boolean(string='Active', default=True)


class StocksenseWatchlistItem(models.Model):
    """
    Explainable anomaly alert item on the StockSense Watchlist.
    Inherits mail.thread and mail.activity.mixin for native Odoo collaboration and tasks.
    """
    _name = 'stocksense.watchlist.item'
    _description = 'StockSense Watchlist Item'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'score desc, create_date desc'

    name = fields.Char(string='Alert Title', required=True, tracking=True)
    rule_type = fields.Selection([
        ('shrinkage_anomaly', 'Shrinkage Anomaly'),
        ('delay_risk', 'Operation Delay Risk'),
        ('stock_variance', 'Stock Variance'),
    ], string='Rule Type', required=True, index=True, tracking=True)
    related_model = fields.Char(string='Related Model', index=True)
    related_res_id = fields.Integer(string='Related Record ID', index=True)
    product_id = fields.Many2one('product.product', string='Product', index=True, tracking=True)
    location_id = fields.Many2one('stock.location', string='Location', index=True, tracking=True)
    score = fields.Float(string='Risk Score (0-100)', digits=(5, 1), required=True, default=0.0, tracking=True)
    severity = fields.Selection([
        ('normal', 'Normal'),
        ('attention', 'Attention'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ], string='Severity', default='normal', required=True, index=True, tracking=True)
    actual_value = fields.Float(string='Actual Observed Value', digits=(12, 2))
    baseline_mean = fields.Float(string='Baseline Mean (μ)', digits=(12, 2))
    baseline_std = fields.Float(string='Baseline Std (σ)', digits=(12, 2))
    z_score = fields.Float(string='Deviation (Z-Score)', digits=(6, 2), tracking=True)
    explanation = fields.Text(string='What Happened & Why Unusual', tracking=True)
    evidence = fields.Text(string='Statistical Evidence', tracking=True)
    recommended_action = fields.Text(string='Recommended Action', tracking=True)
    state = fields.Selection([
        ('new', 'New'),
        ('acknowledged', 'Acknowledged'),
        ('dismissed', 'Dismissed'),
        ('escalated', 'Escalated'),
        ('resolved', 'Resolved'),
    ], string='Status', default='new', required=True, index=True, tracking=True)
    feedback = fields.Selection([
        ('none', 'No Feedback'),
        ('true_positive', 'True Positive (Confirmed)'),
        ('false_positive', 'False Positive'),
        ('unclear', 'Unclear / Inconclusive'),
    ], string='Manager Feedback', default='none', tracking=True)
    assigned_user_id = fields.Many2one('res.users', string='Assigned Manager', default=lambda self: self.env.user)
    acknowledged_date = fields.Datetime(string='Acknowledged Date', readonly=True)
    resolved_date = fields.Datetime(string='Resolved Date', readonly=True)

    def action_acknowledge(self):
        self.write({
            'state': 'acknowledged',
            'acknowledged_date': fields.Datetime.now(),
        })

    def action_dismiss(self):
        self.write({
            'state': 'dismissed',
            'resolved_date': fields.Datetime.now(),
        })

    def action_escalate(self):
        self.write({'state': 'escalated'})

    def action_resolve(self):
        self.write({
            'state': 'resolved',
            'resolved_date': fields.Datetime.now(),
        })

    def action_feedback_true_positive(self):
        for record in self:
            record.write({'feedback': 'true_positive'})
            StewardEngine.process_feedback(self.env, record, 'true_positive')

    def action_feedback_false_positive(self):
        for record in self:
            record.write({
                'feedback': 'false_positive',
                'state': 'dismissed',
                'resolved_date': fields.Datetime.now(),
            })
            StewardEngine.process_feedback(self.env, record, 'false_positive')

    def action_feedback_unclear(self):
        for record in self:
            record.write({'feedback': 'unclear'})
            StewardEngine.process_feedback(self.env, record, 'unclear')

    def action_create_recount_activity(self):
        """
        Creates a native Odoo activity (mail.activity) for warehouse recount.
        """
        self.ensure_one()
        summary = f"Physical Recount: {self.product_id.name or 'Stock'} @ {self.location_id.name or 'Location'}"
        note = (
            f"<p><strong>StockSense Alert:</strong> {self.name}</p>"
            f"<p><strong>Evidence:</strong> Deviation of {self.z_score}σ (Risk: {self.score}/100)</p>"
            f"<p><strong>Action:</strong> {self.recommended_action}</p>"
        )
        self.activity_schedule(
            act_type_xmlid='mail.mail_activity_data_todo',
            summary=summary,
            note=note,
            user_id=self.assigned_user_id.id or self.env.user.id,
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Recount Activity Scheduled'),
                'message': _('A native Odoo activity has been assigned to the manager.'),
                'sticky': False,
                'type': 'success',
            }
        }

    @api.model
    def run_steward_cron(self):
        """
        Entrypoint for the scheduled ir.cron job.
        """
        return StewardEngine.run_full_steward(self.env)
