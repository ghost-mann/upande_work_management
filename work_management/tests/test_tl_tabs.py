"""Team leader card tabs (2026-11-26): Late assigning and People.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_tl_tabs -v
"""

import datetime
import os
import types
import unittest
from unittest import mock

from work_management import assign_ahead as aa
from work_management.tests import mirror
from work_management.tests.test_one_worker_one_day import source

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(HERE, "public", "js", "work-management-dashboard.js")


class Row(dict):
	__getattr__ = dict.get


class FakeDb:
	"""Answers each SQL by the first table it names."""

	def __init__(self, answers, singles=None):
		self.answers = answers
		self.singles = singles or {}
		self.queries = []

	def sql(self, query, args=None, as_dict=False):
		self.queries.append((query, args))
		for key, rows in self.answers.items():
			if key in query:
				return [Row(r) for r in rows] if as_dict else [tuple(r.values()) if isinstance(r, dict) else r for r in rows]
		return []

	def get_single_value(self, dt, field):
		return self.singles.get(field)


def patched(db):
	return mock.patch.object(aa, "frappe", types.SimpleNamespace(db=db, utils=aa.frappe.utils))


class TestLateReport(unittest.TestCase):
	def setUp(self):
		self.db = FakeDb({
			"FROM `tabWork Management Assigner` a": [
				{"asg": "A1", "start": datetime.date(2026, 11, 27), "created": "2026-11-25 10:00:00", "farm": "Vale",
				 "task": "T1", "task_label": "Weeding", "block": "B1", "state": "Assigned", "reason": None, "note": None,
				 "saver": "clerk@x", "tl": "EMP-0042", "custom_approved_at": None, "approval_date": None},
				{"asg": "A2", "start": datetime.date(2026, 11, 27), "created": "2026-11-27 07:10:00", "farm": "Vale",
				 "task": "T1", "task_label": "Weeding", "block": "B2", "state": "Assigned", "reason": "Weather",
				 "note": None, "saver": "clerk@x", "tl": "EMP-0042", "custom_approved_at": None, "approval_date": None},
			],
			"FROM `tabUser`": [("clerk@x", "Clerk One")],
			"FROM `tabEmployee`": [("EMP-0042", "Jane Leader")],
		}, singles={"assign_cutoff_time": "18:00:00", "assign_day_before": 0})

	def test_counts_and_names(self):
		with patched(self.db):
			out = aa.late_report(["Vale"], "2026-11-01", "2026-11-30")
		self.assertEqual(out["by_leader"][0]["name"], "Jane Leader")   # Employee ID leader, no login
		self.assertEqual((out["by_leader"][0]["total"], out["by_leader"][0]["late"]), (2, 1))
		self.assertEqual(out["by_saver"][0]["name"], "Clerk One")
		self.assertEqual([r["asg"] for r in out["late_rows"]], ["A2"])
		self.assertEqual(out["cutoff"], "18:00")
		self.assertEqual(out["switch_on"], 0)

	def test_filters_reach_the_query(self):
		with patched(self.db):
			aa.late_report(["Vale"], "2026-11-01", "2026-11-30", farm="Vale", team_leader="EMP-0042")
		q, args = self.db.queries[0]
		self.assertIn("p.team_leader = %(tl)s", q)
		self.assertIn("a.farm = %(fm)s", q)
		self.assertIn("!= 'Rejected'", q)
		self.assertEqual(args["tl"], "EMP-0042")


class TestCrewOnDay(unittest.TestCase):
	"""People tab list (2026-11-28): per leader, assigned and present on a picked day."""

	def setUp(self):
		self.db = FakeDb({
			"FROM `tabWork Assignment Employee`": [
				{"tl": "EMP-0042", "emp": "W1"}, {"tl": "EMP-0042", "emp": "W2"},
				{"tl": "EMP-0042", "emp": "W3"}, {"tl": "EMP-0042", "emp": "W4"},
				{"tl": "tl@x", "emp": "W1"},
			],
			"FROM `tabEmployee Checkin`": [("W1", "2026-11-20 06:58:00")],
			"FROM `tabAttendance`": [("W2", "Absent"), ("W3", "Present")],
			"FROM `tabLeave Application`": [("W4", "Annual Leave")],
			"FROM `tabUser`": [("tl@x", "Tom Leader")],
			"FROM `tabEmployee`": [("EMP-0042", "Jane Leader")],
		})

	def run(self, result=None):
		with mock.patch.object(aa.frappe.utils, "today", return_value="2026-11-28"):
			return super().run(result)

	def test_counts_per_leader(self):
		with patched(self.db):
			out = aa.crew_on_day(["Vale"], "2026-11-20")
		jane = out["EMP-0042"]
		self.assertEqual((jane["assigned"], jane["present"], jane["absent"], jane["leave"], jane["not_scanned"]),
			(4, 2, 1, 1, 0))
		self.assertEqual(jane["name"], "Jane Leader")
		self.assertEqual((out["tl@x"]["assigned"], out["tl@x"]["present"]), (1, 1))  # one worker, two leaders

	def test_day_and_farm_reach_the_query(self):
		with patched(self.db):
			aa.crew_on_day(["Vale"], "2026-11-20", farm="Vale")
		q, args = self.db.queries[0]
		self.assertEqual(args["d"], "2026-11-20")
		self.assertIn("a.farm = %(fm)s", q)
		self.assertIn("<= %(d)s", q)
		self.assertIn(">= %(d)s", q)

	def test_future_day_reads_no_scans(self):
		with patched(self.db):
			out = aa.crew_on_day(["Vale"], "2999-01-01")
		self.assertEqual(out["EMP-0042"]["present"], 0)
		self.assertFalse(any("Checkin" in q for q, _ in self.db.queries))


class TestDashboardActions(unittest.TestCase):
	def setUp(self):
		self.src = source("dashboard")
		start = self.src.index('action == "tl_late" or action == "tl_people"')
		self.body = self.src[start:self.src.index('elif action == "plan_completion"', start)]

	def test_same_visibility_as_tl_kpis(self):
		self.assertIn("if not tq_all:\n            tq_who = frappe.session.user", self.body)

	def test_farm_must_be_one_of_ours(self):
		self.assertIn("tq_farm not in FARMS", self.body)

	def test_calls_the_rules(self):
		for fn in ("late_report", "crew_people", "leaders_in", "crew_on_day"):
			self.assertIn("work_management.assign_ahead." + fn, self.body)


class TestScreen(unittest.TestCase):
	def setUp(self):
		with open(JS) as h:
			self.js = h.read()

	def test_three_tabs(self):
		for label in ('"perf","Performance"', '"late","Late assigning"', '"people","People"'):
			self.assertIn(label, self.js)

	def test_calls_the_actions(self):
		self.assertIn('action:"tl_late"', self.js)
		self.assertIn('action:"tl_people"', self.js)

	def test_people_day_columns(self):
		self.assertIn('id="tlk-day"', self.js)
		self.assertIn('action:"tl_people", day:TLK.day', self.js)
		self.assertIn("day_counts", self.js)
		self.assertIn("Assigned ", self.js)

	def test_both_late_views(self):
		self.assertIn("By team leader", self.js)
		self.assertIn("By who saved", self.js)

	@unittest.skipUnless(mirror.present(mirror.WEB_PAGES), "mirror not checked out")
	def test_same_as_mirror(self):
		with open(os.path.join(mirror.WEB_PAGES, "work-management-dashboard.js")) as h:
			self.assertEqual(h.read(), self.js)


if __name__ == "__main__":
	unittest.main()
