# -*- coding: utf-8 -*-
# Part of StockSense Hackathon Module. See LICENSE file for full copyright and licensing details.

import logging
from odoo import http, fields, _
from odoo.http import request
from ..services.voice_parser import VoiceParser
from ..services.steward_engine import StewardEngine

_logger = logging.getLogger(__name__)


def _get_request_env(env=None):
    if env is not None:
        return env
    try:
        return request.env
    except (RuntimeError, AttributeError):
        return None


class StockSenseVoiceController(http.Controller):
    """
    Authenticated JSON API controller for VoiceOps and StockSense Dashboard.
    """

    @http.route('/voiceops/process', type='json', auth='user', methods=['POST'])
    def process_voice_input(self, speech_text=None, intent=None, env=None, **kwargs):
        """
        Parses speech transcription, resolves entities against Odoo models,
        and pre-evaluates risk with Steward before asking user confirmation.
        """
        env = _get_request_env(env)
        if not speech_text and not intent:
            return {'success': False, 'error': 'No speech text or intent provided.'}

        # 1. Parse text if raw string provided
        if speech_text and not intent:
            raw_intent = VoiceParser.parse_transcript(speech_text)
        else:
            raw_intent = dict(intent)

        if raw_intent.get('action') == 'unknown':
            return {
                'success': False,
                'action': 'unknown',
                'raw_text': speech_text,
                'error': raw_intent.get('error', 'Unrecognized warehouse command.'),
            }

        # 2. Entity Resolution
        resolved = VoiceParser.resolve_entities(env, raw_intent)
        if resolved.get('resolution_errors'):
            return {
                'success': False,
                'action': resolved.get('action'),
                'raw_text': speech_text,
                'errors': resolved['resolution_errors'],
                'resolved': resolved,
            }

        action = resolved.get('action')

        # 3. Direct Read-Only or Non-Mutating Actions
        if action in ['query_stock', 'show_alerts', 'explain_alert', 'create_task', 'run_steward']:
            return {
                'success': True,
                'action': action,
                'requires_confirmation': action in ['create_task', 'run_steward'],
                'resolved': resolved,
            }

        # 4. Inventory Mutations: Evaluate risk with Steward
        if action == 'adjust':
            product = env['product.product'].browse(resolved.get('product_id'))
            location = env['stock.location'].browse(resolved.get('source_location_id') or resolved.get('dest_location_id'))
            if not location:
                # Default to warehouse internal stock if location omitted
                wh = env['stock.warehouse'].search([('company_id', '=', env.company.id)], limit=1)
                location = wh.lot_stock_id

            resolved['location_id'] = location.id
            resolved['location_name'] = location.complete_name
            qty = resolved.get('quantity', 0.0)

            eval_res = StewardEngine.evaluate_adjustment(env, product, location, qty)
            resolved['steward_eval'] = eval_res

            return {
                'success': True,
                'action': 'adjust',
                'requires_confirmation': True,
                'is_anomalous': eval_res['is_anomalous'],
                'severity': eval_res['severity'],
                'risk_score': eval_res['risk_score'],
                'z_score': eval_res['z_score'],
                'explanation': eval_res['explanation'],
                'evidence': eval_res['evidence'],
                'recommended_action': eval_res['recommended_action'],
                'resolved': resolved,
            }

        # Transfer / Receive / Deliver
        return {
            'success': True,
            'action': action,
            'requires_confirmation': True,
            'is_anomalous': False,
            'resolved': resolved,
        }

    @http.route('/voiceops/execute', type='json', auth='user', methods=['POST'])
    def execute_operation(self, payload=None, env=None, **kwargs):
        """
        Executes a confirmed warehouse action natively in Odoo.
        Guarantees idempotency and enforces the Steward security boundary.
        """
        env = _get_request_env(env)
        if not payload:
            return {'success': False, 'error': 'No execution payload provided.'}

        action = payload.get('action')
        resolved = payload.get('resolved', {})

        try:
            # 1. RECEIVE GOODS
            if action == 'receive':
                product_id = resolved.get('product_id')
                quantity = resolved.get('quantity', 0.0)
                partner_id = resolved.get('partner_id')
                dest_loc_id = resolved.get('dest_location_id')

                if quantity <= 0:
                    return {'success': False, 'error': 'Received quantity must be positive.'}

                wh = env['stock.warehouse'].search([('company_id', '=', env.company.id)], limit=1)
                picking_type = wh.in_type_id
                dest_location = env['stock.location'].browse(dest_loc_id) if dest_loc_id else picking_type.default_location_dest_id
                src_location = picking_type.default_location_src_id or env.ref('stock.stock_location_suppliers', raise_if_not_found=False) or env['stock.location'].search([('usage', '=', 'supplier')], limit=1)

                picking = env['stock.picking'].create({
                    'picking_type_id': picking_type.id,
                    'location_id': src_location.id,
                    'location_dest_id': dest_location.id,
                    'partner_id': partner_id or False,
                    'origin': 'VoiceOps Reception',
                    'move_ids': [(0, 0, {
                        'name': f"Receipt: {resolved.get('product_name')}",
                        'product_id': product_id,
                        'product_uom': env['product.product'].browse(product_id).uom_id.id,
                        'product_uom_qty': quantity,
                        'quantity': quantity,
                        'location_id': src_location.id,
                        'location_dest_id': dest_location.id,
                    })],
                })
                picking.action_confirm()
                for move in picking.move_ids:
                    move.quantity = quantity
                picking.button_validate()

                return {
                    'success': True,
                    'message': f"Successfully received {quantity:g} units of {resolved.get('product_name')}.",
                    'picking_name': picking.name,
                    'state': picking.state,
                }

            # 2. INTERNAL TRANSFER
            elif action == 'internal_transfer':
                product_id = resolved.get('product_id')
                quantity = resolved.get('quantity', 0.0)
                src_loc_id = resolved.get('source_location_id')
                dest_loc_id = resolved.get('dest_location_id')

                if quantity <= 0:
                    return {'success': False, 'error': 'Transfer quantity must be positive.'}

                wh = env['stock.warehouse'].search([('company_id', '=', env.company.id)], limit=1)
                picking_type = wh.int_type_id
                src_location = env['stock.location'].browse(src_loc_id) if src_loc_id else wh.lot_stock_id
                dest_location = env['stock.location'].browse(dest_loc_id)

                if not dest_location:
                    return {'success': False, 'error': 'Destination location is required for transfers.'}

                picking = env['stock.picking'].create({
                    'picking_type_id': picking_type.id,
                    'location_id': src_location.id,
                    'location_dest_id': dest_location.id,
                    'origin': 'VoiceOps Transfer',
                    'move_ids': [(0, 0, {
                        'name': f"Transfer: {resolved.get('product_name')}",
                        'product_id': product_id,
                        'product_uom': env['product.product'].browse(product_id).uom_id.id,
                        'product_uom_qty': quantity,
                        'quantity': quantity,
                        'location_id': src_location.id,
                        'location_dest_id': dest_location.id,
                    })],
                })
                picking.action_confirm()
                picking.action_assign()
                for move in picking.move_ids:
                    move.quantity = quantity
                picking.button_validate()

                return {
                    'success': True,
                    'message': f"Moved {quantity:g} units from {src_location.name} to {dest_location.name}.",
                    'picking_name': picking.name,
                    'state': picking.state,
                }

            # 3. QUERY STOCK
            elif action == 'query_stock':
                product_id = resolved.get('product_id')
                product = env['product.product'].browse(product_id)
                total_qty = product.qty_available

                # Location breakdown
                quants = env['stock.quant'].search([
                    ('product_id', '=', product_id),
                    ('location_id.usage', '=', 'internal'),
                    ('quantity', '>', 0),
                ])
                loc_details = [
                    f"{q.location_id.complete_name}: {q.quantity:g} units"
                    for q in quants
                ]

                return {
                    'success': True,
                    'product_name': product.display_name,
                    'total_quantity': total_qty,
                    'location_breakdown': loc_details,
                    'message': f"We have {total_qty:g} units of {product.name} across warehouse locations.",
                }

            # 4. INVENTORY ADJUSTMENT (Guarded)
            elif action == 'adjust':
                product_id = resolved.get('product_id')
                loc_id = resolved.get('location_id')
                quantity_change = resolved.get('quantity', 0.0)
                reason = resolved.get('reason')

                adj_req = env['stocksense.adjustment.request'].create({
                    'product_id': product_id,
                    'location_id': loc_id,
                    'quantity_change': quantity_change,
                    'reason': reason or 'VoiceOps Adjustment',
                })
                adj_req.action_submit()

                if adj_req.state == 'pending_approval':
                    return {
                        'success': True,
                        'status': 'pending_approval',
                        'is_anomalous': True,
                        'risk_score': adj_req.risk_score,
                        'z_score': adj_req.z_score,
                        'explanation': adj_req.explanation,
                        'evidence': adj_req.evidence,
                        'recommended_action': adj_req.recommended_action,
                        'message': (
                            f"⚠ Stewardship Alert: Adjustment of {quantity_change:g} units flagged as anomalous "
                            f"(Deviation: {adj_req.z_score}σ, Risk: {adj_req.risk_score}/100). "
                            f"Routed to Pending Manager Review without altering stock."
                        ),
                    }
                else:
                    return {
                        'success': True,
                        'status': 'applied',
                        'is_anomalous': False,
                        'message': f"Adjustment of {quantity_change:g} units applied to inventory.",
                    }

            # 5. EXPLAIN ALERT
            elif action == 'explain_alert':
                target_loc_id = resolved.get('target_location_id')
                target_prod_id = resolved.get('target_product_id')
                target_name = resolved.get('target_display')

                domain = [('state', 'in', ['new', 'acknowledged', 'escalated'])]
                if target_loc_id:
                    domain.append(('location_id', '=', target_loc_id))
                elif target_prod_id:
                    domain.append(('product_id', '=', target_prod_id))
                else:
                    domain.append('|')
                    domain.append(('name', 'ilike', target_name))
                    domain.append(('explanation', 'ilike', target_name))

                item = env['stocksense.watchlist.item'].search(domain, limit=1)
                if item:
                    return {
                        'success': True,
                        'found': True,
                        'title': item.name,
                        'product': item.product_id.name or 'N/A',
                        'location': item.location_id.complete_name or 'N/A',
                        'score': item.score,
                        'severity': item.severity,
                        'z_score': item.z_score,
                        'baseline_mean': item.baseline_mean,
                        'baseline_std': item.baseline_std,
                        'actual_value': item.actual_value,
                        'explanation': item.explanation,
                        'evidence': item.evidence,
                        'recommended_action': item.recommended_action,
                        'message': f"{item.name}: {item.explanation}",
                    }
                else:
                    # Provide baseline info if no active alert
                    return {
                        'success': True,
                        'found': False,
                        'message': f"No active alerts found for '{target_name}'.",
                    }

            # 6. CREATE RECOUNT TASK
            elif action == 'create_task':
                target_loc_id = resolved.get('target_location_id')
                target_name = resolved.get('target_display')
                loc = env['stock.location'].browse(target_loc_id) if target_loc_id else None

                # Find associated watchlist item if exists
                item = env['stocksense.watchlist.item'].search([
                    ('location_id', '=', loc.id if loc else False),
                    ('state', 'in', ['new', 'acknowledged']),
                ], limit=1)

                if item:
                    item.action_create_recount_activity()
                    return {
                        'success': True,
                        'message': f"Created recount activity linked to alert for {target_name}.",
                    }
                else:
                    # Create Watchlist item for recount and schedule activity on it
                    item = env['stocksense.watchlist.item'].create({
                        'name': f"Recount Task: {target_name}",
                        'rule_type': 'variance_recount',
                        'location_id': loc.id if loc else False,
                        'score': 60.0,
                        'severity': 'attention',
                        'state': 'acknowledged',
                        'explanation': f"Physical inventory recount requested via VoiceOps for {target_name}.",
                        'evidence': f"Manual recount triggered by {env.user.name}",
                        'recommended_action': "Perform physical cycle count.",
                    })
                    item.action_create_recount_activity()
                    return {
                        'success': True,
                        'message': f"Created recount task and activity for {target_name}.",
                    }

            # 7. RUN STEWARD
            elif action == 'run_steward':
                res = StewardEngine.run_full_steward(env)
                return {
                    'success': True,
                    'result': res,
                    'message': f"Steward audit complete. Scanned operations and refreshed Watchlist.",
                }

            return {'success': False, 'error': f"Unsupported action: {action}"}

        except Exception as e:
            _logger.exception("Error executing VoiceOps command")
            return {'success': False, 'error': str(e)}

    @http.route('/stocksense/dashboard/data', type='json', auth='user', methods=['POST'])
    def get_dashboard_data(self, env=None, **kwargs):
        """
        Returns real-time KPIs and Watchlist records for the StockSense Steward Dashboard.
        """
        env = _get_request_env(env)
        # KPIs
        total_products = env['product.product'].search_count([('type', '=', 'product')])
        total_quants = env['stock.quant'].search([('location_id.usage', '=', 'internal')])
        total_stock = sum(total_quants.mapped('quantity'))
        pending_ops = env['stock.picking'].search_count([('state', 'in', ['confirmed', 'assigned'])])
        low_stock_items = env['product.product'].search_count([('type', '=', 'product'), ('qty_available', '<=', 5)])
        
        steward_alerts = env['stocksense.watchlist.item'].search_count([('state', 'in', ['new', 'acknowledged', 'escalated'])])
        critical_alerts = env['stocksense.watchlist.item'].search_count([('severity', '=', 'critical'), ('state', 'in', ['new', 'acknowledged', 'escalated'])])
        delayed_ops = env['stocksense.watchlist.item'].search_count([('rule_type', '=', 'delay_risk'), ('state', 'in', ['new', 'acknowledged', 'escalated'])])
        pending_reviews = env['stocksense.adjustment.request'].search_count([('state', '=', 'pending_approval')])

        # Watchlist Items
        watchlist_records = env['stocksense.watchlist.item'].search([
            ('state', 'in', ['new', 'acknowledged', 'escalated']),
        ], order='score desc, create_date desc', limit=20)

        watchlist = [{
            'id': item.id,
            'name': item.name,
            'rule_type': item.rule_type,
            'product_name': item.product_id.name or 'N/A',
            'location_name': item.location_id.name or 'N/A',
            'score': item.score,
            'severity': item.severity,
            'actual_value': item.actual_value,
            'baseline_mean': item.baseline_mean,
            'baseline_std': item.baseline_std,
            'z_score': item.z_score,
            'explanation': item.explanation,
            'evidence': item.evidence,
            'recommended_action': item.recommended_action,
            'state': item.state,
            'feedback': item.feedback,
            'create_date': fields.Datetime.to_string(item.create_date),
        } for item in watchlist_records]

        # Pending Adjustment Requests
        adj_records = env['stocksense.adjustment.request'].search([
            ('state', '=', 'pending_approval'),
        ], order='create_date desc', limit=10)

        adjustments = [{
            'id': adj.id,
            'name': adj.name,
            'product_name': adj.product_id.name,
            'location_name': adj.location_id.complete_name,
            'quantity_change': adj.quantity_change,
            'current_quantity': adj.current_quantity,
            'new_quantity': adj.new_quantity,
            'reason': adj.reason,
            'risk_score': adj.risk_score,
            'z_score': adj.z_score,
            'severity': adj.severity,
            'explanation': adj.explanation,
            'evidence': adj.evidence,
            'recommended_action': adj.recommended_action,
            'requested_by': adj.requested_by.name,
        } for adj in adj_records]

        return {
            'success': True,
            'kpis': {
                'total_products': total_products,
                'total_stock': total_stock,
                'pending_ops': pending_ops,
                'low_stock_items': low_stock_items,
                'steward_alerts': steward_alerts,
                'critical_alerts': critical_alerts,
                'delayed_ops': delayed_ops,
                'pending_reviews': pending_reviews,
            },
            'watchlist': watchlist,
            'adjustments': adjustments,
        }

    @http.route('/stocksense/steward/run', type='json', auth='user', methods=['POST'])
    def trigger_steward(self, env=None, **kwargs):
        """
        Manually triggers full Steward audit from the dashboard button.
        """
        env = _get_request_env(env)
        res = StewardEngine.run_full_steward(env)
        return {'success': True, 'result': res}
