# -*- coding: utf-8 -*-
# Part of StockSense Hackathon Module. See LICENSE file for full copyright and licensing details.

"""
Seed script to set up demo company, delayed operations, and baseline data
for the end-to-end hackathon demonstration.
Can be executed via odoo-bin shell or as a standalone script.
"""

from datetime import datetime, timedelta


def seed_demo_data(env):
    print("=== StockSense: Seeding Demo Environment ===")

    # 1. Update company name
    company = env['res.company'].search([], limit=1)
    if company:
        company.name = "TrueStock Co."
        print(f"Set primary company to: {company.name}")

    # 2. Locations
    stock_loc = env.ref('stock.stock_location_stock')
    rack_b = env.ref('stocksense_hackathon.location_rack_b', raise_if_not_found=False)
    if not rack_b:
        rack_b = env['stock.location'].search([('name', '=', 'Rack B')], limit=1)

    # 3. Product: Steel Rods
    steel_rods = env.ref('stocksense_hackathon.product_steel_rods', raise_if_not_found=False)
    if not steel_rods:
        steel_rods = env['product.product'].search([('name', '=', 'Steel Rods')], limit=1)

    # 4. Vendor Alpha
    vendor_alpha = env.ref('stocksense_hackathon.partner_vendor_alpha', raise_if_not_found=False)
    if not vendor_alpha:
        vendor_alpha = env['res.partner'].search([('name', '=', 'Vendor Alpha')], limit=1)

    # 5. Baseline for Steel Rods @ Rack B
    baseline = env['stocksense.baseline.stat'].search([
        ('product_id', '=', steel_rods.id if steel_rods else False),
        ('location_id', '=', rack_b.id if rack_b else False),
        ('metric_type', '=', 'adjustment_magnitude'),
    ], limit=1)
    if baseline:
        baseline.write({
            'mean_value': -3.0,
            'std_value': 1.5,
            'sample_count': 120,
        })
    elif steel_rods and rack_b:
        env['stocksense.baseline.stat'].create({
            'product_id': steel_rods.id,
            'location_id': rack_b.id,
            'metric_type': 'adjustment_magnitude',
            'mean_value': -3.0,
            'std_value': 1.5,
            'sample_count': 120,
        })
    print("Verified baseline for Steel Rods @ Rack B: Mean = -3.0, Std = 1.5, N = 120")

    # 6. Create Demo Delayed Receipt (19 hours elapsed)
    wh = env['stock.warehouse'].search([('company_id', '=', env.company.id)], limit=1)
    if not wh:
        wh = env['stock.warehouse'].search([], limit=1)
    comp_id = wh.company_id.id if wh else env.company.id

    if wh and steel_rods and vendor_alpha:
        dest_loc_id = rack_b.id if rack_b else wh.lot_stock_id.id
        existing_delayed = env['stock.picking'].search([
            ('origin', '=', 'Demo Delayed Receipt Alpha'),
            ('state', 'in', ['confirmed', 'assigned']),
        ], limit=1)

        if existing_delayed:
            if rack_b and existing_delayed.location_dest_id.id != rack_b.id:
                existing_delayed.write({'location_dest_id': rack_b.id})
                existing_delayed.move_ids.write({'location_dest_id': rack_b.id})
        else:
            scheduled_19h_ago = datetime.now() - timedelta(hours=19)
            supplier_loc = wh.in_type_id.default_location_src_id or env.ref('stock.stock_location_suppliers')
            picking = env['stock.picking'].create({
                'picking_type_id': wh.in_type_id.id,
                'company_id': comp_id,
                'partner_id': vendor_alpha.id,
                'location_id': supplier_loc.id,
                'location_dest_id': dest_loc_id,
                'origin': 'Demo Delayed Receipt Alpha',
                'scheduled_date': scheduled_19h_ago,
                'move_ids': [(0, 0, {
                    'name': 'Pending Supply: Steel Rods',
                    'product_id': steel_rods.id,
                    'product_uom': steel_rods.uom_id.id,
                    'product_uom_qty': 100.0,
                    'quantity': 0.0,
                    'company_id': comp_id,
                    'location_id': supplier_loc.id,
                    'location_dest_id': dest_loc_id,
                })],
            })
            picking.action_confirm()
            # Force scheduled_date and create_date in DB
            env.cr.execute(
                "UPDATE stock_picking SET scheduled_date = %s, create_date = %s WHERE id = %s",
                (scheduled_19h_ago, scheduled_19h_ago, picking.id)
            )
            print(f"Created demo delayed receipt {picking.name} scheduled 19 hours ago.")

    print("=== Demo Environment Seeding Finished Successfully ===")


if __name__ == '__main__' and 'env' in locals():
    seed_demo_data(env)
