"""Missing work: the 07:30 email to team leaders, farm managers and the GM/HR."""

import ast
import unittest
from pathlib import Path

from work_management import missing_work as mw

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "missing_work.py").read_text()

STAND = [{"team_leader": "tl@x", "stand_in": "si@x", "from_date": "2026-11-10", "to_date": "2026-11-12",
	"master_plan": "MP-1"}]


def row(emp, day, farm, tl=None, mp="MP-1"):
	crews = [{"assignment": "ASG-1", "farm": farm, "task_name": "Weeding", "block": "B1", "planner": "PL-1",
		"team_leader": tl, "master_plan": mp}] if tl is not None else []
	return {"employee": emp, "day": day, "farm": farm, "crews": crews, "excuse": None}


def body(name):
	for n in ast.walk(ast.parse(SRC)):
		if isinstance(n, ast.FunctionDef) and n.name == name:
			return ast.unparse(n)
	raise AssertionError(name)


class TestLeader(unittest.TestCase):
	def test_stand_in_wins_on_its_dates(self):
		self.assertEqual(mw.leader_for("tl@x", "MP-1", "2026-11-11", STAND), "si@x")

	def test_leader_outside_stand_in_dates(self):
		self.assertEqual(mw.leader_for("tl@x", "MP-1", "2026-11-13", STAND), "tl@x")

	def test_stand_in_of_another_plan_ignored(self):
		self.assertEqual(mw.leader_for("tl@x", "MP-2", "2026-11-11", STAND), "tl@x")


class TestRecipients(unittest.TestCase):
	def setUp(self):
		self.emails = {"tl@x": "tl@x", "fmv@x": "fmv@x"}
		self.fms = {"Vale": ["fmv@x"], "Endebess": ["fme@x"]}

	def test_on_crew_goes_to_leader_and_fm(self):
		out = mw.recipients([row("E1", "2026-11-13", "Vale", "tl@x")], [], self.emails, self.fms, [])
		self.assertEqual(sorted(out), ["fmv@x", "tl@x"])
		self.assertFalse(out["tl@x"]["all_farms"])

	def test_leader_without_login_falls_to_fm(self):
		out = mw.recipients([row("E1", "2026-11-13", "Vale", "EMP-0042")], [], self.emails, self.fms, [])
		self.assertEqual(sorted(out), ["fmv@x"])

	def test_no_crew_goes_to_fm_only(self):
		out = mw.recipients([row("E1", "2026-11-13", "Endebess")], [], self.emails, self.fms, [])
		self.assertEqual(sorted(out), ["fme@x"])

	def test_notify_gets_all_farms(self):
		rows = [row("E1", "2026-11-13", "Vale", "tl@x"), row("E2", "2026-11-13", "Endebess")]
		out = mw.recipients(rows, [], self.emails, self.fms, ["gm@x", "hr@x"])
		self.assertTrue(out["gm@x"]["all_farms"])
		self.assertEqual(len(out["gm@x"]["rows"]), 2)
		self.assertEqual(len(out["hr@x"]["rows"]), 2)

	def test_no_rows_no_email(self):
		self.assertEqual(mw.recipients([], [], self.emails, self.fms, ["gm@x"]), {})

	def test_a_person_gets_each_row_once(self):
		out = mw.recipients([row("E1", "2026-11-13", "Vale", "fmv@x")], [], self.emails, self.fms, [])
		self.assertEqual(len(out["fmv@x"]["rows"]), 1)

	def test_notify_parsing(self):
		self.assertEqual(mw.split_emails("gm@x, hr@x\nother@x,,"), ["gm@x", "hr@x", "other@x"])


class TestSend(unittest.TestCase):
	def test_gated_on_setting(self):
		self.assertIn("missing_work_reminder", body("send_reminders")[:600])

	def test_window_is_yesterday_back_seven_days(self):
		s = body("send_reminders")
		self.assertIn("add_days(today, -1)", s)
		self.assertIn("add_days(today, -7)", s)

	def test_sender(self):
		self.assertIn('SENDER = "Kaitet Work Management <notifications@karenroses.com>"', SRC)
		self.assertIn("sender=SENDER", body("send_reminders"))
		self.assertIn("add_css=False", body("send_reminders"))

	def test_links_to_the_tab(self):
		self.assertIn("/work-actuals?tab=missing", SRC)

	def test_hook_registered(self):
		hooks = (ROOT / "hooks.py").read_text()
		self.assertIn('"30 7 * * *": [', hooks)
		self.assertIn('"work_management.missing_work.send_reminders"', hooks)

	def test_email_escapes_names(self):
		self.assertIn("escape_html", body("render_email"))


if __name__ == "__main__":
	unittest.main()
