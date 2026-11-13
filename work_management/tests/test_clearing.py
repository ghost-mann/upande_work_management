"""Clearing every issue in a payroll check (2026-11-12): the issue classes and
owners, acknowledgements tied to the row as it is, the stage gates, duplicate
groups and the duplicate detail view.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest work_management.tests.test_clearing -v
"""

import types
import unittest

from work_management.tests.test_amount_sanity import block
from work_management.tests.test_one_worker_one_day import source
from work_management.tests.test_payroll_check import defined, nested


class TestTheIssueTable(unittest.TestCase):
	def test_every_kind_has_its_class_and_owner(self):
		src = defined("payment", "wmi_issues")
		table = source("payment")
		want = {"qty_outlier_hard": ("block", "farm"), "rate_mismatch": ("block", "HR"),
			"left_but_earning": ("block", "HR"), "off_crew": ("ack", "HR"),
			"qty_outlier": ("ack", "farm"), "ghost_days": ("ack", "farm"),
			"leave_paid": ("ack", "farm"), "off_paid": ("ack", "farm"), "late_entry": ("ack", "farm"),
			"approval_gap": ("ack", "GM"), "self_approved": ("ack", "GM"), "backdated": ("ack", "GM")}
		for code, (cls, owner) in want.items():
			with self.subTest(code=code):
				self.assertIn('"' + code + '": ("' + cls + '", "' + owner + '"', table)
				self.assertIn('add("' + code + '"', src)

	def test_only_unpaid_unsent_confirmed_rows_are_judged(self):
		src = defined("payment", "wmi_issues")
		for clause in ("ac.workflow_state = 'CONFIRMED'", "IFNULL(we.paid, 0) = 0", "IFNULL(we.payment_ref, '') = ''"):
			with self.subTest(clause=clause):
				self.assertIn(clause, src)


class TestAcknowledgements(unittest.TestCase):
	def test_the_fingerprint_changes_with_the_row(self):
		fn = nested("payment", "wmi_print", {"frappe": types.SimpleNamespace(
			utils=types.SimpleNamespace(flt=lambda v: float(v or 0)))})
		self.assertEqual(fn(8, 387, "2026-10-30", "400314"), fn(8.0, 387.0, "2026-10-30", "400314"))
		self.assertNotEqual(fn(8, 387, "2026-10-30", "400314"), fn(80, 3870, "2026-10-30", "400314"))

	def test_an_ack_counts_only_while_the_fingerprint_matches(self):
		self.assertIn("ok = 1 if (ak and ak.row_hash == fprint) else 0", defined("payment", "wmi_issues"))

	def test_only_ack_kinds_are_acknowledged_by_their_owner(self):
		b = block("payment", "chk_ack")
		self.assertIn('WMI_CLASS[ak_code][0] != "ack"', b)
		self.assertIn("wmi_may(ak_now[kk][\"owner\"])", b)

	def test_fixes_are_limited_to_their_kinds(self):
		b = block("payment", "chk_fix_row")
		self.assertIn('"recompute": ("rate_mismatch",)', b)
		self.assertIn("is already approved in this check; send it back first.", b)


class TestTheGates(unittest.TestCase):
	def test_a_farm_waits_for_its_own_issues(self):
		self.assertIn("oi = wmi_open(wmi_issues(pc, af), [af])", block("payment", "chk_farm_approve"))

	def test_hr_waits_for_farm_and_hr_issues_and_the_gm_for_its_own(self):
		b = block("payment", "chk_hr_approve")
		self.assertIn('[f.farm for f in pc.farms] + ["HR"] + ([] if is_hr_step else ["GM"])', b)


class TestDuplicates(unittest.TestCase):
	def test_groups_by_the_assignments_behind_them(self):
		b = block("payment", "chk_dup_groups")
		self.assertIn('" + ".join(asgs)', b)

	def test_a_group_fix_never_zeroes_paid_or_sent_copies(self):
		b = block("payment", "chk_dup_group_fix")
		self.assertIn("not cx.payment_ref and not frappe.utils.cint(cx.paid)", b)

	def test_the_detail_view_carries_everything_for_judgment(self):
		b = block("payment", "chk_dup_detail")
		for key in ('"asg_created"', '"entered_at"', '"fm"', '"hr"', '"gm"', '"team_leader"', '"window"',
				'"plan_after_zero"', '"pay_basis"', '"scans"', '"attendance"', 'out["around"]', '"backdated"',
				'"self_approved"'):
			with self.subTest(key=key):
				self.assertIn(key, b)

	def test_keep_one_copy(self):
		self.assertIn('krow = frappe.form_dict.get("keep_row")', block("payment", "chk_fix_dup"))


if __name__ == "__main__":
	unittest.main()


class TestFinalReviewFixes(unittest.TestCase):
	def test_record_acks_are_tied_to_who_approved(self):
		self.assertIn("def wmi_doc_print(total, entered, fm, hr, gm):", source("payment"))

	def test_the_self_approver_cannot_acknowledge_it(self):
		self.assertIn("so somebody else must acknowledge it", block("payment", "chk_ack"))

	def test_zeroing_only_while_still_unsent(self):
		body = defined("payment", "wmpc_zero")
		self.assertIn("WHERE name = %s AND IFNULL(payment_ref, '') = '' AND IFNULL(paid, 0) = 0", body)

	def test_a_sent_copy_is_always_the_one_kept(self):
		self.assertIn("keepers = sent", block("payment", "chk_dup_group_fix"))
		self.assertIn("so that is the one kept", block("payment", "chk_fix_dup"))

	def test_copies_held_by_another_check_are_left_alone(self):
		self.assertIn('cx.payroll_check in ("", pc.name)', block("payment", "chk_dup_group_fix"))

	def test_ack_and_fix_rejudge_only_their_rows(self):
		self.assertIn("wmi_issues(pc, None, ak_keys)", block("payment", "chk_ack"))
		self.assertIn("wmi_issues(pc, None, [fr_row])", block("payment", "chk_fix_row"))

	def test_rate_periods_are_not_mismatches(self):
		self.assertIn("prate", defined("payment", "wmi_issues"))

	def test_a_leavers_last_week_is_paid_on_the_relieving_date(self):
		src = source("payment")
		self.assertEqual(src.count("_pay_on = wm_emp.relieving_date") + src.count("_pay_on = bw_emp.relieving_date"), 2)
