# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Cap arithmetic for the Work Management Master Plan.

Pure arithmetic, so it needs no site and no database:

	./env/bin/python -m unittest upande_work_management.tests.test_master_plan -v

Figures follow the worked example in the design spec: Handling budgeted at
75,070 Trees @ 11.00 = KES 825,770.00.
"""

import unittest

from upande_work_management.master_plan import (
	TOLERANCE,
	check_cut_allowed,
	check_plan_allowed,
	line_headroom,
)


class TestLineHeadroom(unittest.TestCase):
	def test_untouched_line_has_full_headroom(self):
		h = line_headroom(75070, 825770.0, 0, 0)
		self.assertAlmostEqual(h["remaining_qty"], 75070)
		self.assertAlmostEqual(h["remaining_cost"], 825770.0)
		self.assertFalse(h["exhausted"])

	def test_partly_consumed_line(self):
		h = line_headroom(75070, 825770.0, 62670, 689370.0)
		self.assertAlmostEqual(h["remaining_qty"], 12400)
		self.assertAlmostEqual(h["remaining_cost"], 136400.0)
		self.assertAlmostEqual(h["qty_pct"], 62670 / 75070 * 100, places=6)
		self.assertFalse(h["exhausted"])

	def test_exhausted_when_either_side_is_gone(self):
		self.assertTrue(line_headroom(75070, 825770.0, 75070, 400000.0)["exhausted"])
		self.assertTrue(line_headroom(75070, 825770.0, 100, 825770.0)["exhausted"])

	def test_headroom_never_reports_negative(self):
		h = line_headroom(100, 1000.0, 130, 1400.0)
		self.assertEqual(h["remaining_qty"], 0)
		self.assertEqual(h["remaining_cost"], 0)
		self.assertTrue(h["exhausted"])

	def test_zero_budget_line_is_exhausted(self):
		self.assertTrue(line_headroom(0, 0, 0, 0)["exhausted"])


class TestCheckPlanAllowed(unittest.TestCase):
	def test_plan_within_both_ceilings_is_allowed(self):
		ok, why = check_plan_allowed(75070, 825770.0, 62670, 689370.0, 12400, 136400.0)
		self.assertTrue(ok)
		self.assertIsNone(why)

	def test_quantity_ceiling_refuses_and_says_the_numbers(self):
		ok, why = check_plan_allowed(75070, 825770.0, 62670, 689370.0, 13000, 143000.0)
		self.assertFalse(ok)
		self.assertIn("12,400", why)
		self.assertIn("13,000", why)

	def test_cost_ceiling_refuses_even_when_quantity_fits(self):
		# a rate rise makes the same quantity cost more than the budget allows
		ok, why = check_plan_allowed(75070, 825770.0, 62670, 689370.0, 12400, 190000.0)
		self.assertFalse(ok)
		self.assertIn("cost", why.lower())

	def test_exactly_hitting_the_ceiling_is_allowed(self):
		ok, why = check_plan_allowed(75070, 825770.0, 62670, 689370.0, 12400.0, 136400.0)
		self.assertTrue(ok, why)

	def test_tolerance_absorbs_float_noise(self):
		ok, _ = check_plan_allowed(100, 1000.0, 0, 0, 100 + TOLERANCE / 2, 1000.0)
		self.assertTrue(ok)

	def test_beyond_tolerance_is_refused(self):
		ok, _ = check_plan_allowed(100, 1000.0, 0, 0, 100.5, 1000.0)
		self.assertFalse(ok)


class TestCheckCutAllowed(unittest.TestCase):
	"""Lowering an approved line below what the planner already holds."""

	def test_raising_a_line_is_always_allowed(self):
		ok, why = check_cut_allowed(90000, 990000.0, 62670, 689370.0, "Handling")
		self.assertTrue(ok)
		self.assertIsNone(why)

	def test_cut_that_stays_above_committed_is_allowed(self):
		ok, why = check_cut_allowed(70000, 770000.0, 62670, 689370.0, "Handling")
		self.assertTrue(ok, why)

	def test_cut_below_committed_quantity_is_refused_and_names_both(self):
		ok, why = check_cut_allowed(50000, 550000.0, 62670, 689370.0, "Handling")
		self.assertFalse(ok)
		self.assertIn("Handling", why)
		self.assertIn("62,670", why)
		self.assertIn("50,000", why)

	def test_cost_is_checked_even_when_quantity_fits(self):
		# same trees, but the rate was corrected downwards
		ok, why = check_cut_allowed(75070, 400000.0, 62670, 689370.0, "Handling")
		self.assertFalse(ok)
		self.assertIn("KES", why)

	def test_removing_a_consumed_line_is_a_cut_to_zero(self):
		ok, why = check_cut_allowed(0, 0, 62670, 689370.0, "Handling")
		self.assertFalse(ok)
		self.assertIn("Handling", why)

	def test_removing_an_untouched_line_is_allowed(self):
		ok, why = check_cut_allowed(0, 0, 0, 0, "Pruning")
		self.assertTrue(ok, why)

	def test_cutting_exactly_to_what_is_committed_is_allowed(self):
		ok, why = check_cut_allowed(62670, 689370.0, 62670, 689370.0, "Handling")
		self.assertTrue(ok, why)

	def test_tolerance_absorbs_float_noise(self):
		ok, _ = check_cut_allowed(62670 - TOLERANCE / 2, 689370.0, 62670, 689370.0)
		self.assertTrue(ok)

	def test_beyond_tolerance_is_refused(self):
		ok, _ = check_cut_allowed(62669.5, 689370.0, 62670, 689370.0)
		self.assertFalse(ok)

	def test_reason_falls_back_when_no_task_named(self):
		ok, why = check_cut_allowed(0, 0, 10, 100.0)
		self.assertFalse(ok)
		self.assertIn("This activity", why)

