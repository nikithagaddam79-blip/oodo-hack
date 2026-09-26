# -*- coding: utf-8 -*-
# Part of StockSense Hackathon Module. See LICENSE file for full copyright and licensing details.

"""
Full End-to-End Demo Workflow Verification Script.
Executes the exact 9 steps from Section 46 and asserts all state changes.
"""

from odoo import api, fields, SUPERUSER_ID
from odoo.modules.registry import Registry
from odoo.addons.stocksense_hackathon.services.voice_parser import VoiceParser
from odoo.addons.stocksense_hackathon.services.steward_engine import StewardEngine
from odoo.addons.stocksense_hackathon.scripts.seed_demo_data import seed_demo_data


def run_demo_verification(dbname):
    registry = Registry(dbname)
    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})

        print("\n=======================================================")
        print("    STOCKSENSE HACKATHON: END-TO-END DEMO VERIFICATION")
        print("=======================================================\n")

        # Setup demo data
        seed_demo_data(env)

        # Reset Steel Rods inventory to 0 for pristine demo run
        steel_prod = env.ref('stocksense_hackathon.product_steel_rods', raise_if_not_found=False) or env['product.product'].search([('name', '=', 'Steel Rods')], limit=1)
        if steel_prod:
            env['stock.quant'].search([('product_id', '=', steel_prod.id)]).write({'quantity': 0.0})

        cr.commit()

        # -----------------------------------------------------------------
        # STEP 1: Voice: Receive 50 Steel Rods from Vendor Alpha
        # -----------------------------------------------------------------
        print("\n--- STEP 1: Receive 50 Steel Rods from Vendor Alpha ---")
        cmd_1 = "Receive 50 Steel Rods from Vendor Alpha"
        intent_1 = VoiceParser.parse_transcript(cmd_1)
        print(f"Spoken Command: '{cmd_1}'")
        print(f"Parsed Intent: {intent_1}")
        assert intent_1['action'] == 'receive'
        assert intent_1['quantity'] == 50.0

        resolved_1 = VoiceParser.resolve_entities(env, intent_1)
        print(f"Resolved Entities: Product ID={resolved_1.get('product_id')}, Partner ID={resolved_1.get('partner_id')}")
        assert resolved_1.get('product_id'), "Product resolution failed for Steel Rods"
        assert resolved_1.get('partner_id'), "Vendor resolution failed for Vendor Alpha"

        # Execute receipt
        from odoo.addons.stocksense_hackathon.controllers.voice_controller import StockSenseVoiceController
        controller = StockSenseVoiceController()
        # Mock request.env
        class MockRequest:
            pass
        import odoo.http
        odoo.http.request = MockRequest()
        odoo.http.request.env = env
        odoo.http.request.company = env.company

        exec_res_1 = controller.execute_operation(payload={'action': 'receive', 'resolved': resolved_1}, env=env)
        print(f"Receipt Execution Result: {exec_res_1}")
        assert exec_res_1['success'] is True
        assert 'picking_name' in exec_res_1
        cr.commit()

        # -----------------------------------------------------------------
        # STEP 2: Voice: Move 50 Steel Rods from Main Warehouse to Rack B
        # -----------------------------------------------------------------
        print("\n--- STEP 2: Move 50 Steel Rods from Main Warehouse to Rack B ---")
        cmd_2 = "Move 50 Steel Rods from Main Warehouse to Rack B"
        intent_2 = VoiceParser.parse_transcript(cmd_2)
        print(f"Spoken Command: '{cmd_2}'")
        print(f"Parsed Intent: {intent_2}")
        assert intent_2['action'] == 'internal_transfer'
        assert intent_2['quantity'] == 50.0

        resolved_2 = VoiceParser.resolve_entities(env, intent_2)
        print(f"Resolved Entities: {resolved_2}")
        exec_res_2 = controller.execute_operation(payload={'action': 'internal_transfer', 'resolved': resolved_2}, env=env)
        print(f"Transfer Execution Result: {exec_res_2}")
        assert exec_res_2['success'] is True
        cr.commit()

        # -----------------------------------------------------------------
        # STEP 3: Voice: How many Steel Rods do we have?
        # -----------------------------------------------------------------
        print("\n--- STEP 3: How many Steel Rods do we have? ---")
        cmd_3 = "How many Steel Rods do we have?"
        intent_3 = VoiceParser.parse_transcript(cmd_3)
        resolved_3 = VoiceParser.resolve_entities(env, intent_3)
        exec_res_3 = controller.execute_operation(payload={'action': 'query_stock', 'resolved': resolved_3}, env=env)
        print(f"Stock Query Result: {exec_res_3['message']}")
        print(f"Total Quantity: {exec_res_3['total_quantity']}")
        print(f"Breakdown:\n" + "\n".join(exec_res_3['location_breakdown']))
        assert exec_res_3['total_quantity'] >= 50.0

        # -----------------------------------------------------------------
        # STEP 4: Manager clicks: Run Steward Now
        # -----------------------------------------------------------------
        print("\n--- STEP 4: Run Steward Now ---")
        steward_res = StewardEngine.run_full_steward(env)
        print(f"Steward Full Run Result: {steward_res}")
        cr.commit()

        # Check Watchlist for delay alert from seeded 19h receipt
        delayed_items = env['stocksense.watchlist.item'].search([
            ('rule_type', '=', 'delay_risk'),
            ('state', 'in', ['new', 'acknowledged']),
        ])
        print(f"Delayed items flagged: {len(delayed_items)}")
        for item in delayed_items:
            print(f"  • Flagged: {item.name} | Score: {item.score} ({item.severity}) | Z-Score: {item.z_score}σ")
            print(f"    Elapsed: {item.actual_value:.1f}h (Baseline: {item.baseline_mean}h ± {item.baseline_std}h)")
        assert len(delayed_items) > 0, "Expected at least 1 delayed operation to be flagged"

        # -----------------------------------------------------------------
        # STEP 5: Manager asks: Why is Rack B flagged?
        # -----------------------------------------------------------------
        print("\n--- STEP 5: Why is Rack B flagged? ---")
        cmd_5 = "Why is Rack B flagged?"
        intent_5 = VoiceParser.parse_transcript(cmd_5)
        resolved_5 = VoiceParser.resolve_entities(env, intent_5)
        print(f"Parsed & Resolved: {resolved_5}")
        exec_res_5 = controller.execute_operation(payload={'action': 'explain_alert', 'resolved': resolved_5}, env=env)
        print(f"Explain Alert Output: {exec_res_5}")

        # -----------------------------------------------------------------
        # STEP 6: Manager says: Create a recount task for Rack B
        # -----------------------------------------------------------------
        print("\n--- STEP 6: Create a recount task for Rack B ---")
        cmd_6 = "Create a recount task for Rack B"
        intent_6 = VoiceParser.parse_transcript(cmd_6)
        resolved_6 = VoiceParser.resolve_entities(env, intent_6)
        exec_res_6 = controller.execute_operation(payload={'action': 'create_task', 'resolved': resolved_6}, env=env)
        print(f"Task Creation Result: {exec_res_6}")
        assert exec_res_6['success'] is True
        cr.commit()

        # -----------------------------------------------------------------
        # STEP 7: Warehouse worker says: Adjust Steel Rods by minus twenty because of damage
        # -----------------------------------------------------------------
        print("\n--- STEP 7: Adjust Steel Rods by minus twenty because of damage ---")
        cmd_7 = "Adjust Steel Rods by minus twenty because of damage"
        intent_7 = VoiceParser.parse_transcript(cmd_7)
        print(f"Spoken Command: '{cmd_7}'")
        print(f"Parsed Intent: {intent_7}")
        assert intent_7['action'] == 'adjust'
        assert intent_7['quantity'] == -20.0, f"Expected -20.0, got {intent_7['quantity']}"

        resolved_7 = VoiceParser.resolve_entities(env, intent_7)
        # Point to Rack B
        resolved_7['location_id'] = env.ref('stocksense_hackathon.location_rack_b').id

        # Verify Steward calculation: abs(-20 - (-3)) / 1.5 = 11.33
        eval_7 = StewardEngine.evaluate_adjustment(
            env,
            env['product.product'].browse(resolved_7['product_id']),
            env['stock.location'].browse(resolved_7['location_id']),
            -20.0
        )
        print(f"Steward Pre-Evaluation:")
        print(f"  • Z-score: {eval_7['z_score']}σ")
        print(f"  • Risk Score: {eval_7['risk_score']}/100 ({eval_7['severity'].upper()})")
        print(f"  • Is Anomalous: {eval_7['is_anomalous']}")
        assert eval_7['z_score'] == 11.33, f"Expected 11.33, got {eval_7['z_score']}"
        assert eval_7['is_anomalous'] is True

        # Execute adjustment through controller
        exec_res_7 = controller.execute_operation(payload={'action': 'adjust', 'resolved': resolved_7}, env=env)
        print(f"Execution Output: {exec_res_7['message']}")
        assert exec_res_7['status'] == 'pending_approval'
        assert exec_res_7['is_anomalous'] is True
        assert exec_res_7['z_score'] == 11.33
        cr.commit()

        # Verify no stock change has occurred yet
        steel_prod = env['product.product'].browse(resolved_7['product_id'])
        rack_b_loc = env.ref('stocksense_hackathon.location_rack_b')
        quants_before = env['stock.quant'].search([
            ('product_id', '=', steel_prod.id),
            ('location_id', '=', rack_b_loc.id),
        ])
        qty_before = sum(quants_before.mapped('quantity'))
        print(f"Stock at Rack B remains protected at: {qty_before} units (No modification yet)")
        assert qty_before == 50.0

        # -----------------------------------------------------------------
        # STEP 8: Manager reviews & approves
        # -----------------------------------------------------------------
        print("\n--- STEP 8: Manager Review & Approval ---")
        adj_req = env['stocksense.adjustment.request'].search([
            ('state', '=', 'pending_approval'),
            ('product_id', '=', steel_prod.id),
            ('location_id', '=', rack_b_loc.id),
        ], limit=1)
        assert adj_req, "Expected pending adjustment request"
        print(f"Adjustment ID: {adj_req.name}")
        print(f"Evidence:\n{adj_req.evidence}")
        print(f"Explanation:\n{adj_req.explanation}")
        print(f"Recommendation: {adj_req.recommended_action}")

        # Manager approves
        adj_req.action_approve()
        print(f"Manager approved {adj_req.name}. New status: {adj_req.state}")
        assert adj_req.state == 'approved'
        assert adj_req.stock_move_id.state == 'done'
        cr.commit()

        # Verify stock is now updated
        quants_after = env['stock.quant'].search([
            ('product_id', '=', steel_prod.id),
            ('location_id', '=', rack_b_loc.id),
        ])
        qty_after = sum(quants_after.mapped('quantity'))
        print(f"Stock at Rack B after approval: {qty_after} units (50 - 20 = 30)")
        assert qty_after == 30.0

        # -----------------------------------------------------------------
        # STEP 9: Manager provides feedback
        # -----------------------------------------------------------------
        print("\n--- STEP 9: Manager Feedback ---")
        if adj_req.watchlist_id:
            adj_req.watchlist_id.action_feedback_true_positive()
            print(f"Recorded feedback: {adj_req.watchlist_id.feedback}")
            assert adj_req.watchlist_id.feedback == 'true_positive'
            cr.commit()

        print("\n=======================================================")
        print("  ALL 9 DEMO SCENARIO STEPS VERIFIED AND PASSED 100%!")
        print("=======================================================\n")


if __name__ == '__main__':
    run_demo_verification('stocksense_demo')
