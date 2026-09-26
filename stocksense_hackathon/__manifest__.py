# -*- coding: utf-8 -*-
# Part of StockSense Hackathon Module. See LICENSE file for full copyright and licensing details.

{
    'name': 'StockSense',
    'version': '17.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Odoo records what happened. StockSense understands what is unusual.',
    'description': """
StockSense — Intelligent Inventory Security, VoiceOps & Statistical Anomaly Detection
=====================================================================================
* Deterministic Statistical Intelligence Engine (StockSense Steward)
* Natural Language VoiceOps with Speech Recognition & Regex Parser
* Human-in-the-Loop Inventory Security & Adjustment Approval Gate
* Real-time Watchlist & Explainable Anomaly Breakdown (Z-scores & Evidence)
* Delayed Operation Detection & Native Odoo Activity Scheduling
* Continuous Adaptive Thresholds from Manager Feedback
    """,
    'author': 'StockSense Architecture Team',
    'website': 'https://github.com/stocksense',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'stock',
        'web',
        'mail',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/cron.xml',
        'data/demo_data.xml',
        'views/steward_views.xml',
        'views/dashboard_views.xml',
        'views/menu_views.xml',
        'views/login_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'stocksense_hackathon/static/src/css/stocksense.css',
            'stocksense_hackathon/static/src/js/voiceops.js',
            'stocksense_hackathon/static/src/js/steward_dashboard.js',
            'stocksense_hackathon/static/src/xml/voiceops.xml',
            'stocksense_hackathon/static/src/xml/steward_dashboard.xml',
        ],
        'web.assets_frontend': [
            'stocksense_hackathon/static/src/css/stocksense.css',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
