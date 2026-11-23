"""Missing work in the payroll check: a farm with present-but-unrecorded task-worker
days cannot approve its part; excuses lock with the farm's approval; workers
added late for the check are shown to HR."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = (ROOT / "api" / "payment.py").read_text()
JS = (ROOT / "public" / "js" / "work-payment.js").read_text()


def between(start, end):
	i = PY.index(start)
	return PY[i:PY.index(end, i + len(start))]


class TestIssues(unittest.TestCase):
	def test_issue_classes(self):
		self.assertIn('"missing_work": ("block", "farm", "Present, no work recorded")', PY)
		self.assertIn('"added_late": ("ack", "HR", "Worker added to a crew late for this check")', PY)

	def test_missing_work_comes_from_the_shared_finder(self):
		body = between("def wmi_issues(", "return found")
		self.assertIn('frappe.call("work_management.missing_work.find"', body)

	def test_top_up_skips_missing_work(self):
		body = between("def wmi_issues(", "return found")
		i = body.index('frappe.call("work_management.missing_work.find"')
		self.assertIn("is_top_up", body[max(0, i - 400):i])

	def test_missing_work_key_is_employee_and_day(self):
		body = between("def wmi_issues(", "return found")
		self.assertIn('+ "|" +', body)

	def test_added_late_issue_reads_crew_flag(self):
		body = between("def wmi_issues(", "return found")
		self.assertIn("wae.added_for_check = %(c)s", body)
		self.assertIn('add("added_late"', body)


class TestApproval(unittest.TestCase):
	def test_farm_approve_points_to_missing_work(self):
		body = between('action == "chk_farm_approve"', 'action == "chk_send_back"')
		self.assertIn("Actuals > Missing work", body)

	def test_farm_approve_stamps_excuses(self):
		body = between('action == "chk_farm_approve"', 'action == "chk_send_back"')
		self.assertIn('frappe.call("work_management.missing_work.stamp_excuses"', body)

	def test_send_back_unstamps_excuses(self):
		body = between('action == "chk_send_back"', 'action == "chk_issues"')
		self.assertIn('frappe.call("work_management.missing_work.unstamp_excuses"', body)

	def test_cancel_unstamps_excuses(self):
		body = between('action == "chk_cancel"', 'out["error"] = "unknown action: "')
		self.assertIn('frappe.call("work_management.missing_work.unstamp_excuses"', body)

	def test_detail_returns_excused(self):
		body = between('action == "chk_detail"', 'action == "chk_fix_dup"')
		self.assertIn('out["excused"]', body)
		self.assertIn("`tabWork Missing Day Excuse`", body)


class TestScreen(unittest.TestCase):
	def test_js_links_to_missing_tab(self):
		self.assertIn("/work-actuals?tab=missing", JS)

	def test_js_shows_excused_summary(self):
		self.assertIn("d.excused", JS)
		self.assertIn("No work given", JS)


if __name__ == "__main__":
	unittest.main()
