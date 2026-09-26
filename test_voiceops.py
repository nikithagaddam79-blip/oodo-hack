# -*- coding: utf-8 -*-
# Part of StockSense Hackathon Module. See LICENSE file for full copyright and licensing details.

from odoo.tests.common import TransactionCase
from ..services.voice_parser import VoiceParser, parse_spoken_number


class TestStockSenseVoiceOps(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env.ref('stocksense_hackathon.product_steel_rods', raise_if_not_found=False)
        if not cls.product:
            cls.product = cls.env['product.product'].create({
                'name': 'Steel Rods',
                'type': 'product',
                'default_code': 'SR-01',
            })
        cls.vendor = cls.env.ref('stocksense_hackathon.partner_vendor_alpha', raise_if_not_found=False)
        if not cls.vendor:
            cls.vendor = cls.env['res.partner'].create({
                'name': 'Vendor Alpha',
            })
        cls.location_rack_b = cls.env.ref('stocksense_hackathon.location_rack_b', raise_if_not_found=False)
        if not cls.location_rack_b:
            cls.location_rack_b = cls.env['stock.location'].create({
                'name': 'Rack B',
                'usage': 'internal',
                'location_id': cls.env.ref('stock.stock_location_stock').id,
            })

    def test_01_spoken_number_parsing(self):
        """
        Verify conversion of spoken number words and negative signs.
        """
        self.assertEqual(parse_spoken_number("fifty"), 50.0)
        self.assertEqual(parse_spoken_number("twenty"), 20.0)
        self.assertEqual(parse_spoken_number("minus twenty"), -20.0)
        self.assertEqual(parse_spoken_number("negative twenty"), -20.0)
        self.assertEqual(parse_spoken_number("-20"), -20.0)
        self.assertEqual(parse_spoken_number("reduce by twenty"), -20.0)
        self.assertEqual(parse_spoken_number("subtract twenty"), -20.0)
        self.assertEqual(parse_spoken_number("100"), 100.0)

    def test_02_parse_receive_intent(self):
        """
        'Receive 50 Steel Rods from Vendor Alpha'
        """
        cmd = "Receive 50 Steel Rods from Vendor Alpha"
        intent = VoiceParser.parse_transcript(cmd)
        self.assertEqual(intent['action'], 'receive')
        self.assertEqual(intent['quantity'], 50.0)
        self.assertEqual(intent['product'], 'Steel Rods')
        self.assertEqual(intent['supplier'], 'Vendor Alpha')

        # Entity resolution
        resolved = VoiceParser.resolve_entities(self.env, intent)
        self.assertEqual(resolved.get('product_id'), self.product.id)
        self.assertEqual(resolved.get('partner_id'), self.vendor.id)

    def test_03_parse_transfer_intent(self):
        """
        'Move 50 Steel Rods from Main Warehouse to Rack B'
        """
        cmd = "Move 50 Steel Rods from Main Warehouse to Rack B"
        intent = VoiceParser.parse_transcript(cmd)
        self.assertEqual(intent['action'], 'internal_transfer')
        self.assertEqual(intent['quantity'], 50.0)
        self.assertEqual(intent['product'], 'Steel Rods')
        self.assertEqual(intent['destination_location'], 'Rack B')

    def test_04_parse_negative_adjustment_intent(self):
        """
        'Adjust Steel Rods by minus twenty because of damage'
        Must yield quantity = -20.0, NOT +20.0
        """
        cmd = "Adjust Steel Rods by minus twenty because of damage"
        intent = VoiceParser.parse_transcript(cmd)
        self.assertEqual(intent['action'], 'adjust')
        self.assertEqual(intent['quantity'], -20.0)
        self.assertEqual(intent['product'], 'Steel Rods')
        self.assertIn('damage', intent['reason'])

    def test_05_parse_query_stock_intent(self):
        """
        'How many Steel Rods do we have?'
        """
        cmd = "How many Steel Rods do we have?"
        intent = VoiceParser.parse_transcript(cmd)
        self.assertEqual(intent['action'], 'query_stock')
        self.assertEqual(intent['product'], 'Steel Rods')

    def test_06_parse_explain_alert_intent(self):
        """
        'Why is Rack B flagged?'
        """
        cmd = "Why is Rack B flagged?"
        intent = VoiceParser.parse_transcript(cmd)
        self.assertEqual(intent['action'], 'explain_alert')
        self.assertEqual(intent['target'], 'Rack B')

    def test_07_parse_create_recount_task_intent(self):
        """
        'Create a recount task for Rack B'
        """
        cmd = "Create a recount task for Rack B"
        intent = VoiceParser.parse_transcript(cmd)
        self.assertEqual(intent['action'], 'create_task')
        self.assertEqual(intent['target'], 'Rack B')
