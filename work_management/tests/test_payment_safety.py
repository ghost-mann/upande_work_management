"""Payment safety (2026-11-12): repair tools never touch sent rows, legacy
tools retired, one send at a time, purge cancels the money first, slip submit
checks the money agrees, sends refuse Suspended and other companies.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest work_management.tests.test_payment_safety -v
"""

import unittest

from work_management.tests.test_amount_sanity import block
from work_management.tests.test_one_worker_one_day import source


class TestRepairTools(unittest.TestCase):
	def test_recalc_and_round_skip_sent_and_checked_rows(self):
		for action in ("pay_recalc_wages", "pay_round_amounts"):
			with self.subTest(action=action):
				b = block("payment", action)
				self.assertIn("payment_ref", b)
				self.assertIn("payroll_check", b)

	def test_legacy_tools_are_retired(self):
		src = source("payment")
		self.assertIn("Duplicate days are now fixed in Payment > Payroll checks.", src)
		self.assertIn("Send from the Pay workers tab", src)

	def test_orphan_repair_leaves_rows_whose_money_is_still_live(self):
		self.assertIn("asl.ref_docname = we.payment_ref AND asl.docstatus = 1", block("payment", "pay_fix_orphan_refs"))

	def test_purge_cancels_the_money_before_freeing_rows(self):
		b = block("payment", "pay_purge_queue")
		self.assertLess(b.index("adoc.cancel()"), b.index('"payment_ref": None'))
		self.assertIn("frappe.db.rollback(save_point=pq_sp)", b)


class TestSends(unittest.TestCase):
	def test_one_send_at_a_time(self):
		src = source("payment")
		self.assertEqual(src.count("GET_LOCK('wmpay-send', 60)"), 2)
		self.assertIn("RELEASE_LOCK('wmpay-send')", src)

	def test_rows_are_claimed_only_if_still_unsent(self):
		src = source("payment")
		self.assertEqual(src.count("WHERE name IN %s AND IFNULL(payment_ref, '') = ''"), 2)
		self.assertEqual(src.count("were sent by somebody else meanwhile"), 2)

	def test_suspended_and_other_companies_are_refused(self):
		src = source("payment")
		self.assertEqual(src.count('"employee is Suspended"'), 2)
		self.assertEqual(src.count("_emp.company != DEFAULT_COMPANY"), 2)


class TestPayrollHooks(unittest.TestCase):
	def test_only_unpaid_runs_become_paid_and_money_must_agree(self):
		src = source("payment")
		start = src.index("def on_salary_slip_submit(")
		body = src[start:src.index("\ndef ", start + 1)]
		self.assertIn('if state != "Unpaid":', body)
		self.assertIn('fx.kind = "slip mismatch"', body)

	def test_cancel_refuses_while_a_slip_carries_the_run(self):
		src = source("payment")
		start = src.index("def on_payment_update(")
		body = src[start:src.index("\ndef ", start + 1)]
		self.assertIn("still carries this run", body)


if __name__ == "__main__":
	unittest.main()
