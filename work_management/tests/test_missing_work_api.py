"""Missing work: the Actuals tab's endpoint, excuses and payroll-check stamping."""

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "missing_work.py").read_text()

from work_management import missing_work as mw  # noqa: E402

CFG = {"farms": ["Vale", "Endebess", "Lokitela"],
	"farm_approver_role": {"Vale": "FM Vale", "Endebess": "FM Endebess", "Lokitela": "FM Lokitela"},
	"hr_head_roles": ["HOD HR"], "capabilities": {"enter_work": ["Work Clerk"]}}


def body(name):
	tree = ast.parse(SRC)
	for n in ast.walk(tree):
		if isinstance(n, ast.FunctionDef) and n.name == name:
			return ast.unparse(n)
	raise AssertionError(name + " not defined")


def action(name):
	s = body("wm_missing_work")
	i = s.index("'" + name + "'")
	j = s.find("elif action ==", i + 1)
	return s[i:j if j > 0 else len(s)]


class TestWhoMay(unittest.TestCase):
	def test_clerk_records_on_every_farm(self):
		self.assertTrue(mw.may_record(CFG, ["Work Clerk"], "Vale"))
		self.assertTrue(mw.may_record(CFG, ["Work Clerk"], "Endebess"))

	def test_fm_only_own_farm(self):
		self.assertTrue(mw.may_record(CFG, ["FM Vale"], "Vale"))
		self.assertFalse(mw.may_record(CFG, ["FM Vale"], "Endebess"))

	def test_gm_hr_and_system_manager_everywhere(self):
		for role in ("General Manager", "HOD HR", "System Manager"):
			self.assertTrue(mw.may_record(CFG, [role], "Lokitela"), role)

	def test_farm_outside_config_refused(self):
		self.assertFalse(mw.may_record(CFG, ["Work Clerk"], "Saboti"))

	def test_nobody_else(self):
		self.assertFalse(mw.may_record(CFG, ["Employee"], "Vale"))

	def test_add_late_only_fm_or_gm(self):
		self.assertTrue(mw.may_add_late(CFG, ["FM Vale"], "Vale"))
		self.assertFalse(mw.may_add_late(CFG, ["FM Vale"], "Endebess"))
		self.assertTrue(mw.may_add_late(CFG, ["General Manager"], "Endebess"))
		self.assertFalse(mw.may_add_late(CFG, ["Work Clerk"], "Vale"))
		self.assertFalse(mw.may_add_late(CFG, ["HOD HR"], "Vale"))

	def test_user_farms_narrowed_by_user_permission(self):
		self.assertEqual(mw.user_farms(CFG, ["Work Clerk"], []), ["Vale", "Endebess", "Lokitela"])
		self.assertEqual(mw.user_farms(CFG, ["Work Clerk"], ["Vale"]), ["Vale"])
		self.assertEqual(mw.user_farms(CFG, ["FM Endebess"], []), ["Endebess"])


class TestEndpoint(unittest.TestCase):
	def test_actions_exist(self):
		for a in ("mw_list", "mw_excuse", "mw_unexcuse"):
			self.assertIn("action == '" + a + "'", body("wm_missing_work"))

	def test_short_name_is_routed(self):
		# the screens call /api/method/wm_missing_work, as they do wm_actuals
		hooks = (ROOT / "hooks.py").read_text()
		self.assertIn('"wm_missing_work": "work_management.missing_work.wm_missing_work"', hooks)

	def test_whitelisted(self):
		self.assertIn("@frappe.whitelist()\ndef wm_missing_work", SRC)

	def test_excuse_checks_farm_permission(self):
		self.assertIn("may_record(", action("mw_excuse"))
		self.assertIn("may_record(", action("mw_unexcuse"))

	def test_excuse_reason_validated(self):
		s = action("mw_excuse")
		self.assertIn("REASONS", s)
		self.assertIn("'Other'", s)

	def test_excuse_only_for_a_missing_day(self):
		# you cannot excuse a day that has work, or a day that is not someone's missing day
		self.assertIn("find(", action("mw_excuse"))

	def test_stamped_excuse_cannot_change(self):
		self.assertIn("payroll_check", action("mw_excuse"))
		self.assertIn("payroll_check", action("mw_unexcuse"))

	def test_list_returns_the_screen_fields(self):
		s = action("mw_list")
		for k in ("'rows'", "'counts'", "'farms'", "'open_check'", "'can_excuse'", "'late_farms'"):
			self.assertIn(k, s)
		self.assertIn("include_excused=True", s)


class TestAssignmentOptions(unittest.TestCase):
	def test_list_returns_assignments_covering_the_dates(self):
		s = action("mw_list")
		self.assertIn("'assignments'", s)
		self.assertIn("assignment_options(", s)

	def test_options_are_assigned_with_an_active_crew(self):
		s = body("assignment_options")
		self.assertIn("workflow_state = 'Assigned'", s)
		self.assertIn("IFNULL(w2.status, 'Active') != 'Left'", s)
		self.assertIn("a.from_date <= %s AND a.to_date >= %s", s)


class TestStamping(unittest.TestCase):
	def test_unstamp_clears_only_this_check(self):
		self.assertIn("SET payroll_check = '' WHERE payroll_check = %s", body("unstamp_excuses"))

	def test_stamp_only_unstamped_rows_of_the_farm_and_dates(self):
		s = body("stamp_excuses")
		self.assertIn("IFNULL(payroll_check, '') = ''", s)
		self.assertIn("farm = %s", s)
		self.assertIn("work_date BETWEEN %s AND %s", s)

	def test_open_check_is_farm_review_not_top_up_farm_not_approved(self):
		s = body("open_check")
		self.assertIn("'Farm Review'", s)
		self.assertIn("is_top_up", s)
		self.assertIn("'Approved'", s)


if __name__ == "__main__":
	unittest.main()
