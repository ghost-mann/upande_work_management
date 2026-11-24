"""Every KES figure the dashboard calls pay counts what payroll counts (2026-11-24).

For 21 Oct - 20 Nov 2026 the payroll check carried KES 3,775,720 while Field
intelligence said 3,797,169, the attendance sheet left out leavers, and the
Delivery timeline counted salaried supervisors. The rule now, everywhere: pay is
confirmed work, counted in payroll, above zero, by an employee on the payable
lists in Settings (else 'Task Worker') -- the rows a farm's approval puts into a
payroll check. Work still in approval is shown on its own, never added in.

Field intelligence keeps Man-days as its labour measure and adds Paid days, the
check's worker-days.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_dashboards_count_payroll_pay -v
"""

import inspect
import textwrap
import unittest
from pathlib import Path

from work_management.api import dashboard

SRC = inspect.getsource(dashboard.wm_dashboard)
JS = (Path(__file__).resolve().parents[1] / "public" / "js" / "work-management-dashboard.js").read_text()

START = "# PAYROLL PAY (2026-11-24)"
END = "# -- end payroll pay --"


def helpers():
	lines = SRC.splitlines(True)
	first = next(i for i, l in enumerate(lines) if START in l)
	last = next(i for i, l in enumerate(lines) if END in l)
	ns = {"frappe": None}
	exec(compile(textwrap.dedent("".join(lines[first:last])), "<payroll-pay>", "exec"), ns)
	return ns


def action(name):
	i = SRC.index('action == "' + name + '"')
	j = SRC.find("\n    elif action ==", i + 1)
	return SRC[i:j if j > 0 else len(SRC)]


class TestWhoIsPaidByTheTask(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.clause = staticmethod(helpers()["wmpay_clause"])

	def test_the_payable_lists_are_ored_against_the_rows_employee(self):
		s = self.clause([("designation", ["Task Worker"]), ("employment_type", ["Casual", "Contract"])], "we")
		self.assertIn("pye.name = we.employee", s)
		self.assertIn("pye.designation IN ('Task Worker')", s)
		self.assertIn("pye.employment_type IN ('Casual', 'Contract')", s)
		self.assertIn(" OR ", s)

	def test_blank_settings_never_open_the_gate(self):
		s = self.clause([("designation", []), ("employment_type", ["", None])], "w")
		self.assertIn("pye.employment_type = 'Task Worker'", s)
		self.assertIn("pye.name = w.employee", s)

	def test_an_apostrophe_is_quoted(self):
		self.assertIn("'Pickers'' Lead'", self.clause([("designation", ["Pickers' Lead"])], "we"))

	def test_a_percent_sign_survives_the_drivers_formatting(self):
		self.assertIn("'100%% piece'", self.clause([("designation", ["100% piece"])], "we"))

	def test_the_whole_row_rule_matches_the_payroll_check(self):
		s = helpers()["wmpay_row"]("we", "ac", "EXISTS (x)")
		for part in ("ac.workflow_state = 'CONFIRMED'", "IFNULL(we.count_in_payroll, 0) = 1",
				"we.amount > 0", "EXISTS (x)"):
			self.assertIn(part, s)


class TestFieldIntelligence(unittest.TestCase):
	def test_cost_is_payroll_pay(self):
		s = action("field_intel")
		self.assertIn("wmpay_row(", s)
		self.assertIn("THEN we.amount ELSE 0 END", s)

	def test_paid_days_are_counted_beside_man_days(self):
		s = action("field_intel")
		self.assertIn("paid_days", s)
		self.assertIn('fe["paid_days"]', s)

	def test_a_paid_row_with_no_quantity_still_counts_as_pay(self):
		# the check takes amount > 0 whatever the quantity; man-days still need output
		s = action("field_intel")
		self.assertIn("(we.actual_quantity > 0 OR we.amount > 0)", s)
		self.assertIn("CASE WHEN we.actual_quantity > 0 THEN", s)

	def test_work_without_an_assignment_is_not_dropped(self):
		self.assertIn("LEFT JOIN `tabWork Management Assigner` a2", action("field_intel"))

	def test_all_time_is_payroll_pay_too(self):
		s = action("field_intel")
		i = s.index("cum_pay = {}")
		self.assertIn("WHERE \"\"\" + fi_pay", s[i:i + 900])
		self.assertIn("fi_pay = wmpay_row(", s)


class TestDeliveryTimeline(unittest.TestCase):
	def test_delivered_kes_is_payroll_pay(self):
		s = action("timeline")
		self.assertIn("wmpay_row(", s)
		self.assertIn("THEN we.amount ELSE 0 END", s)


class TestAttendanceSheet(unittest.TestCase):
	def sheet(self):
		s = action("people_board")
		return s[s.index("am_month ="):]

	def test_pay_is_confirmed_payroll_pay_and_approval_is_apart(self):
		s = self.sheet()
		self.assertIn("wmpay_row(", s)
		self.assertIn('tot["pending"]', s)
		self.assertIn('c["pend"]', s)

	def test_leavers_with_pay_in_the_range_are_listed(self):
		s = self.sheet()
		self.assertIn("e.status != 'Active'", s)

	def test_the_screen_shows_in_approval_apart(self):
		self.assertIn("in approval KES", JS)
		self.assertIn("to payroll KES", JS)
		self.assertIn('"In approval KES"', JS)


class TestTheScreen(unittest.TestCase):
	def test_field_intelligence_has_a_paid_days_column(self):
		self.assertIn(">Paid days</th>", JS)
		self.assertIn("f.paid_days", JS)


if __name__ == "__main__":
	unittest.main()
