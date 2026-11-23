"""Missing work part 2: "no work" reasons are approved farm manager -> HR -> GM
(following the Settings chain for Actuals), strictly by different people; the
Waiting list; asking HR to correct an Absent day; the grid endpoint."""

import ast
import unittest
from pathlib import Path

from work_management import missing_work as mw

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "missing_work.py").read_text()

ROWS = [
	{"key": "actuals_submit", "state": "Draft", "next_state": "Pending Farm Manager", "role": "Work Entry", "on": 1},
	{"key": "actuals_farm_manager", "state": "Pending Farm Manager", "next_state": "Pending HR Head", "role": "Farm Manager", "on": 1},
	{"key": "actuals_hr_head", "state": "Pending HR Head", "next_state": "Pending GM", "role": "HOD HR", "on": 1},
	{"key": "actuals_gm", "state": "Pending GM", "next_state": "CONFIRMED", "role": "General Manager", "on": 1},
]
CFG = {"farms": ["Vale", "Endebess"], "farm_approver_role": {"Vale": "Farm Manager Vale", "Endebess": "Farm Manager Endebess"},
	"hr_head_roles": ["HOD HR"], "capabilities": {"enter_work": ["Work Entry"]}, "stage_rows": ROWS}


def action(name):
	tree = ast.parse(SRC)
	fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "wm_missing_work"][0]
	s = ast.unparse(fn)
	i = s.index("'" + name + "'")
	j = s.find("\n    elif action ==", i + 1)
	return s[i:j if j > 0 else len(s)]


class TestChain(unittest.TestCase):
	def test_full_chain(self):
		self.assertEqual(mw.reason_chain(ROWS), ["Pending Farm Manager", "Pending HR", "Pending GM"])

	def test_chain_with_hr_off(self):
		rows = [dict(r, on=0) if r["key"] == "actuals_hr_head" else r for r in ROWS]
		self.assertEqual(mw.reason_chain(rows), ["Pending Farm Manager", "Pending GM"])

	def test_next_status(self):
		chain = mw.reason_chain(ROWS)
		self.assertEqual(mw.next_status("Pending Farm Manager", chain), "Pending HR")
		self.assertEqual(mw.next_status("Pending HR", chain), "Pending GM")
		self.assertEqual(mw.next_status("Pending GM", chain), "Approved")

	def test_next_status_skips_a_step_switched_off(self):
		chain = ["Pending Farm Manager", "Pending GM"]
		self.assertEqual(mw.next_status("Pending Farm Manager", chain), "Pending GM")


class TestChainChangesMidway(unittest.TestCase):
	def test_a_reason_at_a_step_switched_off_goes_on_to_the_next_step(self):
		# HR switched off while reasons sit with HR: approving moves them to the GM,
		# never straight to Approved
		self.assertEqual(mw.next_status("Pending HR", ["Pending Farm Manager", "Pending GM"]), "Pending GM")
		self.assertEqual(mw.next_status("Pending Farm Manager", ["Pending GM"]), "Pending GM")
		self.assertEqual(mw.next_status("Pending GM", ["Pending Farm Manager"]), "Approved")


class TestStandIns(unittest.TestCase):
	SI = [{"stage": "actuals_hr", "user": "standin@x", "farm": None},
		{"stage": "actuals_fm", "user": "vale-si@x", "farm": "Vale"}]

	def test_a_listed_stand_in_may_take_the_step(self):
		self.assertTrue(mw.may_step("Pending HR", [], "Vale", CFG, user="standin@x", stand_ins=self.SI))
		self.assertTrue(mw.may_step("Pending Farm Manager", [], "Vale", CFG, user="vale-si@x", stand_ins=self.SI))

	def test_a_stand_in_only_for_their_step_and_farm(self):
		self.assertFalse(mw.may_step("Pending GM", [], "Vale", CFG, user="standin@x", stand_ins=self.SI))
		self.assertFalse(mw.may_step("Pending Farm Manager", [], "Endebess", CFG, user="vale-si@x", stand_ins=self.SI))


class TestWhoMayStep(unittest.TestCase):
	def test_farm_manager_step(self):
		self.assertTrue(mw.may_step("Pending Farm Manager", ["Farm Manager Vale"], "Vale", CFG))
		self.assertFalse(mw.may_step("Pending Farm Manager", ["Farm Manager Vale"], "Endebess", CFG))
		self.assertTrue(mw.may_step("Pending Farm Manager", ["General Manager"], "Endebess", CFG))
		self.assertFalse(mw.may_step("Pending Farm Manager", ["HOD HR"], "Vale", CFG))

	def test_hr_step(self):
		self.assertTrue(mw.may_step("Pending HR", ["HOD HR"], "Vale", CFG))
		self.assertFalse(mw.may_step("Pending HR", ["General Manager"], "Vale", CFG))
		self.assertFalse(mw.may_step("Pending HR", ["Farm Manager Vale"], "Vale", CFG))

	def test_gm_step(self):
		self.assertTrue(mw.may_step("Pending GM", ["General Manager"], "Vale", CFG))
		self.assertFalse(mw.may_step("Pending GM", ["HOD HR"], "Vale", CFG))

	def test_system_manager_any_step(self):
		for st in ("Pending Farm Manager", "Pending HR", "Pending GM"):
			self.assertTrue(mw.may_step(st, ["System Manager"], "Vale", CFG), st)

	def test_nothing_to_do_on_final_states(self):
		for st in ("Approved", "Sent back"):
			self.assertFalse(mw.may_step(st, ["System Manager"], "Vale", CFG), st)


class TestTwoPeople(unittest.TestCase):
	EX = {"marked_by": "clerk@x", "fm_by": "fm@x", "hr_by": "hr@x", "status": "Pending GM"}

	def test_cannot_approve_own_reason(self):
		self.assertIn("marked", mw.two_people_err(dict(self.EX, status="Pending Farm Manager"), "clerk@x"))

	def test_hr_cannot_also_take_gm(self):
		self.assertIn("HR step", mw.two_people_err(self.EX, "hr@x"))

	def test_nobody_takes_two_steps_on_one_reason(self):
		# e.g. the GM took the farm manager step, HR is switched off, and the GM is
		# asked again at the GM step
		ex = {"marked_by": "clerk@x", "fm_by": "gm@x", "hr_by": None, "status": "Pending GM"}
		self.assertIn("already took a step", mw.two_people_err(ex, "gm@x"))
		ex = {"marked_by": "clerk@x", "fm_by": "sm@x", "hr_by": None, "status": "Pending HR"}
		self.assertIn("already took a step", mw.two_people_err(ex, "sm@x"))

	def test_someone_else_is_fine(self):
		self.assertEqual(mw.two_people_err(self.EX, "gm@x"), "")


class TestActions(unittest.TestCase):
	def test_actions_exist(self):
		for a in ("mw_approve", "mw_send_back", "mw_waiting", "mw_ask_hr", "mw_grid"):
			self.assertIn("action == '" + a + "'", SRC.replace('"', "'"))

	def test_stand_ins_are_read_for_approve_and_waiting(self):
		self.assertIn("reason_stand_ins(", action("mw_approve"))
		self.assertIn("reason_stand_ins(", action("mw_waiting"))

	def test_approve_is_strict_and_checks_the_step(self):
		s = action("mw_approve")
		self.assertIn("may_step(", s)
		self.assertIn("two_people_err(", s)
		self.assertIn("next_status(", s)

	def test_send_back_needs_a_reason(self):
		s = action("mw_send_back")
		self.assertIn("may_step(", s)
		self.assertIn("Say why", s)
		self.assertIn("'Sent back'", s)

	def test_remarking_resets_the_status(self):
		s = action("mw_excuse")
		self.assertIn("'status': chain[0]", s)
		self.assertIn("'sent_back_by': None", s)

	def test_an_approved_or_mid_chain_reason_cannot_be_remarked(self):
		self.assertIn("already approved", action("mw_excuse"))

	def test_ask_hr_once(self):
		s = action("mw_ask_hr")
		self.assertIn("`tabAttendance Request`", s)
		self.assertIn("already asked", s)
		self.assertIn("'On Duty'", s)
		self.assertIn("may_record(", s)

	def test_ask_hr_refuses_a_leaver_plainly(self):
		# ERPNext refuses an Attendance Request for an inactive employee with an error
		# page; say so in words instead
		s = action("mw_ask_hr")
		self.assertIn("'status'", s)
		self.assertIn("no longer active", s)

	def test_ask_hr_reports_a_refused_request_in_words(self):
		s = action("mw_ask_hr")
		self.assertIn("try:", s)
		self.assertIn("could not be raised", s)
		self.assertIn("log_error", s)

	def test_waiting_lists_work_and_reasons_not_final(self):
		s = action("mw_waiting")
		self.assertIn("missing_work_fix = 1", s)
		self.assertIn("workflow_state != 'CONFIRMED'", s)
		self.assertIn("status LIKE 'Pending%%'", s)
		self.assertIn("'your_turn'", s)

	def test_grid_endpoint(self):
		s = action("mw_grid")
		self.assertIn("grid(", s)
		for k in ("'farm_counts'", "'details'", "'open_check'", "'assignments'", "'late_farms'", "'reasons'"):
			self.assertIn(k, s)


if __name__ == "__main__":
	unittest.main()
