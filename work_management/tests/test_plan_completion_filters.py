"""The dashboard's Plan completion filters.

Two things made them look broken. The server kept any plan whose period merely
overlapped the range, while the card groups plans by the week each one starts --
so a month-long plan sat under every range, and 4 weeks, 8 weeks and All came back
the same. And the date boxes waited for an Apply button while the farm picker
applied at once, so a changed date silently did nothing.
"""

import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ported(module):
	with open(os.path.join(HERE, "api", module + ".py")) as handle:
		return handle.read()


def dashboard_js():
	with open(os.path.join(HERE, "public", "js", "work-management-dashboard.js")) as handle:
		return handle.read()


class TestRangeSelectsByStartWeek(unittest.TestCase):
	def setUp(self):
		src = ported("dashboard")
		self.block = src[src.index('action == "plan_completion"'):][:2500]

	def test_a_plan_is_in_range_when_it_starts_in_range(self):
		self.assertIn("period_from >= %(a)s AND period_from <= %(b)s", self.block)

	def test_overlap_no_longer_decides(self):
		self.assertNotIn("period_from <= %(b)s AND period_to >= %(a)s", self.block)

	def test_the_default_range_is_the_eight_week_button(self):
		# the card opens with "8 weeks" lit, so the default must be that same range
		self.assertIn("add_days(frappe.utils.today(), -55)", self.block)


class TestControlsApplyOnChange(unittest.TestCase):
	def setUp(self):
		js = dashboard_js()
		self.controls = js[js.index("function pcControls"):js.index("function pcRow")]
		self.wire = js[js.index("function pcWire"):js.index("function todayISO")]

	def test_there_is_no_apply_button(self):
		self.assertNotIn("pc-apply", self.controls)
		self.assertNotIn("pc-apply", self.wire)

	def test_each_date_box_refetches_when_changed(self):
		for box in ("pc-from", "pc-to"):
			self.assertRegex(self.wire, r'el\("' + box + r'"\)[^;]*;\s*if\(\w+\) \w+\.onchange=')

	def test_quick_ranges_are_whole_weeks_ending_today(self):
		# n weeks back including today is n*7-1 days, not n*7 -- one day more pulls in
		# a plan that started the day before the range and so shows an extra week
		days = sorted(int(d) for d in re.findall(r"\b(27|55|83)\b", self.wire))
		self.assertEqual(days, [27, 55, 83])


class TestOnlyTheNewestResponseDraws(unittest.TestCase):
	"""Typing a year into a date box fires a change per digit, so several requests
	race; a slow early one must not overwrite the answer to the last."""

	def test_stale_responses_are_dropped(self):
		js = dashboard_js()
		fetch = js[js.index("function planCompletion"):js.index("function pcControls")]
		self.assertIn("var seq=++PC.seq;", fetch)
		self.assertEqual(fetch.count("if(seq!==PC.seq) return;"), 2)


def action_block(name, size=12000):
	src = ported("dashboard")
	start = src.index('action == "' + name + '"')
	end = src.find("\nelif action ==", start + 10)
	return src[start:end if end > 0 else start + size]


class TestMasterPlanCardServer(unittest.TestCase):
	def test_a_list_naming_no_farm_is_bounded_by_the_callers_farms(self):
		block = action_block("plan_completion")
		self.assertIn('pc_where = " AND farm IN %(fms)s"', block)

	def test_work_done_is_weighted_by_value_never_summed_across_units(self):
		block = action_block("plan_completion")
		self.assertIn('"completion": frappe.utils.flt(pc_wv / pc_wd * 100, 1)', block)
		self.assertNotIn("pc_dq / pc_pq * 100", block)

	def test_the_list_reports_pay_awaiting_approval(self):
		self.assertIn('"pending_value"', action_block("plan_completion"))

	def test_the_list_reports_work_recorded_but_not_yet_approved(self):
		block = action_block("plan_completion")
		self.assertIn('"recorded_completion"', block)
		self.assertIn("IFNULL(ac.workflow_state,'') != 'Rejected'", block)

	def test_detail_checks_the_plans_own_farm(self):
		# the dispatch guard only sees a farm named in the request; mp_detail's farm
		# comes from the plan, so it must check it itself
		self.assertIn("FARMS and md_plan.farm not in FARMS", action_block("mp_detail"))

	def test_detail_returns_every_section_the_panel_shows(self):
		block = action_block("mp_detail")
		for key in ("plan", "money", "activities", "requests", "assignments",
				"actuals", "people", "payments"):
			self.assertIn('out["' + key + '"]', block, key)

	def test_detail_attributes_requests_by_the_completion_rule(self):
		block = action_block("mp_detail")
		self.assertIn("master_plan = %(plan)s", block)
		self.assertIn("IFNULL(master_plan,'') = ''", block)


class TestMasterPlanCardScreen(unittest.TestCase):
	def setUp(self):
		self.js = dashboard_js()

	def test_both_measures_are_named(self):
		self.assertIn(">Work done<", self.js)
		self.assertIn(">Budget used<", self.js)

	def test_status_reads_work_against_time(self):
		assess = self.js[self.js.index("function pcAssess"):self.js.index("function pcChipMatch")]
		# recorded work, approved or not: sign-off lags the field by days
		self.assertIn("recorded+PC_BEHIND_MARGIN<time", assess)
		self.assertIn("recorded>=PC_DONE_AT", assess)
		self.assertIn("var PC_BEHIND_MARGIN = 15;", self.js)
		self.assertIn("var PC_DONE_AT = 90;", self.js)

	def test_the_open_plan_loads_its_detail(self):
		self.assertIn('call({action:"mp_detail", plan:plan})', self.js)

	def test_detail_rows_open_the_existing_drawers(self):
		draw = self.js[self.js.index("function pcDrawDetail"):self.js.index("function pcPane")]
		for opener in ("openPlanModal", "openActualModal", "openEmpModal", "openPaymentModal"):
			self.assertIn(opener, draw)

	def test_dates_are_local_not_utc(self):
		self.assertIn("function todayISO(){ return localISO(new Date()); }", self.js)


class TestThePlansValueIsItsLines(unittest.TestCase):
	"""The header's total_cost goes stale when lines are edited outside the
	screen; on four live plans it was a fraction of the lines, and the card
	flagged them over budget when no line was."""

	def test_the_list_values_a_plan_by_its_approved_lines(self):
		block = action_block("plan_completion")
		self.assertIn("pc_wd_cost = pc_wd_cost + frappe.utils.flt(pc_a.cost)", block)
		self.assertIn("pc_val = frappe.utils.flt(pc_wd_cost, 2) if pc_wd_cost > 0", block)

	def test_the_detail_does_too(self):
		self.assertIn("md_planned = md_planned + frappe.utils.flt(md_a.cost)", action_block("mp_detail"))


class TestTrendsSaysWhatItsNumbersAre(unittest.TestCase):
	def setUp(self):
		self.block = action_block("charts", 30000)
		self.js = dashboard_js()

	def test_actuals_are_measured_against_a_target_in_one_unit(self):
		# output valued at its rate, so trees, hours and kilograms add up
		self.assertIn("we.actual_quantity * ac.rate", self.block)
		self.assertIn('w["target"]', self.block)
		self.assertIn('["out","Actuals vs target"]', self.js)

	def test_work_in_approval_is_shown_not_dropped(self):
		self.assertIn('w["val_pend"]', self.block)
		self.assertIn('w["pay_pend"]', self.block)

	def test_no_farm_named_means_the_callers_farms(self):
		self.assertIn('dconds = dconds + " AND ac.farm IN %s"', self.block)
		self.assertIn('sc_conds = sc_conds + " AND farm IN %(fs)s"', self.block)

	def test_the_strip_carries_money_and_names_its_waiting_counts(self):
		self.assertIn('out["stage_money"]', self.block)
		self.assertIn('["to_paid","payment runs unpaid"]', self.js)

	def test_growth_is_only_claimed_against_a_period_the_records_cover(self):
		self.assertIn('out["data_from"]', self.block)
		self.assertIn("pw.from < AN.data.data_from", self.js)

	def test_the_card_has_a_key(self):
		self.assertIn("bd.innerHTML=rgNote+bd.innerHTML+anKey();", self.js)

	def test_the_farm_picker_fills_without_waiting_for_a_list_never_sent(self):
		self.assertIn('out["farms"] = list(FARMS) if FARMS else []', self.block)
		self.assertIn(":FARM_LIST;", self.js)

	def test_a_week_cut_by_the_dates_is_not_compared_as_a_full_week(self):
		self.assertIn("function anPartial(wstart)", self.js)
		self.assertIn('out["range"]', self.block)
