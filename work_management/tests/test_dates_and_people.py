"""Dates and people (2026-11-12): what a submit may do, active employees,
employment dates, release and swap dates, crew edits mid-approval.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest work_management.tests.test_dates_and_people -v
"""

import types
import unittest

from work_management.tests.test_amount_sanity import block
from work_management.tests.test_one_worker_one_day import Row, source
from work_management.tests.test_payroll_check import nested


def left_err(start, last, to_date="2026-10-11", today="2026-11-12"):
	def sql(q, args=None):
		if "MIN(COALESCE(start_date" in q:
			return [(start,)]
		if "MAX(we.work_date)" in q:
			return [(last,)]
		return []
	fake = types.SimpleNamespace(
		utils=types.SimpleNamespace(today=lambda: today),
		db=types.SimpleNamespace(sql=sql,
			get_value=lambda dt, n, f=None, as_dict=False: Row(from_date="2026-09-28", to_date=to_date)
				if dt == "Work Management Assigner" else "Josephine"))
	return nested("assigner", "wmg_left_err", {"frappe": fake})


class TestReleaseDates(unittest.TestCase):
	def test_not_before_recorded_work(self):
		self.assertIn("work recorded here up to 2026-10-05",
			left_err("2026-09-28", "2026-10-05")("WMA-1", "E1", "2026-10-01"))

	def test_not_before_they_started(self):
		self.assertIn("before they started", left_err("2026-10-02", None)("WMA-1", "E1", "2026-10-01"))

	def test_not_in_the_future_or_after_the_end(self):
		self.assertIn("has not come yet", left_err("2026-09-28", None)("WMA-1", "E1", "2026-11-20"))
		self.assertIn("after the assignment ends", left_err("2026-09-28", None)("WMA-1", "E1", "2026-10-20"))

	def test_a_good_date_passes(self):
		self.assertEqual(left_err("2026-09-28", "2026-10-03")("WMA-1", "E1", "2026-10-04"), "")


class TestWhereTheRulesApply(unittest.TestCase):
	def test_release_and_swap_check_the_date(self):
		self.assertIn("wmg_left_err(nm, rw, rel_day)", block("assigner", "a_release"))
		for module in ("assigner", "actuals"):
			with self.subTest(module=module):
				b = block(module, "a_substitute")
				self.assertIn("wmg_left_err(nm, outgoing, left_date)", b)
				self.assertIn("The replacement cannot start before", b)
				self.assertIn("The replacement is not an active employee.", b)

	def test_a_submit_checks_the_plan_and_the_people(self):
		b = block("assigner", "a_submit")
		for text in ("Only an approved plan can be assigned", "That plan is closed.",
				"already has a live assignment", "Not active employees, so they cannot be put on work",
				"That assignment belongs to another plan", "if not err and planner and not sb_pending:"):
			with self.subTest(text=text):
				self.assertIn(text, b)

	def test_a_crew_changed_mid_approval_goes_back_to_the_farm_manager(self):
		b = block("assigner", "a_submit")
		self.assertIn('STAGE_STATE["assigner_farm_manager"], update_modified=False)', b)
		self.assertIn("Only the GM can change a crew waiting for the GM.", b)

	def test_add_crew_needs_active_employees(self):
		self.assertIn("Not active employees:", block("assigner", "a_add_crew"))

	def test_work_is_recorded_only_within_employment(self):
		b = block("actuals", "act_submit")
		self.assertIn("after they left the company", b)
		self.assertIn("before they joined", b)


if __name__ == "__main__":
	unittest.main()
