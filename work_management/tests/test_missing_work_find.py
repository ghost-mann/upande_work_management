"""Missing work: which present task-worker days have no actuals, and whose farm they are."""

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "missing_work.py").read_text()

from work_management import missing_work as mw  # noqa: E402

A = {"assignment": "ASG-1", "farm": "Vale", "task_name": "Weeding", "block": "B1",
	"planner": "PL-1", "team_leader": "tl@x", "master_plan": "MP-1"}
B = {"assignment": "ASG-2", "farm": "Lokitela", "task_name": "Pruning", "block": "L2",
	"planner": "PL-2", "team_leader": "tl2@x", "master_plan": "MP-2"}


class TestClassify(unittest.TestCase):
	def run_it(self, presence, actuals=(), excuses=None, crews=None, home=None):
		return mw.classify(presence, set(actuals), excuses or {}, crews or {}, home or {"E1": "Endebess"})

	def test_no_actuals_is_missing(self):
		out = self.run_it([("E1", "2026-11-03")])
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["employee"], "E1")
		self.assertEqual(out[0]["day"], "2026-11-03")
		self.assertIsNone(out[0]["excuse"])

	def test_actuals_clear_it(self):
		self.assertEqual(self.run_it([("E1", "2026-11-03")], actuals=[("E1", "2026-11-03")]), [])

	def test_actuals_on_any_crew_clear_it(self):
		crews = {("E1", "2026-11-03"): [A, B]}
		self.assertEqual(self.run_it([("E1", "2026-11-03")], actuals=[("E1", "2026-11-03")], crews=crews), [])

	def test_farm_is_crew_farm_else_home(self):
		crews = {("E1", "2026-11-03"): [A]}
		out = self.run_it([("E1", "2026-11-03"), ("E1", "2026-11-04")], crews=crews)
		by_day = {r["day"]: r for r in out}
		self.assertEqual(by_day["2026-11-03"]["farm"], "Vale")
		self.assertEqual(by_day["2026-11-03"]["crews"], [A])
		self.assertEqual(by_day["2026-11-04"]["farm"], "Endebess")
		self.assertEqual(by_day["2026-11-04"]["crews"], [])

	def test_excused_day_carries_excuse(self):
		ex = {"name": "x1", "reason": "Rain / weather", "note": "", "marked_by": "fm@x", "payroll_check": ""}
		out = self.run_it([("E1", "2026-11-03")], excuses={("E1", "2026-11-03"): ex})
		self.assertEqual(out[0]["excuse"], ex)

	def test_actuals_beat_excuse(self):
		ex = {"name": "x1", "reason": "Rain / weather", "note": "", "marked_by": "fm@x", "payroll_check": ""}
		out = self.run_it([("E1", "2026-11-03")], actuals=[("E1", "2026-11-03")],
			excuses={("E1", "2026-11-03"): ex})
		self.assertEqual(out, [])

	def test_duplicate_presence_counts_once(self):
		self.assertEqual(len(self.run_it([("E1", "2026-11-03"), ("E1", "2026-11-03")])), 1)

	def test_sorted_by_farm_day_employee(self):
		out = mw.classify([("E2", "2026-11-04"), ("E1", "2026-11-04"), ("E1", "2026-11-03")], set(), {}, {},
			{"E1": "Vale", "E2": "Vale"})
		self.assertEqual([(r["day"], r["employee"]) for r in out],
			[("2026-11-03", "E1"), ("2026-11-04", "E1"), ("2026-11-04", "E2")])


class TestPresence(unittest.TestCase):
	"""present_days: scan or Present attendance, minus Absent-only, holidays, leave, outside employment."""

	def days(self, **kw):
		base = dict(employees={"E1": {"holiday_list": "HL", "joined": "2026-01-01", "relieved": None}},
			scans=set(), present=set(), absent=set(), holidays=set(), leaves={})
		base.update(kw)
		return sorted(mw.present_days(**base))

	def test_scan_counts(self):
		self.assertEqual(self.days(scans={("E1", "2026-11-03")}), [("E1", "2026-11-03")])

	def test_present_attendance_counts(self):
		self.assertEqual(self.days(present={("E1", "2026-11-03")}), [("E1", "2026-11-03")])

	def test_absent_beats_scan(self):
		self.assertEqual(self.days(scans={("E1", "2026-11-03")}, absent={("E1", "2026-11-03")}), [])

	def test_present_beats_absent(self):
		self.assertEqual(self.days(present={("E1", "2026-11-03")}, absent={("E1", "2026-11-03")}),
			[("E1", "2026-11-03")])

	def test_holiday_dropped(self):
		self.assertEqual(self.days(scans={("E1", "2026-11-03")}, holidays={("HL", "2026-11-03")}), [])

	def test_leave_dropped(self):
		self.assertEqual(self.days(scans={("E1", "2026-11-03")},
			leaves={"E1": [("2026-11-01", "2026-11-05")]}), [])

	def test_after_relieving_dropped(self):
		emps = {"E1": {"holiday_list": "", "joined": "2026-01-01", "relieved": "2026-11-02"}}
		self.assertEqual(self.days(employees=emps, scans={("E1", "2026-11-02"), ("E1", "2026-11-03")}),
			[("E1", "2026-11-02")])

	def test_not_a_task_worker_dropped(self):
		self.assertEqual(self.days(scans={("E9", "2026-11-03")}), [])


class TestCrewDays(unittest.TestCase):
	def test_crew_span_expands_to_days(self):
		rows = [dict(A, employee="E1", start="2026-11-02", end="2026-11-04")]
		out = mw.crew_days(rows, "2026-11-03", "2026-11-10")
		self.assertEqual(sorted(out), [("E1", "2026-11-03"), ("E1", "2026-11-04")])
		self.assertEqual(out[("E1", "2026-11-03")][0]["assignment"], "ASG-1")
		self.assertNotIn("employee", out[("E1", "2026-11-03")][0])


class TestBatched(unittest.TestCase):
	def test_find_is_batched(self):
		tree = ast.parse(SRC)
		fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "find"][0]
		# iterating over one query's result is fine; a query in a loop's body is not
		for loop in [n for n in ast.walk(fn) if isinstance(n, (ast.For, ast.While))]:
			for stmt in loop.body:
				self.assertNotIn("frappe.db.sql", ast.unparse(stmt), "a query inside a loop")
		for comp in [n for n in ast.walk(fn) if isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp))]:
			self.assertNotIn("frappe.db.sql", ast.unparse(comp.elt if hasattr(comp, "elt") else comp.value))

	def test_crews_that_cannot_take_entries_are_not_crews(self):
		# the Actuals grid refuses entry on a plan closed early and on an assignment
		# whose whole crew is released; such a day is offered "Add to assignment"
		fn = SRC[SRC.index("def load("):SRC.index("def counts(")]
		self.assertIn("custom_close_state", fn)
		self.assertIn("IFNULL(w2.status, 'Active') != 'Left'", fn)

	def test_task_worker_rule_matches_dashboard(self):
		for t in ("Work Management Payable Employment Type", "Work Management Payable Designation",
				"Work Management Payable Category", "e.employment_type = 'Task Worker'"):
			self.assertIn(t, SRC)

	def test_reasons(self):
		self.assertEqual(mw.REASONS, ["Sent home – no work", "Rain / weather", "Sick / left early",
			"Scanned but not working", "Other"])


if __name__ == "__main__":
	unittest.main()


def L(**kw):
	"""A small load() result for the pure rules."""
	base = {"presence": set(), "normal_actuals": set(), "fix_states": {}, "excuses": {}, "scans": set(),
		"present": set(), "absent": set(), "half": set(), "holiday_days": set(), "leave_days": set(),
		"ar_open": set(), "sent_back": {}, "crews": {}, "home": {}}
	base.update(kw)
	return base


class TestDayState(unittest.TestCase):
	K = ("E1", "2026-11-03")

	def test_not_present_is_none(self):
		self.assertEqual(mw.day_state("E1", "2026-11-03", L()), "none")

	def test_present_no_work_is_open(self):
		self.assertEqual(mw.day_state("E1", "2026-11-03", L(presence={self.K})), "open")

	def test_normal_actuals_clear(self):
		self.assertEqual(mw.day_state("E1", "2026-11-03", L(presence={self.K}, normal_actuals={self.K})), "cleared")

	def test_pending_fix_is_waiting_confirmed_is_cleared(self):
		self.assertEqual(mw.day_state("E1", "2026-11-03",
			L(presence={self.K}, fix_states={self.K: "Pending HR Head"})), "waiting")
		self.assertEqual(mw.day_state("E1", "2026-11-03",
			L(presence={self.K}, fix_states={self.K: "CONFIRMED"})), "cleared")

	def test_reason_states(self):
		for status, want in (("Pending Farm Manager", "waiting"), ("Pending GM", "waiting"),
				("Approved", "cleared"), ("Sent back", "open")):
			self.assertEqual(mw.day_state("E1", "2026-11-03",
				L(presence={self.K}, excuses={self.K: {"status": status}})), want, status)


class TestGridCodes(unittest.TestCase):
	DAYS = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-07", "2026-11-08",
		"2026-11-09", "2026-11-10"]

	def test_codes(self):
		e = "E1"
		d = self.DAYS
		l = L(presence={(e, d[0]), (e, d[1]), (e, d[2]), (e, d[3]), (e, d[8])},
			scans={(e, d[0]), (e, d[1]), (e, d[2]), (e, d[3])}, present={(e, d[8])},
			normal_actuals={(e, d[0])}, fix_states={(e, d[2]): "Pending Farm Manager"},
			excuses={(e, d[3]): {"status": "Approved"}},
			absent={(e, d[4]), (e, d[5])}, ar_open={(e, d[5])}, leave_days={(e, d[6])}, holiday_days={(e, d[7])})
		# p: present with work, M missing, W waiting, R reason approved, A absent, X asked HR,
		# L leave, O off, then P present-by-attendance with no work -> missing again
		self.assertEqual(mw.grid_codes(e, d, l), "pMWRAXLOM")

	def test_half_day_and_no_record(self):
		l = L(presence={("E1", self.DAYS[0])}, half={("E1", self.DAYS[0])}, present={("E1", self.DAYS[0])},
			normal_actuals={("E1", self.DAYS[0])})
		self.assertEqual(mw.grid_codes("E1", self.DAYS[:2], l), "h?")


class TestGridShape(unittest.TestCase):
	def test_grid_lists_every_task_worker_and_sorts_open_first(self):
		fn = SRC[SRC.index("def grid("):SRC.index("def ", SRC.index("def grid(") + 5)]
		self.assertIn("home", fn)
		self.assertIn("crews", fn)
		self.assertIn('-w["open"]', fn)

	def test_load_is_batched(self):
		tree = ast.parse(SRC)
		fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "load"][0]
		for loop in [n for n in ast.walk(fn) if isinstance(n, (ast.For, ast.While))]:
			for stmt in loop.body:
				self.assertNotIn("frappe.db.sql", ast.unparse(stmt))

	def test_crews_carry_uom(self):
		self.assertIn("IFNULL(pl.uom, '') uom", SRC)
