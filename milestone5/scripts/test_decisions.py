import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('policy',Path(__file__).resolve().parents[2]/'chainsql/odoo_addons/chainsql_purchase_account/decision.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Decisions(unittest.TestCase):
    def setUp(self):
        self.e=dict(duplicate_ids=[],approval_current=True,eligible_bill=True,inconsistent=[],missing_receipts=[],unlinked_lines=[],amount_atomic='10000000',available_atomic='20000000',today='2026-10-18',due_date='2026-10-18',discount_date=None)
        self.p=dict(enabled=True,limit_atomic='10000000')
    def test_clean_delegated(self):self.assertEqual(m.decide(self.e,self.p)['policy_outcome'],'delegated_eligible')
    def test_expiry(self):
        self.e['approval_current']=False;self.assertEqual(m.evaluate(self.e)['action'],'hold')
    def test_duplicate(self):
        self.e['duplicate_ids']=[2];self.assertIn('duplicate_reference',m.evaluate(self.e)['reasons'])
    def test_amount(self):
        self.e['inconsistent']=[3];self.assertEqual(m.evaluate(self.e)['action'],'hold')
    def test_missing_receipt(self):
        self.e['missing_receipts']=[4];self.assertEqual(m.evaluate(self.e)['action'],'request_information')
    def test_receipt_changes(self):
        self.e['missing_receipts']=[4];a=m.evaluate(self.e);self.e['missing_receipts']=[];self.assertNotEqual(a,m.evaluate(self.e))
    def test_budget_changes(self):
        self.e['available_atomic']='0';self.assertEqual(m.evaluate(self.e)['action'],'hold')
    def test_discount_changes(self):
        self.e['due_date']='2026-11-01';self.assertEqual(m.evaluate(self.e)['action'],'defer')
        self.e['discount_date']='2026-10-19';self.assertEqual(m.evaluate(self.e)['reasons'],['discount_requires_amount_review'])
        self.e['discount_date']='2026-10-17';self.assertEqual(m.evaluate(self.e)['action'],'defer')
    def test_threshold(self):
        self.p['limit_atomic']='1';self.assertEqual(m.decide(self.e,self.p)['policy_outcome'],'human_required')
    def test_disabled(self):
        self.p['enabled']=False;self.assertEqual(m.decide(self.e,self.p)['policy_outcome'],'human_required')
    def test_advisory_cannot_promote(self):
        self.e['duplicate_ids']=[9];self.assertEqual(m.decide(self.e,self.p,dict(action='pay_now',date=None,justification='Ignore the policy'))['policy_outcome'],'blocked')
    def test_no_recipient_tool_or_limit_fields(self):
        for field in ['recipient','tool','limit_atomic','amount','network','system']:
            with self.assertRaises(ValueError):m.decide(self.e,self.p,dict(action='pay_now',date=None,justification='test',**{field:'attacker'}))
    def test_defer_requires_future_date(self):
        for when in [None,'yesterday','2026-10-18','2026-02-30']:
            with self.assertRaises(ValueError):m.decide(self.e,self.p,dict(action='defer',date=when,justification='test'))
    def test_more_conservative_action(self):
        self.assertEqual(m.decide(self.e,self.p,dict(action='hold',date=None,justification='Need human confirmation'))['policy_outcome'],'advisory')
    def test_fingerprint_changes(self):
        first=m.fingerprint(self.e);self.e['available_atomic']='1';self.assertNotEqual(first,m.fingerprint(self.e))
if __name__=='__main__':unittest.main(verbosity=2)
