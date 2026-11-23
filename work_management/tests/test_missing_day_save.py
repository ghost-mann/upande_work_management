"""Missing work part 2: a missing day's work is saved as its own small record
(act_submit missing_fix=1) and goes through the normal actuals approvals; a
missing-day record sent back is deleted and logged so the day reopens."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = (ROOT / "api" / "actuals.py").read_text()


def block(start, end):
	i = PY.index(start)
	return PY[i:PY.index(end, i + len(start))]


SUBMIT = block('action == "act_submit"', 'action == "od_pending"')
DETAIL = block('action == "act_detail"', 'action == "act_submit"')
REJECT = block('action == "act_reject"', 'action == "act_close_roles"')


class TestMissingDaySave(unittest.TestCase):
	def test_flag_read(self):
		self.assertIn('frappe.form_dict.get("missing_fix")', SUBMIT)

	def test_validates_open_day_and_crew(self):
		self.assertIn('frappe.call("work_management.missing_work.find"', SUBMIT)
		self.assertIn('["assignment"] != assignment', SUBMIT)

	def test_one_employee_per_record(self):
		self.assertIn("One worker per missing-day record", SUBMIT)

	def test_needs_the_right_to_send_for_approval(self):
		self.assertIn("can send a missing day for approval", SUBMIT)

	def test_never_resumes_or_waits_for_the_main_record(self):
		self.assertRegex(SUBMIT, r"if mw_fix:\s*\n\s*existing = \[\]\s*\n\s*live = \[\]")

	def test_normal_saves_ignore_missing_day_records(self):
		self.assertGreaterEqual(SUBMIT.count('"missing_work_fix": 0'), 2)

	def test_goes_straight_to_first_stage(self):
		self.assertRegex(SUBMIT, r"if mw_fix:\s*\n\s*completed = 1")

	def test_marked_as_a_missing_day_record(self):
		self.assertIn("d.missing_work_fix = 1", SUBMIT)

	def test_cap_still_applies(self):
		# the budget guard is not skipped for a missing-day record
		i = SUBMIT.index("HARD TARGET CAP")
		self.assertNotIn("mw_fix", SUBMIT[i:i + 1600])


class TestMainRecordStillCompletes(unittest.TestCase):
	def test_completion_counts_missing_day_records_on_the_same_assignment(self):
		# the plan cap counts them, so the "target reached" check must too, or the
		# main record can never reach its target and is stuck in Draft
		i = SUBMIT.index("COMPLETION GATE")
		gate = SUBMIT[i:i + 2200]
		self.assertIn("IFNULL(ac.missing_work_fix, 0) = 1", gate)


class TestCloseEarlyLeavesFixesToTheirApprovers(unittest.TestCase):
	def test_close_confirm_skips_missing_day_records_not_at_gm(self):
		body = block('elif action == "act_close_confirm"', 'elif action == "act_close_reject"')
		self.assertIn("missing_work_fix", body)


class TestGridIgnoresMissingDayRecords(unittest.TestCase):
	def test_detail_lock_and_resume_skip_them(self):
		self.assertGreaterEqual(DETAIL.count("IFNULL(missing_work_fix, 0) = 0"), 2)


class TestRejectDeletes(unittest.TestCase):
	def test_reject_deletes_fix_and_logs_day(self):
		self.assertIn("missing_work_fix", REJECT)
		self.assertIn("wmg_log_deleted(", REJECT)
		self.assertIn('frappe.delete_doc("Work Management Actuals"', REJECT)
		self.assertIn('"missing_employee"', REJECT)
		self.assertIn('out["deleted"]', REJECT)


if __name__ == "__main__":
	unittest.main()
