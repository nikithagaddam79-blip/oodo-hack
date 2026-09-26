# -*- coding: utf-8 -*-
# Part of StockSense Hackathon Module. See LICENSE file for full copyright and licensing details.

from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError
from ..services.steward_engine import StewardEngine


class TestStockSenseSteward(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Create test product and location
        cls.product = cls.env['product.product'].create({
            'name': 'Test Steel Rods',
            'type': 'product',
            'default_code': 'TEST-STEEL',
        })
        cls.location = cls.env['stock.location'].create({
            'name': 'Test Rack B',
            'usage': 'internal',
            'location_id': cls.env.ref('stock.stock_location_stock').id,
        })
        # Set baseline: Mean = -3.0, Std = 1.5, Samples = 120
        cls.baseline = cls.env['stocksense.baseline.stat'].create({
            'product_id': cls.product.id,
            'location_id': cls.location.id,
            'metric_type': 'adjustment_magnitude',
            'mean_value': -3.0,
            'std_value': 1.5,
            'sample_count': 120,
        })
        # Rule config
        cls.rule_config = cls.env['stocksense.rule.config'].search([
            ('rule_type', '=', 'shrinkage_anomaly'),
        ], limit=1)
        if not cls.rule_config:
            cls.rule_config = cls.env['stocksense.rule.config'].create({
                'name': 'Test Shrinkage Rule',
                'rule_type': 'shrinkage_anomaly',
                'sensitivity_threshold': 3.0,
                'min_sample_size': 10,
            })
        else:
            cls.rule_config.write({'sensitivity_threshold': 3.0})
        # Create warehouse staff user
        cls.staff_user = cls.env['res.users'].create({
            'name': 'Test Warehouse Staff',
            'login': 'test_staff',
            'email': 'staff@test.com',
            'groups_id': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('stock.group_stock_user').id,
                cls.env.ref('stocksense_hackathon.group_stocksense_user').id,
            ])],
        })
        # Create inventory manager user
        cls.manager_user = cls.env['res.users'].create({
            'name': 'Test Inventory Manager',
            'login': 'test_manager',
            'email': 'manager@test.com',
            'groups_id': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('stock.group_stock_manager').id,
                cls.env.ref('stocksense_hackathon.group_stocksense_manager').id,
            ])],
        })

    def test_01_statistical_z_score_calculation(self):
        """
        Verify exact Z-Score calculation:
        abs(-20 - (-3.0)) / 1.5 = 17 / 1.5 = 11.33
        """
        z = StewardEngine.calculate_z_score(-20.0, -3.0, 1.5)
        self.assertAlmostEqual(z, 11.333333, places=2)

        # Zero std deviation safe handling
        z_safe_zero = StewardEngine.calculate_z_score(-3.0, -3.0, 0.0)
        self.assertEqual(z_safe_zero, 0.0)

        z_safe_diff = StewardEngine.calculate_z_score(-20.0, -3.0, 0.0)
        self.assertGreater(z_safe_diff, 0.0)

    def test_02_insufficient_history(self):
        """
        If sample count is below minimum required samples, do not classify as anomalous.
        """
        sparse_product = self.env['product.product'].create({
            'name': 'Sparse Product',
            'type': 'product',
        })
        self.env['stocksense.baseline.stat'].create({
            'product_id': sparse_product.id,
            'location_id': self.location.id,
            'metric_type': 'adjustment_magnitude',
            'mean_value': -2.0,
            'std_value': 1.0,
            'sample_count': 3,  # < min_sample_size (10)
        })

        eval_res = StewardEngine.evaluate_adjustment(self.env, sparse_product, self.location, -50.0)
        self.assertFalse(eval_res['is_anomalous'])
        self.assertEqual(eval_res['severity'], 'normal')
        self.assertIn("Insufficient historical data", eval_res['explanation'])

    def test_03_demo_anomaly_evaluation(self):
        """
        Verify that Steel Rods @ Rack B with -20 adjustment produces:
        z = 11.33, is_anomalous = True, severity = critical, risk_score >= 80.
        """
        eval_res = StewardEngine.evaluate_adjustment(self.env, self.product, self.location, -20.0)
        self.assertTrue(eval_res['is_anomalous'])
        self.assertEqual(eval_res['z_score'], 11.33)
        self.assertEqual(eval_res['severity'], 'critical')
        self.assertGreaterEqual(eval_res['risk_score'], 80.0)
        self.assertIn("11.33σ", eval_res['evidence'])
        self.assertIn("recount", eval_res['recommended_action'].lower())

    def test_04_adjustment_security_and_approval_gate(self):
        """
        Test that a suspicious adjustment:
        1. Routes to pending_approval and creates a Watchlist item.
        2. Cannot be approved by warehouse staff (Access Denied).
        3. Can be approved by Inventory Manager, creating a real stock move.
        """
        # Staff user requests suspicious adjustment of -20
        adj_req = self.env['stocksense.adjustment.request'].with_user(self.staff_user).create({
            'product_id': self.product.id,
            'location_id': self.location.id,
            'quantity_change': -20.0,
            'reason': 'Water damage on lower shelf',
        })
        adj_req.action_submit()

        self.assertEqual(adj_req.state, 'pending_approval')
        self.assertTrue(adj_req.watchlist_id)
        self.assertEqual(adj_req.z_score, 11.33)

        # Staff attempts to self-approve -> Must fail
        with self.assertRaises(UserError):
            adj_req.with_user(self.staff_user).action_approve()

        # Manager approves
        adj_req.with_user(self.manager_user).action_approve()
        self.assertEqual(adj_req.state, 'approved')
        self.assertTrue(adj_req.stock_move_id)
        self.assertEqual(adj_req.stock_move_id.state, 'done')
        self.assertEqual(adj_req.watchlist_id.state, 'resolved')

    def test_05_feedback_threshold_adaptation(self):
        """
        Verify manager feedback adapts sensitivity threshold boundedly and deterministically.
        """
        watchlist_item = self.env['stocksense.watchlist.item'].create({
            'name': 'Test Alert',
            'rule_type': 'shrinkage_anomaly',
            'score': 85.0,
            'severity': 'critical',
            'z_score': 11.33,
        })
        init_thresh = self.rule_config.sensitivity_threshold  # 3.0

        # False positive increases threshold
        watchlist_item.action_feedback_false_positive()
        self.rule_config.invalidate_recordset()
        self.assertEqual(self.rule_config.sensitivity_threshold, round(init_thresh + 0.2, 2))
        self.assertEqual(watchlist_item.state, 'dismissed')

        # True positive tightens threshold
        watchlist_item.action_feedback_true_positive()
        self.rule_config.invalidate_recordset()
        self.assertEqual(self.rule_config.sensitivity_threshold, round(init_thresh + 0.2 - 0.1, 2))
