"""The dashboard's activity, people & block explorer.

See docs/superpowers/specs/2026-10-08-activity-people-block-explorer-design.md.
"""

import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ported(module):
	with open(os.path.join(HERE, "api", module + ".py")) as handle:
		return handle.read()


def dashboard_js():
	with open(os.path.join(HERE, "public", "js", "work-management-dashboard.js")) as handle:
		return handle.read()


class TestExplorerServer(unittest.TestCase):
	def setUp(self):
		self.src = ported("dashboard")

	def test_every_action_is_dispatched(self):
		for action in ("ex_lens", "ex_detail", "ex_series"):
			self.assertIn('action == "' + action + '"', self.src)

	def test_the_range_is_bounded_by_the_callers_farms(self):
		helper = self.src[self.src.index("def wmx_range"):self.src.index("def wmx_plan_condition")]
		self.assertIn("elif FARMS:", helper)
		self.assertIn("ac.farm IN %(xfarms)s", helper)

	def test_rejected_work_is_never_counted(self):
		join = self.src[self.src.index("WMX_JOIN = "):self.src.index("WMX_JOIN_PAID")]
		self.assertIn("IFNULL(ac.workflow_state,'') != 'Rejected'", join)
		self.assertIn("IFNULL(pr.workflow_state,'') != 'Rejected'", join)

	def test_output_against_target_is_a_ratio_per_day_never_a_sum_across_units(self):
		self.assertIn("ae.actual_quantity / pr.daily_target", self.src)

	def test_paid_is_joined_once_not_probed_per_row(self):
		# a correlated lookup per worker-day took 22s over eight weeks of the estate
		start = self.src.index('action == "ex_lens"')
		block = self.src[start:self.src.index('elif action == "activity_table"', start)]
		self.assertNotIn("EXISTS (SELECT 1 FROM `tabWork Payment Line`", block)
		self.assertIn("WMX_JOIN_PAID", block)

	def test_a_plan_is_attributed_by_the_plans_card_rule(self):
		helper = self.src[self.src.index("def wmx_plan_condition"):self.src.index("def wmx_subject")]
		self.assertIn(".master_plan = %(xplan)s", helper)
		self.assertIn("IFNULL(", helper)


class TestExplorerScreen(unittest.TestCase):
	def setUp(self):
		self.js = dashboard_js()

	def test_the_section_replaces_the_three_it_absorbed(self):
		for gone in ("Planned value &amp; delivery", "Pipeline performers", "Employee &amp; assignment tracker"):
			self.assertNotIn(gone, self.js)
		self.assertIn('id="wm-ex"', self.js)
		self.assertIn("exInit();", self.js)

	def test_one_unit_per_chart_panel(self):
		# money, percentages and headcount each get their own panel: never two
		# y-scales on one axis
		self.assertIn('var EX_PANELS = {money:"Money (KES)", perf:"Performance (%)", people:"People per day"};', self.js)

	def test_both_cards_carry_a_key(self):
		self.assertIn("function exKey()", self.js)
		self.assertIn("h+=pcKey();", self.js)

	def test_tooltips_write_record_names_as_text(self):
		tip = self.js[self.js.index("function exShowTip"):self.js.index("function exHideTip")]
		self.assertIn("textContent", tip)
		self.assertNotIn("innerHTML", tip)
