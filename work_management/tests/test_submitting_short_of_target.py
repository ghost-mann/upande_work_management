# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Submitting actuals before the plan's target has been reached.

Today the completion gate refuses: short of target the entry saves as a Draft and
the screen says how much more is needed. That is right for a site where a plan is
a commitment, and wrong for one where the crop finishes early — the work is done,
the plan will never reach its figure, and there is no way to submit what happened.

So it is a switch, OFF by default, and no existing site's behaviour moves.

ON, and short, the submit is allowed and A REASON IS REQUIRED — and the plan is
CAPPED AT WHAT WAS DONE. That is the decision recorded on 2026-09-23 and the
alternative ("submit short, plan stays open") is deliberately not built. Capped
means:

    the remaining target is closed out      quantity comes down to the delivered
                                            figure, so the hard target cap above
                                            refuses any further entry
    nothing more can be recorded or paid    custom_close_state = Closed, the same
                                            state an early close writes
    the budget goes back                    master-plan headroom is work_qty
                                            minus the sum of its plans'
                                            quantities, so lowering one releases
                                            the unspent part for a new plan
    the approved figure is kept             in original_qty, the snapshot this app
                                            already uses for a target moved after
                                            approval

and the reason and the shortfall are stamped on both documents, written as a
comment on both, and surfaced on the plan trace, in the review sheet and as a
discrepancy category, so a run of short weeks stays visible instead of becoming
normal.

    PYTHONPATH=. ~/frappe-bench3/env/bin/python -m unittest \\
        work_management.tests.test_submitting_short_of_target -v
"""

import json
import os
import unittest

from work_management.api import config

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SETTINGS = os.path.join(APP, "work_management", "doctype",
	"work_management_settings", "work_management_settings.json")
ACTUALS_DT = os.path.join(APP, "work_management", "doctype",
	"work_management_actuals", "work_management_actuals.json")

SWITCH = "allow_short_submit"
REASON = "custom_short_reason"

PATCH = os.path.join(APP, "patches", "v1_0", "switch_on_the_closed_short_check.py")


def patch_code():
	"""The patch with its docstring stripped.

	The docstring explains why this does NOT sweep every `disc_*` field, and an
	assertion that cannot tell an explanation from the thing it explains is worse
	than no assertion -- the lesson test_the_hours_audit_flags already learned
	about the patch this one follows.
	"""
	import ast

	with open(PATCH, encoding="utf-8") as handle:
		tree = ast.parse(handle.read())
	tree.body = [n for n in tree.body
		if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
			and isinstance(n.value.value, str))]
	return ast.unparse(tree)


def doctype(path):
	with open(path, encoding="utf-8") as handle:
		return json.load(handle)


def field(path, fieldname):
	for f in doctype(path).get("fields", []):
		if f.get("fieldname") == fieldname:
			return f
	return None


def api(module):
	with open(os.path.join(APP, "api", module + ".py"), encoding="utf-8") as handle:
		return handle.read()


def screen(name):
	with open(os.path.join(APP, "public", "js", name), encoding="utf-8") as handle:
		return handle.read()


def page(name):
	with open(os.path.join(APP, "www", name), encoding="utf-8") as handle:
		return handle.read()


def gate():
	"""The completion gate's own block, from its heading to the write."""
	src = api("actuals")
	at = src.index("COMPLETION GATE")
	return src[at:src.index("if is_new:", at)]


def cap():
	"""The block that caps the plan, which runs only after the submit."""
	src = api("actuals")
	at = src.index("CAP THE PLAN AT WHAT WAS DONE")
	return src[at:src.index("elif submit_now and not completed", at)]


class TestTheSwitch(unittest.TestCase):
	def test_it_exists_as_a_checkbox(self):
		self.assertEqual(field(SETTINGS, SWITCH)["fieldtype"], "Check")

	def test_it_is_off_by_default(self):
		"""No existing site's behaviour may move on a migrate. A gate that
		loosened itself would let a short week through on every site that has
		never heard of this feature."""
		self.assertIn(field(SETTINGS, SWITCH).get("default"), (None, "0", 0))

	def test_it_says_what_turning_it_on_does_to_the_plan(self):
		"""Capping a plan is not what "allow submitting early" sounds like, and
		somebody ticks this box without reading any code."""
		text = (field(SETTINGS, SWITCH).get("description") or "").lower()
		for said in ("reason is required", "capped at what was done",
				"master plan", "closed short"):
			with self.subTest(phrase=said):
				self.assertIn(said, text)

	def test_it_is_on_the_general_tab(self):
		order = doctype(SETTINGS)["field_order"]
		self.assertLess(order.index("tab_general"), order.index(SWITCH))
		self.assertLess(order.index(SWITCH), order.index("tab_farms"))

	def test_the_config_defaults_it_off(self):
		"""get_config() falls back without touching a database, and the fallback
		is what an unconfigured install runs on."""
		self.assertIn('"allow_short_submit": False,', open(
			os.path.join(APP, "api", "config.py"), encoding="utf-8").read())

	def test_the_config_reads_it(self):
		src = open(os.path.join(APP, "api", "config.py"), encoding="utf-8").read()
		self.assertIn('cfg["allow_short_submit"] = bool(settings.get("allow_short_submit"))', src)

	def test_the_dispatcher_takes_it_from_the_config(self):
		self.assertIn('ALLOW_SHORT_SUBMIT = _cfg["allow_short_submit"]', api("actuals"))


class TestTheReasonField(unittest.TestCase):
	def test_it_is_on_the_actuals_document(self):
		self.assertIsNotNone(field(ACTUALS_DT, REASON))

	def test_it_is_free_text(self):
		self.assertEqual(field(ACTUALS_DT, REASON)["fieldtype"], "Small Text")

	def test_it_is_labelled_as_the_question_it_answers(self):
		self.assertEqual(field(ACTUALS_DT, REASON)["label"], "Why the target was not met")

	def test_it_is_written_by_the_submit_rather_than_typed_on_the_form(self):
		"""It is collected in the submit dialog, which is the only moment the
		shortfall is known."""
		self.assertTrue(field(ACTUALS_DT, REASON).get("read_only"))


class TestOffIsExactlyTodaysBehaviour(unittest.TestCase):
	"""The whole safety of this change. With the switch off, nothing below the
	`elif` runs and the gate is the code it has always been."""

	def setUp(self):
		self.block = gate()

	def test_the_short_branch_is_behind_the_switch(self):
		self.assertIn("elif submit_now and ALLOW_SHORT_SUBMIT:", self.block)

	def test_the_refusal_is_still_there_for_everyone_else(self):
		self.assertIn("Target not yet completed", self.block)
		self.assertIn("Saved as Draft.", self.block)

	def test_the_refusal_prints_a_dash_rather_than_its_escape(self):
		"""Found while verifying this work, and older than it: the escape was
		doubled on the way through the port, so every site has been reading
		"Target not yet completed \\u2014 15.0 of 60.0"."""
		code = "\n".join(line for line in self.block.splitlines()
			if not line.lstrip().startswith("#"))
		self.assertNotIn("\\u2014", code)
		self.assertIn("Target not yet completed — ", code)

	def test_the_completed_and_salaried_paths_are_untouched(self):
		self.assertIn("if projected2 >= plan_target2 - 0.0001:", self.block)
		self.assertIn("elif salaried_only:", self.block)

	def test_the_short_branch_comes_after_both(self):
		"""A plan that IS complete, or one crewed only by salaried workers, must
		never be read as a short submit -- neither is short and neither should
		cap a plan."""
		self.assertLess(self.block.index("elif salaried_only:"),
			self.block.index("elif submit_now and ALLOW_SHORT_SUBMIT:"))

	def test_saving_a_draft_is_never_a_short_submit(self):
		"""`submit_now` is in the condition: saving a draft short of target is
		the ordinary way a week is recorded and must not close anything."""
		self.assertIn("submit_now and ALLOW_SHORT_SUBMIT", self.block)

	def test_the_config_key_is_the_only_way_in(self):
		"""No second switch, no form parameter that could turn it on per call.
		Three lines read it: the assignment from the config, the answer the
		screen is given so it knows whether to offer the dialog, and the one
		condition that decides."""
		src = api("actuals")
		reads = [line.strip() for line in src.splitlines()
			if "ALLOW_SHORT_SUBMIT" in line and not line.lstrip().startswith("#")]
		self.assertEqual(reads, [
			'ALLOW_SHORT_SUBMIT = _cfg["allow_short_submit"]',
			'a["allow_short_submit"] = 1 if ALLOW_SHORT_SUBMIT else 0',
			"elif submit_now and ALLOW_SHORT_SUBMIT:",
		], reads)


class TestTheReasonIsMandatory(unittest.TestCase):
	def setUp(self):
		self.block = gate()

	def test_it_is_read_from_the_request(self):
		self.assertIn('short_reason = (frappe.form_dict.get("short_reason") or "").strip()',
			self.block)

	def test_a_short_submit_without_one_is_refused(self):
		self.assertIn("if not short_reason:", self.block)
		self.assertIn("A reason is required to submit short of the target", self.block)

	def test_the_refusal_leaves_it_a_draft_rather_than_erroring(self):
		"""The grid is a worker-by-day entry somebody typed. It must not be
		thrown away because the reason box was empty -- `submit_blocked_msg` is
		the same mechanism the completion gate already uses."""
		at = self.block.index("if not short_reason:")
		self.assertIn("submit_blocked_msg = (", self.block[at:at + 400])

	def test_nothing_is_capped_without_one(self):
		"""`short_by` is what the cap keys on, and it is set only in the else."""
		at = self.block.index("if not short_reason:")
		branch = self.block[at:at + 800]
		self.assertLess(branch.index("submit_blocked_msg"), branch.index("short_by = 1"))

	def test_the_screen_asks_before_it_submits(self):
		js = screen("work-actuals.js")
		self.assertIn("if(ST._mayShort){ openShortModal(); return; }", js)

	def test_the_screen_will_not_send_an_empty_one(self):
		js = screen("work-actuals.js")
		at = js.index("function initShortModal(")
		block = js[at:at + 1200]
		self.assertIn('el("ac-short-go").disabled=!ta.value.trim()', block)
		self.assertIn('if(!reason){ toast("A reason is required"); return; }', block)

	def test_the_dialog_is_the_same_card_as_the_others(self):
		html = page("work-actuals.html")
		at = html.index('id="ac-shortmodal"')
		window = html[at:at + 2000]
		for part in ("submodal-card", "submodal-head", "submodal-body", "submodal-foot"):
			with self.subTest(part=part):
				self.assertIn(part, window)

	def test_the_dialog_says_the_plan_will_be_closed(self):
		"""Somebody pressing this is submitting a week. They should not discover
		afterwards that they also closed the plan."""
		js = screen("work-actuals.js")
		at = js.index("function openShortModal(")
		block = js[at:js.index("function closeShortModal(", at)]
		self.assertIn("closes the plan at what was done", block)
		self.assertIn("back to the master plan", block)


class TestThePlanIsCappedAtWhatWasDone(unittest.TestCase):
	"""The decision of 2026-09-23. Not "submit short, plan stays open"."""

	def setUp(self):
		self.block = cap()

	def test_the_target_comes_down_to_the_delivered_figure(self):
		self.assertIn('"quantity": sc_done,', self.block)

	def test_the_money_comes_down_with_it(self):
		"""A master plan line budgets a quantity AND a cost, and its headroom is
		exhausted when EITHER runs out. Capping the quantity alone releases the
		work and keeps the money -- so a new plan for the rest could still be
		refused on cost, and "budget freed" in the audit would always read 0.
		Recomputed at the plan's own rate, which is what adjust_target does."""
		self.assertIn('"total_cost": sc_cost,', self.block)
		self.assertIn("sc_cost = (sc_done * sc_rate) if sc_rate > 0 else sc_was_cost", self.block)

	def test_a_plan_with_no_rate_keeps_its_cost_rather_than_zeroing_it(self):
		"""`sc_done * 0` is 0, and writing that would report the whole budget as
		released when nothing about the money is known."""
		self.assertIn("if sc_rate > 0 else sc_was_cost", self.block)

	def test_the_plan_is_closed(self):
		self.assertIn('"custom_close_state": "Closed",', self.block)
		self.assertIn('"custom_closed_by": frappe.session.user,', self.block)
		self.assertIn('"custom_close_reason": short_reason,', self.block)

	def test_the_plan_is_not_left_open(self):
		"""The alternative behaviour, asserted absent so flipping it would be a
		visible edit rather than a silent drift."""
		self.assertNotIn('"custom_close_state": ""', self.block)

	def test_the_approved_figure_is_kept(self):
		self.assertIn('sc_set["original_qty"] = sc_was', self.block)

	def test_an_already_adjusted_plan_keeps_its_first_snapshot(self):
		"""original_qty means "what this was APPROVED at". A plan whose target was
		raised after approval must not have that overwritten with the raised
		figure, or the trail of the raise is lost."""
		self.assertIn("if not sc_orig:", self.block)

	def test_the_crew_is_released(self):
		"""A closed plan holds nobody, which is what close-plan-early does and
		what stops a capped plan quietly blocking next week's assignment."""
		self.assertIn('"status", "Left"', self.block)
		self.assertIn('IFNULL(we.status,\'Active\') = \'Active\'', self.block)

	def test_it_runs_only_after_the_entry_is_actually_submitted(self):
		"""Capping a plan whose submit was then refused would close a week
		nobody had finished recording."""
		src = api("actuals")
		self.assertLess(
			src.index('d.workflow_state = STAGE_NEXT["actuals_submit"]'),
			src.index("CAP THE PLAN AT WHAT WAS DONE"))

	def test_it_is_inside_the_submitted_branch(self):
		self.assertIn("if short_by and a_pr:", self.block)


class TestTheHeadroomComesBack(unittest.TestCase):
	"""The master plan budgets `work_qty` per activity and headroom is that minus
	the sum of its plans' `quantity`. Lowering one plan's quantity is therefore
	the whole mechanism -- there is no second figure to update, and a test that
	asserted one would be asserting a duplicate."""

	def test_headroom_is_computed_from_the_plans_quantity(self):
		src = api("masterplan")
		at = src.index("THE PLAN IS CHARGED ITS OWN REQUESTS")
		block = src[at:at + 900]
		self.assertIn("COALESCE(SUM(p.quantity),0) q", block)

	def test_remaining_is_the_budget_minus_that(self):
		src = api("masterplan")
		self.assertIn("hd_rq = frappe.utils.flt(ha.work_qty) - hd_pq", src)

	def test_a_rejected_plan_is_the_only_thing_excluded(self):
		"""So a CLOSED plan still counts for what it was capped at -- the work
		was done and the money was spent; only the unspent part comes back."""
		src = api("masterplan")
		at = src.index("THE PLAN IS CHARGED ITS OWN REQUESTS")
		block = src[at:at + 900]
		self.assertIn("IFNULL(p.workflow_state,'') != 'Rejected'", block)
		self.assertNotIn("custom_close_state", block)

	def test_the_cap_is_a_plain_write_to_that_field(self):
		self.assertIn('"quantity": sc_done,', cap())


class TestItIsSaidOnTheRecord(unittest.TestCase):
	def setUp(self):
		self.block = cap()

	def test_a_comment_goes_on_the_actuals_document(self):
		self.assertIn('frappe.get_doc("Work Management Actuals", d.name).add_comment(', self.block)

	def test_a_comment_goes_on_the_plan(self):
		self.assertIn('frappe.get_doc("Work Management Planner", a_pr).add_comment(', self.block)

	def test_both_carry_the_figures_and_the_reason(self):
		self.assertIn('sc_line = ("Closed short: "', self.block)
		self.assertIn('+ "Reason: " + short_reason', self.block)

	def test_a_failure_to_narrate_does_not_undo_the_cap(self):
		"""The comment is a record, not the record."""
		at = self.block.index("try:")
		self.assertIn("except Exception:", self.block[at:at + 900])

	def test_the_reason_is_stamped_on_the_actuals_document_too(self):
		self.assertIn("d.custom_short_reason = short_reason", gate())

	def test_the_actuals_document_is_marked_closed_early(self):
		"""The same flag the early-close path sets, so everything that already
		reads it -- the planner's request list, the dashboard's closed-early
		count -- picks this up without a second field."""
		self.assertIn("d.custom_closed_early = 1", gate())

	def test_the_person_is_told_what_just_happened(self):
		js = screen("work-actuals.js")
		self.assertIn("if(d.closed_short) window.alert(", js)


class TestItIsSurfacedWhereItWillBeRead(unittest.TestCase):
	def test_the_plan_trace_carries_it(self):
		src = api("planner")
		at = src.index("WAS THIS PLAN CLOSED SHORT")
		block = src[at:at + 1600]
		self.assertIn('pl["closed_short"] = {', block)
		self.assertIn('"short_qty": tr_short,', block)

	def test_the_trace_only_claims_it_for_a_closed_plan(self):
		src = api("planner")
		self.assertIn('if tr_short > 0.005 and (pl.custom_close_state or "") == "Closed":', src)

	def test_the_trace_screen_prints_it_before_the_figures(self):
		"""'Delivered 100% of target' is true and misleading when the target came
		down to meet the delivery."""
		js = screen("work-planner.js")
		at = js.index("if(p.closed_short){")
		self.assertLess(at, js.index('h+=trTile("Delivered"'))
		self.assertIn("Closed short of the approved target", js[at:at + 1200])

	def test_the_review_sheet_carries_it_per_task(self):
		src = api("payment")
		at = src.index("WAS THIS TASK'S PLAN CLOSED SHORT")
		block = src[at:at + 2200]
		self.assertIn('t["closed_short"] = [sh_by_plan[pn]', block)

	def test_the_review_sheet_prints_it_on_the_card(self):
		js = screen("work-payment.js")
		self.assertIn("(t.closed_short||[]).map(function(cs){", js)
		self.assertIn("Plan closed short.", js)


class TestTheDiscrepancyCategory(unittest.TestCase):
	""""Closed short" is the point of the whole feature: a short week that nobody
	can see becomes normality one plan at a time."""

	def setUp(self):
		self.src = api("payment")

	def short_block(self):
		at = self.src.index("CLOSED SHORT: plans capped below")
		return self.src[at:self.src.index("employees deactivated in HR", at)]

	def test_there_is_a_check_for_it(self):
		self.assertIn('{"key": "closed_short", "title": "Closed short of target"', self.src)

	def test_it_has_a_settings_toggle_like_every_other_check(self):
		self.assertEqual(field(SETTINGS, "disc_closed_short")["fieldtype"], "Check")
		self.assertIn('"closed_short": "disc_closed_short"', self.src)

	def test_the_toggle_is_read_with_the_rest(self):
		self.assertIn('"disc_closed_short"', self.src)

	def test_it_is_on_by_default(self):
		"""Unlike the feature itself. The check costs nothing on a site that
		never closes a plan short, and a site that does needs to see it."""
		self.assertEqual(field(SETTINGS, "disc_closed_short").get("default"), "1")

	def test_a_patch_makes_that_default_true_on_an_existing_site(self):
		"""THE TRAP, for the third time in this codebase. A `default` on a
		doctype field applies to a NEW document; Work Management Settings is a
		Single that already exists everywhere, so adding a Check writes `'0'`
		into tabSingles whatever the default says. Measured on kentrout.local the
		moment the field landed: disc_closed_short stored=0, disabled=1 -- the
		category shipped invisible, which is precisely what it exists to prevent.
		"""
		self.assertTrue(os.path.exists(PATCH),
			"nothing corrects the 0 that adding this field wrote")
		with open(os.path.join(APP, "patches.txt"), encoding="utf-8") as handle:
			listed = [l.strip() for l in handle
				if l.strip() and not l.lstrip().startswith("#")]
		self.assertIn("work_management.patches.v1_0.switch_on_the_closed_short_check",
			listed)

	def test_the_patch_names_the_one_new_field(self):
		"""A `disc_*` field somebody turned off by hand looks identical to one
		that was never set, so only the genuinely new one is corrected."""
		text = patch_code()
		self.assertIn("disc_closed_short", text)
		for old in ("disc_dup_day", "disc_absent_paid", "disc_long_day"):
			with self.subTest(old=old):
				self.assertNotIn(old, text)

	def test_the_patch_does_not_override_a_flag_already_on(self):
		self.assertIn("if frappe.utils.cint(stored):", patch_code())

	def test_the_patch_survives_the_field_not_existing_yet(self):
		"""Patches and schema sync are not ordered relative to each other on
		every path."""
		self.assertIn("if not meta.get_field(field):", patch_code())

	def test_no_patch_switches_the_feature_itself_on(self):
		"""`disc_closed_short` only makes a report show something. Turning on
		`allow_short_submit` would change what the pipeline DOES, and no
		existing site's behaviour may move on a migrate."""
		for name in sorted(os.listdir(os.path.join(APP, "patches", "v1_0"))):
			if not name.endswith(".py"):
				continue
			with open(os.path.join(APP, "patches", "v1_0", name), encoding="utf-8") as handle:
				body = handle.read()
			with self.subTest(patch=name):
				self.assertNotIn('set_single_value("Work Management Settings", "allow_short_submit"',
					body)

	def test_it_measures_against_what_the_plan_was_approved_for(self):
		block = self.short_block()
		self.assertIn("IFNULL(p.original_qty, 0) approved", block)
		self.assertIn("sc_short = sc_approved - frappe.utils.flt(r.capped)", block)

	def test_a_plan_closed_at_its_full_target_is_not_short(self):
		block = self.short_block()
		self.assertIn("if sc_short <= 0.005:", block)
		self.assertIn("continue", block)

	def test_the_money_column_is_budget_freed_not_money_spent(self):
		"""Every other check's KES figure is money that should not have been
		spent. A negative here would read as an overrun, which is the opposite of
		what happened."""
		self.assertIn('"amount": sc_money if sc_money > 0 else 0,', self.short_block())

	def test_the_reason_travels_with_it(self):
		self.assertIn('"reason": r.reason,', self.short_block())

	def test_the_screen_gives_it_its_own_shape(self):
		"""It is a plan, not a worker-day; the twelve-column worker table would
		be nine empty cells."""
		js = screen("work-payment.js")
		self.assertIn('} else if(c.key==="closed_short"){', js)
		at = js.index('} else if(c.key==="closed_short"){')
		block = js[at:at + 1800]
		for column in ("Approved", "Short by", "Budget freed", "Reason"):
			with self.subTest(column=column):
				self.assertIn(column, block)


class TestTheConfigStillLoadsWithoutASite(unittest.TestCase):
	"""get_config()'s fallback is what an unconfigured install runs on, and a
	missing key there fails at module top and takes a whole screen down."""

	def test_the_key_is_in_the_fallback(self):
		src = open(os.path.join(APP, "api", "config.py"), encoding="utf-8").read()
		at = src.index("def get_config():")
		block = src[at:src.index("try:", at)]
		self.assertIn('"allow_short_submit"', block)

	def test_the_module_still_names_the_two_payment_paths(self):
		"""A smoke check that config.py imports and its constants survive."""
		self.assertTrue(config.ACCOUNTS_RELEASE)
		self.assertTrue(config.PAYROLL_FEED)


if __name__ == "__main__":
	unittest.main()
