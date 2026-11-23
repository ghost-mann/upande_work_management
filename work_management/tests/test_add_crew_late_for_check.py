"""Adding a worker to a crew late, inside an open payroll check (2026-11-23).

A present task worker who was on no crew can only be paid once they are on one.
Most such days in a payroll check are older than the backdate limit, which only
the GM may pass. Inside an open check the farm's own farm manager (or the GM) may
add them for those days without the GM, giving a reason; it is logged on the
assignment and flagged to HR in the check (added_for_check)."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = (ROOT / "api" / "assigner.py").read_text()


def add_crew():
	i = PY.index('action == "a_add_crew"')
	return PY[i:PY.index('action == "a_release"', i)]


class TestAddCrewLate(unittest.TestCase):
	def test_until_sets_left_date(self):
		s = add_crew()
		self.assertIn('frappe.form_dict.get("until")', s)
		self.assertIn('child.status = "Left" if add_until else "Active"', s)
		self.assertIn("child.left_date = add_until", s)

	def test_until_inside_the_assignment(self):
		s = add_crew()
		self.assertIn("str(add_until) < str(add_from)", s)
		self.assertIn("str(add_until) > str(d.to_date)", s)

	def test_for_check_needs_open_check_and_reason(self):
		s = add_crew()
		self.assertIn('frappe.form_dict.get("for_check")', s)
		self.assertIn('frappe.call("work_management.missing_work.open_check"', s)
		self.assertIn('frappe.form_dict.get("backdate_reason")', s)
		self.assertIn('add_oc["period_to"]', s)

	def test_for_check_only_fm_or_gm(self):
		s = add_crew()
		self.assertIn("WMG_GM or (str(d.farm).strip() in wmg_fm)", s)

	def test_backdate_rule_still_applies_without_for_check(self):
		s = add_crew()
		self.assertIn("err = wmg_backdate_err(add_from) or None", s)
		i = s.index("err = wmg_backdate_err(add_from) or None")
		self.assertIn("if not err and add_for:", s[max(0, i - 2500):i])
		self.assertIn("elif not err:\n", s[max(0, i - 60):i])

	def test_flag_and_comment_logged(self):
		s = add_crew()
		self.assertIn("child.added_for_check = add_for", s)
		self.assertIn('"Added late for payroll check "', s)

	def test_busy_check_uses_the_short_span(self):
		s = add_crew()
		self.assertIn("add_until or d.to_date", s)


if __name__ == "__main__":
	unittest.main()
