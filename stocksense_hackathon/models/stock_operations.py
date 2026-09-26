# -*- coding: utf-8 -*-
# Part of StockSense Hackathon Module. See LICENSE file for full copyright and licensing details.

from datetime import datetime
from odoo import api, fields, models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    elapsed_hours = fields.Float(string='Elapsed Hours', compute='_compute_elapsed_hours')
    is_delayed = fields.Boolean(string='Flagged as Delayed', compute='_compute_is_delayed')

    @api.depends('scheduled_date', 'create_date', 'state')
    def _compute_elapsed_hours(self):
        now = datetime.now()
        for picking in self:
            if picking.state not in ['done', 'cancel']:
                ref_time = picking.scheduled_date or picking.create_date
                if ref_time:
                    delta = (now - ref_time).total_seconds() / 3600.0
                    picking.elapsed_hours = round(max(0.0, delta), 1)
                else:
                    picking.elapsed_hours = 0.0
            else:
                picking.elapsed_hours = 0.0

    def _compute_is_delayed(self):
        for picking in self:
            item = self.env['stocksense.watchlist.item'].search([
                ('related_model', '=', 'stock.picking'),
                ('related_res_id', '=', picking.id),
                ('rule_type', '=', 'delay_risk'),
                ('state', 'in', ['new', 'acknowledged', 'escalated']),
            ], limit=1)
            picking.is_delayed = bool(item)
