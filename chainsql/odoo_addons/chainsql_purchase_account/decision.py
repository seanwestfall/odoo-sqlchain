"""Pure, deterministic policy. Document text is deliberately not an input.
Advisory proposals have no wallet, tools, asset, amount or policy fields.
"""
import hashlib
import json
from datetime import date

ACTIONS = ('pay_now', 'defer', 'request_information', 'hold')
VERSION = 'purchasing-baseline-v1'


def fingerprint(evidence):
    return hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def evaluate(e):
    reasons = []
    if e.get('existing_obligation'): reasons.append('existing_obligation_reconcile')
    if e['duplicate_ids']: reasons.append('duplicate_reference')
    if not e['approval_current']: reasons.append('stale_or_expired_approval')
    if not e['eligible_bill']: reasons.append('unsupported_bill_or_currency')
    if e['inconsistent']: reasons.append('inconsistent_purchase_amount_or_quantity')
    if reasons: return dict(action='hold', date=None, reasons=reasons)
    if e['missing_receipts'] or e['unlinked_lines']:
        return dict(action='request_information', date=None, reasons=['missing_receipt_or_purchase_link'])
    if int(e['amount_atomic']) > int(e['available_atomic']):
        return dict(action='hold', date=None, reasons=['insufficient_available_budget'])
    if e.get('discount_date') and e['discount_date'] >= e['today']:
        # Discount settlement amounts require fresh independent approval, never silently reduce a payment.
        return dict(action='hold', date=None, reasons=['discount_requires_amount_review'])
    if e.get('due_date') and e['due_date'] > e['today']:
        return dict(action='defer', date=e['due_date'], reasons=['not_due'])
    return dict(action='pay_now', date=None, reasons=['purchase_and_receipt_match'])


def decide(e, policy, proposal=None):
    baseline = evaluate(e)
    proposed = baseline['action']
    when = baseline['date']
    explanation = '; '.join(baseline['reasons'])
    if proposal is not None:
        if not isinstance(proposal, dict) or set(proposal) != {'action', 'date', 'justification'}:
            raise ValueError('Only action, date and justification are accepted.')
        if proposal['action'] not in ACTIONS or not isinstance(proposal['justification'], str) or not 1 <= len(proposal['justification']) <= 1000:
            raise ValueError('Invalid structured recommendation.')
        proposed, when, explanation = proposal['action'], proposal['date'], proposal['justification']
        if proposed == 'defer':
            if not isinstance(when, str) or date.fromisoformat(when).isoformat() != when or when <= e['today']:
                raise ValueError('A deferral requires a future ISO date.')
        elif when is not None: raise ValueError('Only deferrals have a date.')
    # An agent may become more conservative, but cannot promote blocked evidence to payment.
    if proposed == 'pay_now' and baseline['action'] != 'pay_now':
        outcome = 'blocked'
    elif proposed != 'pay_now':
        outcome = 'advisory'
    elif not policy['enabled'] or int(e['amount_atomic']) > int(policy['limit_atomic']):
        outcome = 'human_required'
    else:
        outcome = 'delegated_eligible'
    return dict(baseline=baseline, proposed_action=proposed, defer_until=when,
                justification=explanation, policy_outcome=outcome, policy_version=VERSION)
