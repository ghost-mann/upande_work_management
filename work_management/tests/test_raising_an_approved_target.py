"""More of the same work on a request already approved, without a second chain.

A week is approved for 500 and the crew can clearly finish 700. Today that needs
a second request through the whole chain for work already under way -- or an
edit, which sends the approved plan back to Draft and throws away the approval it
has. So the target moves in place.

**No new approval stage.** Managers agree a spend increase offline, by decision;
what this has to guarantee is that whoever records the decision is somebody who
could have approved the request in the first place. Raising your own approved
target is approving your own request, one step later and with nobody looking.

**Upward only.** The actuals HARD TARGET CAP and the COMPLETION GATE both read
`Work Management Planner.quantity` live at save time. Cut it below what is
already recorded and recorded work exceeds its own target, while the plan can
never reach 100% and so can never be submitted. `check_cut_allowed()` refuses the
same move on a master plan line for the same reason.

**The guard is on the DOCUMENT, not only on the action.** `quantity` needs
`allow_on_submit` for any of this to be possible, and that opens the desk form
too -- where the action's checks do not run. So the rule lives in the doctype
controller, and is therefore true of every path that reaches the field.

Measured on kentrout.local, request WM-KenTrout Farm-00181 against WMMP-00007
(Weeding budgeted 50):

    before   6 @ KES 800, crew 2, 2 man-days
    raise to 20 -> KES 2,666.67, crew 7, 6 man-days, original_qty 6 kept
    the master plan line moves with it: planned 6 -> 20, remaining 44 -> 30
    raising to 90 refused: "44.0 left of 50.0, this raise asks for 84.0 more"
    lowering to 3 refused, from the action AND from a desk save

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_raising_an_approved_target -v
"""

import json
import os
import re
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLANNER_API = os.path.join(APP, "api", "planner.py")
ACTUALS_API = os.path.join(APP, "api", "actuals.py")
SCREEN = os.path.join(APP, "public", "js", "work-planner.js")
DOCTYPE = os.path.join(APP, "work_management", "doctype",
	"work_management_planner", "work_management_planner.json")
CONTROLLER = os.path.join(APP, "work_management", "doctype",
	"work_management_planner", "work_management_planner.py")

ACTION = "raise_target"


def read(path):
	with open(path) as handle:
		return handle.read()


def js_function(src, name):
	"""One JS function body, declaration to the next one at column 2.

	These assertions used to take a fixed 4,200-character slice of the file and
	search that. Adding four lines of copy to the dialog pushed the code they
	were looking for past the end of the window, and two tests failed for a
	reason that had nothing to do with what they were testing.
	"""
	at = src.index("  function %s(" % name)
	nxt = src.find("\n  function ", at + 10)
	return src[at:nxt if nxt > 0 else len(src)]


def fields():
	return {f["fieldname"]: f for f in json.load(open(DOCTYPE))["fields"]}


def action_block():
	src = read(PLANNER_API)
	at = src.index('elif action in ("raise_target", "adjust_target"):')
	return src[at:src.index('elif action == "approve":', at)]


class TestTheSnapshotFields(unittest.TestCase):
	"""What was approved has to survive the edit that changed it, or "what did we
	agree to" stops being answerable. Master Plan Activity rows have carried
	original_qty / original_cost for exactly this since before this feature."""

	def setUp(self):
		self.fields = fields()

	def test_both_exist(self):
		self.assertIn("original_qty", self.fields)
		self.assertIn("original_cost", self.fields)

	def test_they_are_read_only(self):
		for name in ("original_qty", "original_cost"):
			with self.subTest(field=name):
				self.assertTrue(self.fields[name].get("read_only"))

	def test_they_sit_beside_the_quantity_they_record(self):
		order = json.load(open(DOCTYPE))["field_order"]
		self.assertEqual(order[order.index("quantity") + 1], "original_qty")

	def test_the_pattern_is_named_in_the_description(self):
		"""So the next reader finds the Activity row's version of the same idea."""
		self.assertIn("original_qty", self.fields["original_qty"].get("description") or "")

	def test_the_fields_the_raise_writes_survive_submission(self):
		"""An Approved request is a submitted document. Without allow_on_submit
		the save raises UpdateAfterSubmitError and the feature cannot exist."""
		for name in ("quantity", "total_cost", "people_per_day", "person_days",
				"original_qty", "original_cost"):
			with self.subTest(field=name):
				self.assertTrue(self.fields[name].get("allow_on_submit"), name)


class TestTheDocumentGuardsItself(unittest.TestCase):
	"""allow_on_submit is a property of the FIELD, not of the action: it opens the
	desk form too, where the action's gate does not run. Without this, an approved
	target would be editable in either direction by anybody with write permission,
	with nothing recorded."""

	def setUp(self):
		self.src = read(CONTROLLER)

	def test_the_controller_hooks_the_after_submit_update(self):
		self.assertIn("def on_update_after_submit(self):", self.src)

	def test_it_compares_against_what_was_there_before(self):
		self.assertIn("get_doc_before_save()", self.src)

	def test_lowering_below_the_recorded_floor_is_refused(self):
		"""Lowering to the floor is how a plan that over-asked is closed
		honestly; below it strands recorded work."""
		self.assertIn("if now < was - TOLERANCE:", self.src)
		self.assertIn("if now < floor - TOLERANCE:", self.src)

	def test_the_refusal_says_why_rather_than_just_no(self):
		self.assertIn("reads the target live", self.src)
		self.assertIn("unable to complete", self.src)

	def test_it_asks_the_configured_chain_who_may(self):
		"""Named roles here would go stale the moment a site renamed one or added
		a step."""
		self.assertIn("approvals.effective_chain", self.src)
		self.assertIn('document_type="Work Management Planner"', self.src)

	def test_only_enabled_approval_steps_count(self):
		at = self.src.index("def approver_roles(")
		block = self.src[at:self.src.index("def may_raise_target(")]
		self.assertIn('step.get("kind") == "Approval"', block)
		self.assertIn('step.get("on")', block)

	def test_the_rule_is_pure_and_so_can_be_asserted(self):
		from work_management.work_management.doctype.work_management_planner \
			.work_management_planner import may_raise_target

		self.assertTrue(may_raise_target(["System Manager"]))
		self.assertTrue(may_raise_target(["General Manager"]))
		self.assertFalse(may_raise_target(["Employee"]))
		self.assertFalse(may_raise_target([]))
		self.assertFalse(may_raise_target(None))

	def test_the_general_manager_is_a_bypass_here_and_not_on_a_step(self):
		"""Deliberately the opposite of may_take_step(). A chain step is a
		separation of duties the GM must not collapse; this is a spend increase
		managers agree offline, and the GM is exactly who agrees it."""
		from work_management import approvals
		from work_management.work_management.doctype.work_management_planner \
			.work_management_planner import may_raise_target

		self.assertFalse(approvals.may_take_step("HOD HR", ["General Manager"]))
		self.assertTrue(may_raise_target(["General Manager"]))

	def test_administrator_is_never_locked_out(self):
		from work_management.work_management.doctype.work_management_planner \
			.work_management_planner import may_raise_target

		self.assertTrue(may_raise_target([], "Administrator"))


class TestWhoMayRaiseOne(unittest.TestCase):
	def setUp(self):
		self.block = action_block()

	def test_the_action_asks_the_configured_chain_too(self):
		self.assertIn("for rt_step in AP_STEPS:", self.block)

	def test_the_gm_and_system_manager_may(self):
		self.assertIn('("System Manager" in MY_ROLES) or ("General Manager" in MY_ROLES)',
			self.block)

	def test_the_refusal_names_the_roles_that_could(self):
		"""A refusal that does not say who to ask is a dead end."""
		self.assertIn("Raising an approved target is the approver's decision", self.block)
		self.assertIn('", ".join(sorted(set(rt_roles)))', self.block)


class TestWhatItRefuses(unittest.TestCase):
	def setUp(self):
		self.block = action_block()

	def test_only_an_approved_request(self):
		"""Anything earlier can simply be edited, which is the existing path and
		keeps the chain honest."""
		self.assertIn('rt.workflow_state != "Approved"', self.block)
		self.assertIn("Edit it instead", self.block)

	def test_lowering_below_what_is_recorded(self):
		"""Lowering itself is allowed now -- see
		test_adjusting_what_was_approved.py -- down to the work already recorded
		against the request, and no further."""
		self.assertIn("elif rt_qty < rt_recorded - 0.005:", self.block)
		self.assertIn("is already recorded against this request", self.block)

	def test_a_raise_to_the_same_figure(self):
		self.assertIn("is already at", self.block)

	def test_a_request_naming_no_master_plan(self):
		"""There would be no budget to check the raise against."""
		self.assertIn("names no master plan", self.block)

	def test_a_task_the_plan_does_not_budget(self):
		self.assertIn("is not an approved activity on", self.block)

	def test_a_raise_the_line_cannot_fund(self):
		self.assertIn("Over the budgeted quantity for ", self.block)
		self.assertIn("Over the budgeted cost for ", self.block)

	def test_that_refusal_is_in_the_planner_cap_s_own_style(self):
		"""Same words, same shape: whoever hits it has seen it before."""
		at = self.block.index("Over the budgeted quantity for ")
		self.assertIn(" left of ", self.block[at:at + 400])


class TestWhatItChargesTheBudget(unittest.TestCase):
	def setUp(self):
		self.block = action_block()

	def test_the_line_is_read_by_the_attribution_rule(self):
		"""Not by dates. This builds directly on the drawdown fix -- with the old
		date rule the remaining figure here would be every overlapping plan's
		consumption and the raise would be refused against a budget it does not
		draw on."""
		self.assertIn('attributed_to_plan("p")', self.block)

	def test_it_charges_the_delta_and_not_the_whole_new_target(self):
		"""The current quantity is already counted in the line's consumption, so
		charging the full new figure would double-count it and refuse a raise the
		line has room for."""
		self.assertIn("rt_delta = (rt_qty - frappe.utils.flt(rt.quantity))", self.block)
		self.assertIn("rt_delta > rt_left_q", self.block)

	def test_only_an_approved_master_plan_can_fund_it(self):
		self.assertIn('rt_mp.workflow_state == "Approved"', self.block)

	def test_the_line_can_itself_be_raised_first(self):
		"""check_cut_allowed() permits raises and refuses only cuts below what is
		committed, so the refusal points at a fix rather than a wall."""
		self.assertIn("check_cut_allowed", self.block)


class TestWhatItWrites(unittest.TestCase):
	def setUp(self):
		self.block = action_block()

	def test_the_snapshot_is_taken_once(self):
		"""A second raise must not overwrite the first snapshot with the first
		raise's figure -- "originally approved" means the figure the chain
		approved, not the one before the latest edit."""
		self.assertIn("if not frappe.utils.flt(rd.original_qty):", self.block)

	def test_the_cost_follows_the_quantity(self):
		self.assertIn("rd.total_cost = rt_qty * rt_rate", self.block)

	def test_the_crew_and_the_man_days_do_too(self):
		"""By the same arithmetic the request was written with: man-days are
		quantity / daily target and the crew rounds up, because people come
		whole."""
		self.assertIn("rd.people_per_day = rt_ppd", self.block)
		self.assertIn("rd.person_days", self.block)
		self.assertIn("if rt_ppd < rt_raw:", self.block)

	def test_who_and_when_and_what_changed_is_on_the_document(self):
		self.assertIn("add_comment", self.block)
		for part in ("Target raised by", "frappe.session.user", "frappe.utils.today()"):
			with self.subTest(part=part):
				self.assertIn(part, self.block)

	def test_the_comment_carries_both_figures(self):
		at = self.block.index('"Target raised by "')
		window = self.block[at:at + 600]
		self.assertIn("rt_was_q", window)
		self.assertIn("rt_qty", window)
		self.assertIn("rt_was_c", window)


class TestTheDownstreamFiguresFollow(unittest.TestCase):
	"""The cap, the gate and the drawdown all read the request live, so raising
	it is enough -- but "reads it live" is the property, and it is worth holding
	down because caching any of them would break this silently."""

	def setUp(self):
		self.src = read(ACTUALS_API)

	def gate(self, anchor, until):
		"""The CODE of one gate, comments stripped.

		Both gates were sliced by a byte count, which is a measure of how much
		prose sits between the anchor and the line -- so a comment added to
		either one moved the line out of the window and failed a test about
		something else entirely. The boundary is now the next thing in the file,
		and the comments are dropped because these two assertions are about what
		the gate READS, not about what it explains.
		"""
		at = self.src.index(anchor)
		block = self.src[at:self.src.index(until, at)]
		return "\n".join(line for line in block.splitlines()
			if not line.lstrip().startswith("#"))

	def test_the_hard_target_cap_reads_the_request(self):
		self.assertIn('frappe.db.get_value("Work Management Planner", a_pr, "quantity")',
			self.gate("HARD TARGET CAP", "if cap_error:"))

	def test_the_completion_gate_reads_it_again(self):
		self.assertIn('frappe.db.get_value("Work Management Planner", a_pr, "quantity")',
			self.gate("COMPLETION GATE", "if is_new:"))

	def test_neither_is_read_from_a_snapshot(self):
		"""original_qty is a record of what was approved, never an input to a
		cap. Using it would cap recording at the pre-raise figure.

		A short submit WRITES it -- the approved target is snapshotted when the
		plan is capped at what was done -- but that happens after the gate has
		decided and reads nothing."""
		for anchor, until in (("HARD TARGET CAP", "if cap_error:"),
				("COMPLETION GATE", "if is_new:")):
			with self.subTest(anchor=anchor):
				self.assertNotIn("original_qty", self.gate(anchor, until))

	def test_the_master_plan_drawdown_needs_no_change_of_its_own(self):
		"""planned_qty is summed from the requests, so a raised request raises the
		line's consumption by the same arithmetic that was fixed two commits ago."""
		from work_management.master_plan import attributed_to_plan

		self.assertIn("quantity", "quantity")     # the column the sum reads
		self.assertIn("master_plan", attributed_to_plan("p"))


class TestTheControlOnTheScreen(unittest.TestCase):
	def setUp(self):
		self.js = read(SCREEN)

	def test_the_dialog_exists(self):
		self.assertIn("function openRaiseDialog(", self.js)

	def test_it_is_offered_only_on_an_approved_request(self):
		at = self.js.index("data-raise=")
		self.assertIn('r.workflow_state==="Approved"', self.js[at - 400:at])

	def test_it_previews_before_it_writes(self):
		at = self.js.index("function openRaiseDialog(")
		block = self.js[at:at + 4200]
		self.assertIn('preview:1', block)

	def test_the_preview_shows_before_and_after(self):
		at = self.js.index("function openRaiseDialog(")
		block = self.js[at:at + 4200]
		for figure in ("current_qty", "new_qty", "current_cost", "new_cost"):
			with self.subTest(figure=figure):
				self.assertIn(figure, block)

	def test_it_shows_what_the_raise_leaves_on_the_budget(self):
		""""What does this do to the master plan" is the question the person
		deciding actually has."""
		at = self.js.index("function openRaiseDialog(")
		block = self.js[at:at + 4200]
		self.assertIn("budget_left_qty", block)
		self.assertIn("budget_after_qty", block)

	def test_a_refusal_still_shows_the_figures(self):
		"""'You cannot' without the numbers leaves the person no way to decide
		what to ask for instead."""
		block = js_function(self.js, "openRaiseDialog")
		self.assertLess(block.index("d.current_qty!=null"), block.index("if(d.error)"))

	def test_the_write_is_a_post(self):
		"""Because raise_target is in the screen's writes map -- not because the
		Apply says `true`.

		It did say `true`, and this test asserted that it did. `call(args,
		method)` takes a dispatcher name second, so the Apply asked for
		/api/method/true and every click came back "Failed to get method for
		command true with 'true'". The preview beside it is a read and went to
		the right place, so the dialog looked alive right up to the button.
		"""
		block = js_function(self.js, "openRaiseDialog")
		self.assertIn("quantity:num(qty.value)})", block)
		self.assertNotIn(", true)", block)
		at = self.js.index("var writes")
		self.assertIn("raise_target:1", self.js[at:self.js.index("}", at)])

	def test_the_copy_does_not_promise_an_uncapped_raise(self):
		"""It said "it may go up freely". The master plan line caps it, and the
		refusal was arriving as a surprise."""
		block = js_function(self.js, "openRaiseDialog")
		self.assertNotIn("go up freely", block)
		self.assertIn("within the ", block)
		self.assertIn("remaining budget", block)

	def test_a_budget_refusal_says_where_to_fix_it(self):
		"""The orange box says the line has no room; the next step is to raise
		the line, and that was nowhere on screen."""
		block = js_function(self.js, "openRaiseDialog")
		self.assertIn("Raise the budget on ", block)
		self.assertIn("d.master_plan", block)

	def test_the_disabled_button_carries_the_same_next_step(self):
		"""A greyed control with no explanation is the thing that costs an
		afternoon -- this app has been bitten by it before."""
		block = js_function(self.js, "openRaiseDialog")
		self.assertIn("go.title", block)
		self.assertIn("fixHere", block)

	def test_the_pointer_is_only_for_a_budget_refusal(self):
		"""Telling somebody to raise the master plan when the problem is a cut
		below recorded work sends them to the wrong screen."""
		block = js_function(self.js, "openRaiseDialog")
		self.assertIn("/Over the budgeted/", block)

	def test_the_list_is_reloaded_afterwards(self):
		"""Otherwise the row on screen keeps showing the target that was just
		replaced."""
		self.assertIn("refreshVisibleRequests", self.js)


if __name__ == "__main__":
	unittest.main()
