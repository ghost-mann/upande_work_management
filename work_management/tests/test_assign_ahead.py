"""Assign the day before (2026-11-26): the cut-off rule, reasons and the KPI summary.

Crews should know their job before they arrive, so an assignment for day D is
made before the cut-off (18:00) on D-1. Later is allowed with a reason.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_assign_ahead -v
"""

import ast
import json
import types
import unittest
from pathlib import Path
from unittest import mock

from work_management import assign_ahead as aa

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "assign_ahead.py").read_text()


def body(name):
	for n in ast.walk(ast.parse(SRC)):
		if isinstance(n, ast.FunctionDef) and n.name == name:
			return ast.unparse(n)
	raise AssertionError(name)


def row(asg, created, start="2026-11-27", tl="tl@x", saver="clerk@x", reason=None, approved_at=None, **kw):
	r = {"asg": asg, "start": start, "created": created, "approved_at": approved_at, "tl": tl, "tl_name": tl.upper(),
		"saver": saver, "saver_name": saver.upper(), "reason": reason, "note": None, "farm": "Vale",
		"task": "Weeding", "block": "B1"}
	r.update(kw)
	return r


class TestDeadline(unittest.TestCase):
	def test_day_before_at_cutoff(self):
		self.assertEqual(aa.deadline("2026-11-27"), "2026-11-26 18:00:00")

	def test_custom_cutoff(self):
		self.assertEqual(aa.deadline("2026-11-27", "16:30"), "2026-11-26 16:30:00")

	def test_month_boundary(self):
		self.assertEqual(aa.deadline("2026-12-01"), "2026-11-30 18:00:00")

	def test_no_start(self):
		self.assertIsNone(aa.deadline(None))
		self.assertIsNone(aa.deadline(""))


class TestIsLate(unittest.TestCase):
	def test_before_cutoff_is_on_time(self):
		self.assertFalse(aa.is_late("2026-11-26 17:59:00", "2026-11-27"))

	def test_after_cutoff_is_late(self):
		self.assertTrue(aa.is_late("2026-11-26 18:01:00", "2026-11-27"))

	def test_on_the_day_is_late(self):
		self.assertTrue(aa.is_late("2026-11-27 06:30:00", "2026-11-27"))

	def test_days_ahead_is_on_time(self):
		self.assertFalse(aa.is_late("2026-11-20 09:00:00.123456", "2026-11-27"))

	def test_no_start_is_not_late(self):
		self.assertFalse(aa.is_late("2026-11-27 06:30:00", None))


class TestReasonErr(unittest.TestCase):
	def test_reasons_are_the_agreed_copy(self):
		self.assertEqual(aa.REASONS, ["Replacing absent worker", "Weather", "Urgent work", "Other"])
		self.assertEqual(aa.PLAN_LATE, "Plan approved late")

	def test_ok(self):
		self.assertEqual(aa.reason_err("Weather", ""), "")

	def test_empty(self):
		self.assertIn("reason", aa.reason_err("", "").lower())

	def test_unknown(self):
		self.assertTrue(aa.reason_err("Because", ""))

	def test_other_needs_note(self):
		self.assertTrue(aa.reason_err("Other", "  "))
		self.assertEqual(aa.reason_err("Other", "tractor broke"), "")


class TestCheck(unittest.TestCase):
	def fake(self, on=1, cutoff="18:00:00", plan=None):
		def single(dt, field):
			return {"assign_day_before": on, "assign_cutoff_time": cutoff}.get(field)
		db = types.SimpleNamespace(get_single_value=single,
			get_value=lambda dt, name, fields, as_dict=False: types.SimpleNamespace(**(plan or {})) if plan is not None else None)
		return mock.patch.object(aa, "frappe", types.SimpleNamespace(db=db, utils=aa.frappe.utils))

	def test_switch_off_is_never_late(self):
		with self.fake(on=0):
			self.assertEqual(aa.check("2026-11-27", now="2026-11-27 10:00:00")["late"], 0)

	def test_late_when_on(self):
		with self.fake():
			out = aa.check("2026-11-27", now="2026-11-27 10:00:00")
		self.assertEqual(out["late"], 1)
		self.assertEqual(out["deadline"], "2026-11-26 18:00:00")
		self.assertIsNone(out["auto_reason"])

	def test_on_time(self):
		with self.fake():
			self.assertEqual(aa.check("2026-11-27", now="2026-11-26 12:00:00")["late"], 0)

	def test_plan_approved_late_fills_the_reason(self):
		with self.fake(plan={"custom_approved_at": "2026-11-26 19:30:00", "approval_date": "2026-11-26"}):
			out = aa.check("2026-11-27", planner="PL-1", now="2026-11-27 07:00:00")
		self.assertEqual(out["late"], 1)
		self.assertEqual(out["auto_reason"], "Plan approved late")

	def test_plan_approved_in_time_asks(self):
		with self.fake(plan={"custom_approved_at": "2026-11-25 10:00:00", "approval_date": "2026-11-25"}):
			self.assertIsNone(aa.check("2026-11-27", planner="PL-1", now="2026-11-27 07:00:00")["auto_reason"])

	def test_plan_approval_date_only(self):
		with self.fake(plan={"custom_approved_at": None, "approval_date": "2026-11-27"}):
			self.assertEqual(aa.check("2026-11-27", planner="PL-1", now="2026-11-27 07:00:00")["auto_reason"],
				"Plan approved late")

	def test_no_start_is_not_late(self):
		with self.fake():
			self.assertEqual(aa.check(None, now="2026-11-27 07:00:00")["late"], 0)

	def test_whitelisted(self):
		self.assertIn("frappe.whitelist", SRC.split("def check(")[0].rsplit("\n\n", 1)[-1])


class TestSummarise(unittest.TestCase):
	def setUp(self):
		self.rows = [
			row("A1", "2026-11-25 10:00:00"),                                   # on time
			row("A2", "2026-11-27 07:00:00", reason="Weather"),                 # late
			row("A3", "2026-11-27 08:00:00"),                                   # late, history: no reason
			row("A4", "2026-11-27 08:00:00", tl="tl2@x", saver="clerk2@x",
				reason="Plan approved late", approved_at="2026-11-26 20:00:00"),  # plan late
			row("A5", "2026-11-27 09:00:00", tl="tl2@x", reason="Weather"),     # late
		]
		self.out = aa.summarise(self.rows, "18:00:00")

	def test_by_leader(self):
		by = {r["key"]: r for r in self.out["by_leader"]}
		self.assertEqual((by["tl@x"]["total"], by["tl@x"]["late"], by["tl@x"]["plan_late"]), (3, 2, 0))
		self.assertEqual((by["tl2@x"]["total"], by["tl2@x"]["late"], by["tl2@x"]["plan_late"]), (2, 1, 1))
		self.assertEqual(by["tl@x"]["pct_late"], 66.7)
		self.assertEqual(by["tl2@x"]["pct_late"], 50.0)
		self.assertEqual(by["tl@x"]["name"], "TL@X")

	def test_ranked_by_late(self):
		self.assertEqual([r["key"] for r in self.out["by_leader"]], ["tl@x", "tl2@x"])

	def test_by_saver(self):
		by = {r["key"]: r for r in self.out["by_saver"]}
		self.assertEqual((by["clerk@x"]["total"], by["clerk@x"]["late"]), (4, 3))
		self.assertEqual(by["clerk2@x"]["plan_late"], 1)

	def test_top_reason(self):
		by = {r["key"]: r for r in self.out["by_leader"]}
		self.assertIn(by["tl@x"]["top_reason"], ("Weather", "No reason given"))
		self.assertEqual(by["tl2@x"]["top_reason"], "Weather")

	def test_late_rows(self):
		late = {r["asg"]: r for r in self.out["late_rows"]}
		self.assertEqual(sorted(late), ["A2", "A3", "A4", "A5"])
		self.assertEqual(late["A3"]["reason"], "No reason given")
		self.assertTrue(late["A4"]["plan_late"])
		self.assertEqual(late["A2"]["deadline"], "2026-11-26 18:00:00")

	def test_no_leader(self):
		out = aa.summarise([row("A9", "2026-11-27 07:00:00", tl="", tl_name="")], "18:00:00")
		self.assertEqual(out["by_leader"][0]["name"], "No team leader")


class TestDayStatus(unittest.TestCase):
	def test_precedence(self):
		self.assertEqual(aa.day_status("07:01", "Present", "Annual Leave"), "Leave")
		self.assertEqual(aa.day_status(None, "Absent", None), "Absent")
		self.assertEqual(aa.day_status("07:01", "Absent", None), "Present")
		self.assertEqual(aa.day_status(None, "Half Day", None), "Present")
		self.assertEqual(aa.day_status(None, None, None), "Not scanned")


class TestUnassignedTomorrow(unittest.TestCase):
	def test_only_free_open_plans_for_the_day(self):
		plans = [
			{"name": "P1", "farm": "Vale", "from_date": "2026-11-27", "custom_close_state": ""},
			{"name": "P2", "farm": "Vale", "from_date": "2026-11-27", "custom_close_state": ""},
			{"name": "P3", "farm": "Vale", "from_date": "2026-11-28", "custom_close_state": ""},
			{"name": "P4", "farm": "Saboti", "from_date": "2026-11-27", "custom_close_state": "Closed"},
		]
		out = aa.unassigned_tomorrow(plans, {"P2"}, "2026-11-27")
		self.assertEqual([p["name"] for p in out], ["P1"])


class TestReminder(unittest.TestCase):
	def test_gated_on_setting(self):
		self.assertIn("assign_reminder", body("send_reminder")[:400])

	def test_sender_and_escaping(self):
		self.assertIn('SENDER = "Kaitet Work Management <notifications@karenroses.com>"', SRC)
		self.assertIn("sender=SENDER", body("send_reminder"))
		self.assertIn("escape_html", body("render_reminder"))

	def test_goes_to_assigner_fms_and_notify(self):
		s = body("send_reminder")
		self.assertIn("Assigner: Farm Manager", s)
		self.assertIn("assign_reminder_notify", s)

	def test_render_takes_numbers(self):
		html = aa.render_reminder({"Vale": [{"name": "P1", "task_label": "Weeding <b>", "block_section": "B1",
			"people_per_day": 20, "tl_name": "Jane"}]}, "2026-11-27", "http://x/work-assigner")
		self.assertIn(">20<", html)
		self.assertIn("Weeding &lt;b&gt;", html)

	def test_hook_registered(self):
		hooks = (ROOT / "hooks.py").read_text()
		self.assertIn('"0 16 * * *": [', hooks)
		self.assertIn('"work_management.assign_ahead.send_reminder"', hooks)


class TestFields(unittest.TestCase):
	def fields(self, dt):
		path = ROOT / "work_management" / "doctype" / dt / (dt + ".json")
		d = json.loads(path.read_text())
		return {f["fieldname"]: f for f in d["fields"]}, d["field_order"]

	def test_settings(self):
		f, order = self.fields("work_management_settings")
		for name in ("assign_day_before", "assign_cutoff_time", "assign_reminder", "assign_reminder_notify"):
			self.assertIn(name, f)
			self.assertIn(name, order)
		self.assertEqual(f["assign_day_before"]["default"], "0")
		self.assertEqual(f["assign_cutoff_time"]["fieldtype"], "Time")
		self.assertEqual(f["assign_cutoff_time"]["default"], "18:00:00")
		self.assertEqual(f["assign_reminder"]["default"], "0")

	def test_cutoff_seeded_on_running_sites(self):
		self.assertIn("work_management.patches.v1_0.seed_assign_cutoff_time", (ROOT / "patches.txt").read_text())
		self.assertIn('"18:00:00"', (ROOT / "patches" / "v1_0" / "seed_assign_cutoff_time.py").read_text())

	def test_assigner(self):
		f, order = self.fields("work_management_assigner")
		for name in ("late_assignment", "late_reason", "late_note"):
			self.assertIn(name, f)
			self.assertIn(name, order)
			self.assertEqual(f[name].get("read_only"), 1)


if __name__ == "__main__":
	unittest.main()
