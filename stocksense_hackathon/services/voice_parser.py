# -*- coding: utf-8 -*-
# Part of StockSense Hackathon Module. See LICENSE file for full copyright and licensing details.

import re
import logging

_logger = logging.getLogger(__name__)

# Number word dictionary for spoken number normalization
NUMBER_WORDS = {
    'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4,
    'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9,
    'ten': 10, 'eleven': 11, 'twelve': 12, 'thirteen': 13,
    'fourteen': 14, 'fifteen': 15, 'sixteen': 16, 'seventeen': 17,
    'eighteen': 18, 'nineteen': 19, 'twenty': 20, 'thirty': 30,
    'forty': 40, 'fifty': 50, 'sixty': 60, 'seventy': 70,
    'eighty': 80, 'ninety': 90, 'hundred': 100, 'thousand': 1000,
}


def parse_spoken_number(text):
    """
    Parses numeric strings or spoken number expressions like
    'fifty', 'minus twenty', 'negative 20', '-20', 'subtract 20', 'reduce by 20'.
    Returns float or None.
    """
    if not text:
        return None
    cleaned = text.strip().lower()
    
    # Check negative indicators
    is_negative = False
    negative_prefixes = ['minus', 'negative', 'subtract', 'reduce by', '-']
    for prefix in negative_prefixes:
        if cleaned.startswith(prefix):
            is_negative = True
            cleaned = cleaned[len(prefix):].strip()
            break
        elif f" {prefix} " in f" {cleaned} ":
            is_negative = True
            cleaned = re.sub(rf'\b{prefix}\b', '', cleaned).strip()
            break

    # Direct float/int regex
    direct_match = re.search(r'[-+]?\d*\.?\d+', cleaned)
    if direct_match:
        val = float(direct_match.group(0))
        return -abs(val) if is_negative else val

    # Word-based number parsing
    words = re.findall(r'\b[a-z]+\b', cleaned)
    total = 0
    current = 0
    found_number = False

    for word in words:
        if word in NUMBER_WORDS:
            found_number = True
            val = NUMBER_WORDS[word]
            if val == 100:
                current = (current or 1) * 100
            elif val == 1000:
                total += (current or 1) * 1000
                current = 0
            else:
                current += val

    total += current
    if found_number:
        return -float(total) if is_negative else float(total)
    return None


class VoiceParser:
    """
    Deterministic rule-based NLP parser for warehouse operations.
    Translates spoken warehouse phrases into structured intent schemas.
    """

    @classmethod
    def parse_transcript(cls, text):
        """
        Parses raw voice transcription text into a normalized intent dictionary.
        Supported actions:
        - receive
        - internal_transfer
        - deliver
        - adjust
        - query_stock
        - show_alerts
        - explain_alert
        - create_task
        - run_steward
        """
        if not text:
            return {
                'action': 'unknown',
                'error': 'Empty speech input',
                'confidence': 0.0,
            }

        cleaned = text.strip()
        lower = cleaned.lower()

        # 1. RUN STEWARD
        if re.search(r'\b(run|trigger|start)\s+(steward|audit|analysis)\b', cleaned, re.IGNORECASE) or lower == "run steward now":
            return {
                'action': 'run_steward',
                'raw_text': cleaned,
                'confidence': 0.99,
            }

        # 2. SHOW ALERTS
        if re.search(r'\b(show|view|list|open)\s+(alerts|watchlist|anomalies|warnings)\b', cleaned, re.IGNORECASE):
            return {
                'action': 'show_alerts',
                'raw_text': cleaned,
                'confidence': 0.98,
            }

        # 3. EXPLAIN ALERT / WHY FLAGGED
        explain_match = re.search(r'why\s+is\s+(.+?)\s+flagged', cleaned, re.IGNORECASE) or \
                        re.search(r'explain\s+(?:alert|warning|flag)\s*(?:for\s+)?(.+)', cleaned, re.IGNORECASE)
        if explain_match:
            target = explain_match.group(1).strip(" ?.")
            return {
                'action': 'explain_alert',
                'target': target,
                'raw_text': cleaned,
                'confidence': 0.96,
            }

        # 4. CREATE RECOUNT TASK
        task_match = re.search(r'create\s+(?:a\s+)?(?:recount|count|inventory)\s+task\s+(?:for\s+)?(.+)', cleaned, re.IGNORECASE)
        if task_match:
            target = task_match.group(1).strip(" ?.")
            return {
                'action': 'create_task',
                'target': target,
                'raw_text': cleaned,
                'confidence': 0.96,
            }

        # 5. QUERY STOCK
        query_match = re.search(r'how\s+many\s+(.+?)\s+(?:do\s+we\s+have|are\s+in\s+stock|in\s+stock)', cleaned, re.IGNORECASE) or \
                      re.search(r'(?:what\s+is\s+the\s+stock\s+of|stock\s+of|check\s+stock\s+for)\s+(.+)', cleaned, re.IGNORECASE)
        if query_match:
            product = query_match.group(1).strip(" ?.")
            return {
                'action': 'query_stock',
                'product': product,
                'raw_text': cleaned,
                'confidence': 0.95,
            }

        # 6. INVENTORY ADJUSTMENT
        adjust_match = re.search(
            r'(?:adjust|change|correct|update)\s+(.+?)\s+by\s+([a-z0-9\-+\s]+?)(?:\s+because\s+of\s+|\s+due\s+to\s+|\s+reason\s+:?\s*)(.*)',
            cleaned,
            re.IGNORECASE
        )
        if not adjust_match:
            adjust_match = re.search(r'(?:adjust|change|correct|update)\s+(.+?)\s+by\s+([a-z0-9\-+\s]+)', cleaned, re.IGNORECASE)
        if not adjust_match:
            reduce_match = re.search(r'(?:reduce|decrease|subtract)\s+(.+?)\s+by\s+([a-z0-9\-+\s]+?)(?:\s+because\s+of\s+|\s+due\s+to\s+|$)(.*)', cleaned, re.IGNORECASE)
            if reduce_match:
                prod = reduce_match.group(1).strip()
                raw_qty = reduce_match.group(2).strip()
                reason = reduce_match.group(3).strip() if reduce_match.group(3) else None
                qty = parse_spoken_number(raw_qty)
                if qty is not None:
                    qty = -abs(qty)
                return {
                    'action': 'adjust',
                    'product': prod,
                    'quantity': qty,
                    'reason': reason,
                    'raw_text': cleaned,
                    'confidence': 0.95,
                }

        if adjust_match:
            prod = adjust_match.group(1).strip()
            raw_qty = adjust_match.group(2).strip()
            reason = adjust_match.group(3).strip() if len(adjust_match.groups()) >= 3 and adjust_match.group(3) else None
            qty = parse_spoken_number(raw_qty)
            return {
                'action': 'adjust',
                'product': prod,
                'quantity': qty,
                'reason': reason,
                'raw_text': cleaned,
                'confidence': 0.95,
            }

        # 7. RECEIVE GOODS
        receive_match = re.search(
            r'receive\s+([a-z0-9\-+\s]+?)\s+(?:units?\s+of\s+)?(.+?)\s+from\s+(.+)',
            cleaned,
            re.IGNORECASE
        )
        if receive_match:
            raw_qty = receive_match.group(1).strip()
            product = receive_match.group(2).strip()
            supplier = receive_match.group(3).strip(" .")
            qty = parse_spoken_number(raw_qty)
            return {
                'action': 'receive',
                'product': product,
                'quantity': qty,
                'supplier': supplier,
                'raw_text': cleaned,
                'confidence': 0.97,
            }

        # 8. INTERNAL TRANSFER
        transfer_match = re.search(
            r'(?:move|transfer)\s+([a-z0-9\-+\s]+?)\s+(?:units?\s+of\s+)?(.+?)\s+from\s+(.+?)\s+to\s+(.+)',
            cleaned,
            re.IGNORECASE
        )
        if transfer_match:
            raw_qty = transfer_match.group(1).strip()
            product = transfer_match.group(2).strip()
            src = transfer_match.group(3).strip()
            dest = transfer_match.group(4).strip(" .")
            qty = parse_spoken_number(raw_qty)
            return {
                'action': 'internal_transfer',
                'product': product,
                'quantity': qty,
                'source_location': src,
                'destination_location': dest,
                'raw_text': cleaned,
                'confidence': 0.97,
            }

        # 9. DELIVER GOODS
        deliver_match = re.search(
            r'deliver\s+([a-z0-9\-+\s]+?)\s+(?:units?\s+of\s+)?(.+?)\s+to\s+(.+)',
            cleaned,
            re.IGNORECASE
        )
        if deliver_match:
            raw_qty = deliver_match.group(1).strip()
            product = deliver_match.group(2).strip()
            customer = deliver_match.group(3).strip(" .")
            qty = parse_spoken_number(raw_qty)
            return {
                'action': 'deliver',
                'product': product,
                'quantity': qty,
                'customer': customer,
                'raw_text': cleaned,
                'confidence': 0.95,
            }

        return {
            'action': 'unknown',
            'raw_text': cleaned,
            'confidence': 0.3,
            'error': f"Could not determine warehouse action from: '{cleaned}'",
        }

    @classmethod
    def resolve_entities(cls, env, intent):
        """
        Resolves products, locations, and partners against actual Odoo records.
        Strict verification: Never guesses if ambiguous or missing.
        """
        resolved = dict(intent)
        errors = []

        # 1. Product Resolution
        if 'product' in intent and intent['product']:
            p_name = intent['product'].strip()
            # Try exact match, case-insensitive match, or barcode/default_code
            product = env['product.product'].search([
                '|', '|',
                ('name', '=ilike', p_name),
                ('default_code', '=ilike', p_name),
                ('barcode', '=ilike', p_name),
            ], limit=2)

            if not product:
                # Controlled partial match
                product = env['product.product'].search([
                    ('name', 'ilike', p_name),
                ], limit=2)

            if len(product) == 1:
                resolved['product_id'] = product.id
                resolved['product_name'] = product.display_name
            elif len(product) > 1:
                errors.append(f"Ambiguous product '{p_name}'. Found multiple matches: {', '.join(product.mapped('name'))}.")
            else:
                errors.append(f"Product '{p_name}' not found in inventory.")

        # 2. Location Resolution (Source & Destination)
        for loc_key, target_field in [('source_location', 'source_location_id'), ('destination_location', 'dest_location_id')]:
            if loc_key in intent and intent[loc_key]:
                loc_name = intent[loc_key].strip()
                location = env['stock.location'].search([
                    '|',
                    ('name', '=ilike', loc_name),
                    ('complete_name', 'ilike', loc_name),
                ], limit=2)
                if len(location) == 1:
                    resolved[target_field] = location.id
                    resolved[f"{loc_key}_name"] = location.complete_name
                elif len(location) > 1:
                    errors.append(f"Ambiguous location '{loc_name}'. Found multiple matches: {', '.join(location.mapped('complete_name'))}.")
                else:
                    errors.append(f"Location '{loc_name}' not found.")

        # 3. Supplier / Partner Resolution
        if 'supplier' in intent and intent['supplier']:
            s_name = intent['supplier'].strip()
            partner = env['res.partner'].search([
                ('name', '=ilike', s_name),
            ], limit=2)
            if not partner:
                partner = env['res.partner'].search([
                    ('name', 'ilike', s_name),
                ], limit=2)

            if len(partner) == 1:
                resolved['partner_id'] = partner.id
                resolved['partner_name'] = partner.name
            elif len(partner) > 1:
                errors.append(f"Ambiguous vendor '{s_name}'. Found multiple matches: {', '.join(partner.mapped('name'))}.")
            else:
                # Auto-create or flag
                errors.append(f"Vendor '{s_name}' not found in contacts.")

        # 4. Target Resolution (for explain_alert / create_task)
        if 'target' in intent and intent['target']:
            target_str = intent['target'].strip()
            # Try location first
            loc = env['stock.location'].search([
                '|',
                ('name', '=ilike', target_str),
                ('complete_name', 'ilike', target_str),
            ], limit=1)
            if loc:
                resolved['target_location_id'] = loc.id
                resolved['target_type'] = 'location'
                resolved['target_display'] = loc.complete_name
            else:
                prod = env['product.product'].search([
                    ('name', '=ilike', target_str),
                ], limit=1)
                if prod:
                    resolved['target_product_id'] = prod.id
                    resolved['target_type'] = 'product'
                    resolved['target_display'] = prod.display_name
                else:
                    resolved['target_display'] = target_str

        resolved['resolution_errors'] = errors
        return resolved
