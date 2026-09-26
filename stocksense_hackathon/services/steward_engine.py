# -*- coding: utf-8 -*-
# Part of StockSense Hackathon Module. See LICENSE file for full copyright and licensing details.

import math
import logging
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)


class StewardEngine:
    """
    Centralized Deterministic Statistical Intelligence Engine for StockSense.
    
    Adheres strictly to the One-Brain Architecture:
    Both VoiceOps, Security Gate, and Dashboard call this engine.
    No black-box AI, no random numbers, 100% reproducible statistical calculations.
    """

    @staticmethod
    def calculate_z_score(actual_value, mean, std):
        """
        Calculates standard deviation deviation (z-score).
        Formula: z = abs(actual - mean) / std
        Handles std == 0 safely without division by zero.
        """
        if std is None or std <= 0.0:
            if actual_value != mean:
                return 10.0  # Significant difference with zero variance
            return 0.0
        return abs(actual_value - mean) / std

    @staticmethod
    def calculate_risk_score(z_score, sample_count=100, min_samples=10):
        """
        Deterministic Risk Score (0-100 scale).
        
        Severity Bands:
          0-29    Normal
          30-59   Attention
          60-79   High
          80-100  Critical
          
        Mathematical formulation:
        - If sample count < min_samples: score capped at 25 (Normal / Insufficient baseline)
        - For z <= 1.0: score = min(29.0, z * 29.0)
        - For 1.0 < z < 3.0: score = 30.0 + ((z - 1.0) / 2.0) * 29.0  (Maps to 30-59)
        - For 3.0 <= z < 6.0: score = 60.0 + ((z - 3.0) / 3.0) * 19.0 (Maps to 60-79)
        - For z >= 6.0: score = min(100.0, 80.0 + ((z - 6.0) / 6.0) * 20.0) (Maps to 80-100)
        """
        if sample_count < min_samples:
            return 15.0, 'normal'

        z = max(0.0, float(z_score))
        if z <= 1.0:
            score = round(z * 29.0, 1)
            severity = 'normal'
        elif z < 3.0:
            score = round(30.0 + ((z - 1.0) / 2.0) * 29.0, 1)
            severity = 'attention'
        elif z < 6.0:
            score = round(60.0 + ((z - 3.0) / 3.0) * 19.0, 1)
            severity = 'high'
        else:
            score = round(min(100.0, 80.0 + ((z - 6.0) / 6.0) * 20.0), 1)
            severity = 'critical'

        return score, severity

    @classmethod
    def evaluate_adjustment(cls, env, product, location, quantity_change):
        """
        Evaluates a requested inventory adjustment against historical baseline.
        
        Returns a dictionary containing:
        - is_anomalous: bool
        - z_score: float
        - risk_score: float
        - severity: str
        - mean: float
        - std: float
        - sample_count: int
        - explanation: str
        - evidence: str
        - recommended_action: str
        """
        # 1. Fetch rule configuration
        rule_config = env['stocksense.rule.config'].search([
            ('rule_type', '=', 'shrinkage_anomaly'),
            ('active', '=', True),
        ], limit=1)
        sensitivity_threshold = rule_config.sensitivity_threshold if rule_config else 3.0
        min_sample_size = rule_config.min_sample_size if rule_config else 10

        # 2. Fetch baseline statistic
        baseline = env['stocksense.baseline.stat'].search([
            ('product_id', '=', product.id),
            ('location_id', '=', location.id),
            ('metric_type', '=', 'adjustment_magnitude'),
            ('active', '=', True),
        ], limit=1)

        # Fallback to product-wide baseline if location-specific does not exist
        if not baseline:
            baseline = env['stocksense.baseline.stat'].search([
                ('product_id', '=', product.id),
                ('metric_type', '=', 'adjustment_magnitude'),
                ('active', '=', True),
            ], limit=1)

        if not baseline or baseline.sample_count < min_sample_size:
            # Insufficient historical data
            return {
                'is_anomalous': False,
                'z_score': 0.0,
                'risk_score': 15.0,
                'severity': 'normal',
                'mean': baseline.mean_value if baseline else 0.0,
                'std': baseline.std_value if baseline else 1.0,
                'sample_count': baseline.sample_count if baseline else 0,
                'explanation': f"Insufficient historical data to establish a reliable baseline for {product.display_name} at {location.display_name}.",
                'evidence': f"Observed samples: {baseline.sample_count if baseline else 0} (Minimum required: {min_sample_size})",
                'recommended_action': "Standard verification advised.",
            }

        mean = baseline.mean_value
        std = baseline.std_value
        sample_count = baseline.sample_count

        z_score = round(cls.calculate_z_score(quantity_change, mean, std), 2)
        risk_score, severity = cls.calculate_risk_score(z_score, sample_count, min_sample_size)
        is_anomalous = (z_score >= sensitivity_threshold)

        # Build Explainability Breakdown
        direction = "negative adjustment (shrinkage)" if quantity_change < 0 else "positive adjustment"
        explanation = (
            f"Requested {direction} of {quantity_change:g} units for {product.display_name} at {location.display_name} "
            f"deviates significantly from historical norms (baseline average {mean:g} ± {std:g} units)."
        )

        evidence = (
            f"Statistical Evidence:\n"
            f"• Requested Value: {quantity_change:g} units\n"
            f"• Historical Mean (μ): {mean:g} units\n"
            f"• Standard Deviation (σ): {std:g} units\n"
            f"• Historical Sample Size: {sample_count} adjustments\n"
            f"• Statistical Deviation: {z_score}σ (Threshold: {sensitivity_threshold}σ)\n"
            f"• Deterministic Risk Score: {risk_score}/100 ({severity.upper()})"
        )

        if z_score >= 6.0:
            recommended_action = "MANDATORY: Perform physical recount and verify security footage before approval."
        elif z_score >= 3.0:
            recommended_action = "Perform physical recount of location before manager sign-off."
        else:
            recommended_action = "Standard manager approval."

        return {
            'is_anomalous': is_anomalous,
            'z_score': z_score,
            'risk_score': risk_score,
            'severity': severity,
            'mean': mean,
            'std': std,
            'sample_count': sample_count,
            'explanation': explanation,
            'evidence': evidence,
            'recommended_action': recommended_action,
        }

    @classmethod
    def evaluate_delays(cls, env):
        """
        Scans pending stock pickings (receipts, deliveries, transfers)
        and compares elapsed processing time against historical baseline.
        """
        rule_config = env['stocksense.rule.config'].search([
            ('rule_type', '=', 'delay_risk'),
            ('active', '=', True),
        ], limit=1)
        sensitivity_threshold = rule_config.sensitivity_threshold if rule_config else 2.5
        min_sample_size = rule_config.min_sample_size if rule_config else 5

        # Fetch baseline for processing time
        baseline = env['stocksense.baseline.stat'].search([
            ('metric_type', '=', 'processing_time'),
            ('active', '=', True),
        ], limit=1)
        mean_hours = baseline.mean_value if baseline else 4.0
        std_hours = baseline.std_value if baseline else 1.5
        sample_count = baseline.sample_count if baseline else 50

        # Inspect pending pickings
        open_pickings = env['stock.picking'].search([
            ('state', 'in', ['confirmed', 'assigned']),
        ])

        now = datetime.now()
        flagged_count = 0

        for picking in open_pickings:
            ref_time = picking.scheduled_date or picking.create_date
            if not ref_time:
                continue
            elapsed_hours = (now - ref_time).total_seconds() / 3600.0

            if elapsed_hours <= mean_hours:
                continue

            z_score = round(cls.calculate_z_score(elapsed_hours, mean_hours, std_hours), 2)
            if z_score >= sensitivity_threshold:
                risk_score, severity = cls.calculate_risk_score(z_score, sample_count, min_sample_size)
                
                # Check for existing open watchlist item (deduplication)
                existing_item = env['stocksense.watchlist.item'].search([
                    ('related_model', '=', 'stock.picking'),
                    ('related_res_id', '=', picking.id),
                    ('rule_type', '=', 'delay_risk'),
                    ('state', 'in', ['new', 'acknowledged', 'escalated']),
                ], limit=1)

                op_type = picking.picking_type_id.name or "Operation"
                explanation = (
                    f"{op_type} '{picking.name}' has been pending for {elapsed_hours:.1f} hours, "
                    f"substantially exceeding normal turnaround (mean: {mean_hours:.1f}h ± {std_hours:.1f}h)."
                )
                evidence = (
                    f"Operational Delay Evidence:\n"
                    f"• Operation: {picking.name} ({op_type})\n"
                    f"• Elapsed Time: {elapsed_hours:.1f} hours\n"
                    f"• Historical Average: {mean_hours:.1f} hours\n"
                    f"• Standard Deviation: {std_hours:.1f} hours\n"
                    f"• Delay Deviation: {z_score}σ (Threshold: {sensitivity_threshold}σ)\n"
                    f"• Risk Score: {risk_score}/100"
                )
                recommended_action = "Expedite processing or investigate warehouse bottleneck."

                vals = {
                    'name': f"Delayed Operation: {picking.name}",
                    'rule_type': 'delay_risk',
                    'related_model': 'stock.picking',
                    'related_res_id': picking.id,
                    'location_id': picking.location_dest_id.id if picking.location_dest_id else picking.location_id.id,
                    'score': risk_score,
                    'severity': severity,
                    'actual_value': elapsed_hours,
                    'baseline_mean': mean_hours,
                    'baseline_std': std_hours,
                    'z_score': z_score,
                    'explanation': explanation,
                    'evidence': evidence,
                    'recommended_action': recommended_action,
                }

                if existing_item:
                    existing_item.write(vals)
                else:
                    vals['state'] = 'new'
                    env['stocksense.watchlist.item'].create(vals)
                    flagged_count += 1

        return flagged_count

    @classmethod
    def run_full_steward(cls, env):
        """
        Executes complete Steward intelligence audit across all risk vectors.
        """
        _logger.info("StockSense Steward: Running full inventory intelligence audit...")
        delays_flagged = cls.evaluate_delays(env)
        _logger.info(f"StockSense Steward: Audit completed. Flagged {delays_flagged} delayed operations.")
        return {
            'delays_flagged': delays_flagged,
            'timestamp': datetime.now().isoformat(),
        }

    @classmethod
    def process_feedback(cls, env, watchlist_item, feedback_type):
        """
        Continuously adapts thresholds deterministically based on manager feedback.
        - true_positive: Confirms detection accuracy. Gently tightens sensitivity threshold (-0.1).
        - false_positive: Identifies over-sensitivity. Gently increases sensitivity threshold (+0.2).
        - unclear: Neutral record, does not adjust threshold.
        """
        rule_config = env['stocksense.rule.config'].search([
            ('rule_type', '=', watchlist_item.rule_type),
            ('active', '=', True),
        ], limit=1)
        if not rule_config:
            return

        current_thresh = rule_config.sensitivity_threshold
        if feedback_type == 'false_positive':
            new_thresh = min(5.0, round(current_thresh + 0.2, 2))
            rule_config.write({
                'sensitivity_threshold': new_thresh,
                'dismiss_streak': rule_config.dismiss_streak + 1,
            })
            _logger.info(f"StockSense: Increased {rule_config.rule_type} threshold to {new_thresh} due to false positive.")
        elif feedback_type == 'true_positive':
            new_thresh = max(2.0, round(current_thresh - 0.1, 2))
            rule_config.write({
                'sensitivity_threshold': new_thresh,
                'dismiss_streak': 0,
            })
            _logger.info(f"StockSense: Tightened {rule_config.rule_type} threshold to {new_thresh} due to confirmed alert.")
