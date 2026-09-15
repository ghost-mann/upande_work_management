"""A planner request may be any range inside its master plan's period.

A master plan can budget a whole month. The planner screen used to snap the
request's dates to that whole period the moment a plan was chosen, so planning a
single week under a monthly budget meant editing the dates back down again --
and the screen's own words were "Pick one to snap the dates to it".

The server never required that. `tasks` finds a plan with
`period_from <= from_date AND period_to >= to_date`, which is containment, not
equality. So this is the screen's arithmetic, lifted out and tested here::

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_planner_period -v

The JS is not importable, so the rules are asserted twice: the pure decision is
duplicated here in Python and checked against the cases that matter, and
test_the_screen_still_implements_these_rules() greps the shipped script for the
markers, so the two cannot silently part company.

`clamp_into_plan()` below is the rule for a request that OVERLAPS the plan, and
that is all it ever claimed. A request with no overlap at all -- wholly before
or wholly after -- cannot be clamped into the plan: the clamp leaves one edge
where it was and pushes the other to meet it, so both end up outside. That case
is placed rather than pulled, and lives in
`work_management/tests/test_the_plan_pill_is_a_picker`.
"""

import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def clamp_into_plan(current_from, current_to, plan_from, plan_to):
	"""(from, to) for a request against a chosen plan. Mirrors the screen.

	Empty dates take the plan's period: there is no intent to preserve. Dates
	that already fit are returned untouched, which is the whole point of the
	change. Dates that hang outside are pulled to the nearest edge rather than
	replaced, so a request for the 5th to the 9th of a month whose plan starts on
	the 7th becomes the 7th to the 9th, not the whole month.
	"""
	if not current_from or not current_to:
		return plan_from, plan_to
	return max(current_from, plan_from), min(current_to, plan_to)


class TestChoosingAPlanKeepsTheDatesYouMeant(unittest.TestCase):
	MONTH = ("2026-08-01", "2026-08-31")

	def test_a_week_inside_a_monthly_plan_is_left_alone(self):
		"""The case that prompted this: a month-long budget, a week's work."""
		self.assertEqual(
			clamp_into_plan("2026-08-05", "2026-08-09", *self.MONTH),
			("2026-08-05", "2026-08-09"),
		)

	def test_a_single_day_inside_the_plan_is_left_alone(self):
		self.assertEqual(
			clamp_into_plan("2026-08-14", "2026-08-14", *self.MONTH),
			("2026-08-14", "2026-08-14"),
		)

	def test_dates_matching_the_plan_exactly_are_left_alone(self):
		self.assertEqual(clamp_into_plan(*self.MONTH, *self.MONTH), self.MONTH)

	def test_empty_dates_take_the_plans_period(self):
		self.assertEqual(clamp_into_plan("", "", *self.MONTH), self.MONTH)

	def test_a_range_starting_before_the_plan_is_pulled_to_its_start(self):
		self.assertEqual(
			clamp_into_plan("2026-07-28", "2026-08-09", *self.MONTH),
			("2026-08-01", "2026-08-09"),
		)

	def test_a_range_ending_after_the_plan_is_pulled_to_its_end(self):
		self.assertEqual(
			clamp_into_plan("2026-08-25", "2026-09-04", *self.MONTH),
			("2026-08-25", "2026-08-31"),
		)

	def test_a_range_straddling_the_plan_entirely_becomes_the_plan(self):
		self.assertEqual(
			clamp_into_plan("2026-07-01", "2026-09-30", *self.MONTH), self.MONTH
		)


class TestTheScreenStillImplementsTheseRules(unittest.TestCase):
	"""Greps rather than runs: the screen is JS, and this is the seam.

	Each assertion names a behaviour the Python above tests, so if someone
	restores the snapping the grep fails and points at this file.
	"""

	def setUp(self):
		path = os.path.join(HERE, "public", "js", "work-planner.js")
		with open(path) as handle:
			self.js = handle.read()

	def test_the_chip_no_longer_overwrites_the_dates_outright(self):
		"""The old two lines set both inputs from the chip unconditionally."""
		self.assertNotRegex(
			self.js,
			re.compile(
				r'el\("f-from"\)\.value=x\.getAttribute\("data-bf"\);\s*'
				r'el\("f-to"\)\.value=x\.getAttribute\("data-bt"\);'
			),
		)

	def test_it_bounds_the_date_inputs_to_the_chosen_plan(self):
		"""The function was renamed `planInside` when it grew a second branch for
		a request that does not overlap the plan at all -- where there is nothing
		to clamp onto and both edges have to be placed. That branch and its cases
		live in test_the_plan_pill_is_a_picker; the clamping asserted here is
		unchanged and still what runs for everything that overlaps."""
		self.assertIn("planInside", self.js)
		self.assertNotIn("boundDatesToPlan", self.js)

	def test_the_clamp_is_still_the_answer_wherever_it_can_be(self):
		at = self.js.index("  function planInside(")
		fn = self.js[at:self.js.index("\n  function ", at + 10)]
		for line in ("if(f.value < pf) f.value=pf;",
				"if(t.value > pt) t.value=pt;",
				"if(t.value < f.value) t.value=f.value;"):
			with self.subTest(line=line):
				self.assertIn(line, fn)

	def test_the_wording_no_longer_offers_to_snap(self):
		self.assertNotIn("snap the dates to it", self.js)

	def test_the_slider_is_clamped_to_the_plans_end(self):
		self.assertIn("clampToPlanEnd", self.js)
