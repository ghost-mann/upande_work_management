"""Field intelligence's weekly series: the numbers behind its graphs.

The Efficiency tab draws cost per hectare (of the farm, and of the ground worked),
weekly cost and Ha per man-day as lines over Monday-start weeks. The series come
from one block in `field_intel`, and three of its rules are easy to break:

- a week with no confirmed work is None -- a gap in the line, not a week that
  cost nothing and drags the line to the floor;
- a block worked by two plans in one week is one block's hectares, not two;
- a week whose blocks have no area is None with the blanks counted, so the
  screen says "not recorded" rather than dividing by part of the ground.

The block is lifted out of the shipped module and executed here, so what is
tested is the code that runs rather than a description of it.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_field_intel_weekly -v
"""

import datetime
import inspect
import textwrap
import types
import unittest

import frappe
import frappe.utils

from work_management.api import dashboard

START = "# ── weekly series for the Field intelligence graphs ──"
END = "# ── end weekly series ──"


def row(pr, farm, wk, mandays, pay):
	return frappe._dict(pr=pr, farm=farm, wk=datetime.date.fromisoformat(wk), mandays=mandays, pay=pay)


def run_block(fifrom, fito, week_rows, plan_blocks, all_blocks, farms_out):
	lines = inspect.getsource(dashboard.wm_dashboard).splitlines(True)
	first = next(i for i, l in enumerate(lines) if START in l)
	last = next(i for i, l in enumerate(lines) if END in l)
	block = textwrap.dedent("".join(lines[first:last]))
	namespace = {
		"frappe": types.SimpleNamespace(utils=frappe.utils),
		"fifrom": fifrom,
		"fito": fito,
		"fi_week_rows": week_rows,
		"plan_blocks": plan_blocks,
		"all_blocks": all_blocks,
		"farms_out": farms_out,
	}
	exec(compile(block, "<weekly-series>", "exec"), namespace)
	return namespace["fi_weekly"]


class TestTheWeeks(unittest.TestCase):
	def test_weeks_start_on_monday_and_count_their_days_in_the_window(self):
		# Wed 7 Oct .. Tue 20 Oct 2026: three weeks, the outer two partial
		out = run_block("2026-10-07", "2026-10-20", [], {}, {}, [])
		self.assertEqual(out["weeks"], ["2026-10-05", "2026-10-12", "2026-10-19"])
		self.assertEqual(out["days"], [5, 7, 2])


class TestTheFarmSeries(unittest.TestCase):
	def setUp(self):
		self.farms_out = [{"farm": "Lokitela", "area": 217.0}, {"farm": "Vale", "area": 250.0}]
		self.plan_blocks = {"P1": {"L-A": 1, "L-B": 1}, "P2": {"L-A": 1}, "P3": {"V-1": 1}}
		self.all_blocks = {"L-A": 10.0, "L-B": 5.5, "V-1": 0}

	def weekly(self, rows):
		out = run_block("2026-10-05", "2026-10-18", rows, self.plan_blocks, self.all_blocks, self.farms_out)
		return {f["farm"]: f for f in out["farms"]}

	def test_plans_in_a_week_add_up_and_an_idle_week_is_a_gap(self):
		farms = self.weekly([
			row("P1", "Lokitela", "2026-10-05", 10, 4000),
			row("P2", "Lokitela", "2026-10-05", 2.5, 1000),
		])
		self.assertEqual(farms["Lokitela"]["cost"], [5000, None])
		self.assertEqual(farms["Lokitela"]["mandays"], [12.5, None])
		self.assertEqual(farms["Lokitela"]["area"], 217.0)

	def test_a_block_two_plans_worked_in_one_week_counts_once(self):
		farms = self.weekly([
			row("P1", "Lokitela", "2026-10-12", 4, 1000),
			row("P2", "Lokitela", "2026-10-12", 4, 1000),
		])
		self.assertEqual(farms["Lokitela"]["worked_ha"], [None, 15.5])
		self.assertEqual(farms["Lokitela"]["missing_blocks"], [0, 0])

	def test_blocks_without_an_area_are_not_recorded_rather_than_zero(self):
		farms = self.weekly([row("P3", "Vale", "2026-10-05", 3, 900)])
		self.assertEqual(farms["Vale"]["worked_ha"], [None, None])
		self.assertEqual(farms["Vale"]["missing_blocks"], [1, 0])
		self.assertEqual(farms["Vale"]["cost"], [900, None])

	def test_only_farms_in_the_table_get_a_series(self):
		farms = self.weekly([row("P9", "Elsewhere", "2026-10-05", 1, 100)])
		self.assertEqual(farms, {})

	def test_rows_outside_the_weeks_are_ignored(self):
		farms = self.weekly([row("P1", "Lokitela", "2026-09-28", 1, 100)])
		self.assertEqual(farms, {})


if __name__ == "__main__":
	unittest.main()
