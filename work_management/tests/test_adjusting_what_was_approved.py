"""An approved figure can move — within the limits that keep it honest.

The client: *"adjust a master plan already in the system for specific periods"*
and *"flexibility in adjusting the number of people already planned for a
specific task and targets for the day."*

**A request's target now goes down as well as up.** The floor is the work
already recorded against it -- the very sum the actuals HARD TARGET CAP counts
against the target, so the floor here and the ceiling there are one number.
Below it, recorded work exceeds its own target and the plan can never reach 100%
and therefore never be submitted. Down to exactly what is recorded is how a plan
that over-asked gets closed honestly. Lowering frees the master plan line by
arithmetic: the line's consumption is summed from the requests drawn against it.

**An approved master plan's period can move**, which it already could -- what it
could not do was say so, or refuse the moves that strand somebody. The guard now
covers every request THIS PLAN is charged for rather than only ones whose task
happened to be in the edit, and catches requests that straddle the new edge
rather than only ones entirely outside it.

Measured on kentrout.local, plan 2027-01-04 → 01-31 with a request for
2027-01-11 → 01-13:

    lower 30 -> 10, nothing recorded   allowed; line 30/370 -> 10/390
    6 units confirmed, lower to 6      allowed
    lower to 3                         refused, naming the 6
    lower to 2 from the DESK           refused identically
    period -> 01-04 → 01-12            refused, naming the request and its dates
    period -> 01-12 → 01-31            refused (the leading edge strands it too)
    period -> 01-04 → 01-20            allowed, and audited:
                                       "period to 2027-01-31 → 2027-01-20"

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_adjusting_what_was_approved -v
"""

import os
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLANNER_API = os.path.join(APP, "api", "planner.py")
MP_API = os.path.join(APP, "api", "masterplan.py")
CONTROLLER = os.path.join(APP, "work_management", "doctype",
	"work_management_planner", "work_management_planner.py")
SCREEN = os.path.join(APP, "public", "js", "work-planner.js")


def read(path):
	with open(path) as handle:
		return handle.read()


def adjust_block():
	src = read(PLANNER_API)
	at = src.index('elif action in ("raise_target", "adjust_target"):')
	return src[at:src.index('elif action == "approve":', at)]


class TestTheFloorIsWhatIsRecorded(unittest.TestCase):
	def setUp(self):
		self.controller = read(CONTROLLER)

	def test_the_floor_is_a_shared_function(self):
		"""The action and the desk path must agree about it, or one of them lets
		through what the other refuses."""
		self.assertIn("def recorded_quantity(", self.controller)

	def test_it_is_the_same_sum_the_actuals_cap_counts(self):
		at = self.controller.index("def recorded_quantity(")
		block = self.controller[at:at + 1200]
		self.assertIn("SUM(ac.total_actual_qty)", block)
		self.assertIn("a.planner_request = %(p)s", block)

	def test_work_in_flight_counts(self):
		"""Work at Pending HR Head is recorded work whose document is not
		finished. A cut underneath it would strand it."""
		at = self.controller.index("def recorded_quantity(")
		block = self.controller[at:at + 1200]
		for state in ("Pending HR Head", "Pending GM", "CONFIRMED"):
			with self.subTest(state=state):
				self.assertIn(state, block)

	def test_the_action_uses_it(self):
		self.assertIn("rt_recorded", adjust_block())

	def test_the_controller_uses_it(self):
		at = self.controller.index("def on_update_after_submit")
		self.assertIn("recorded_quantity(self.name)", self.controller[at:at + 1600])


class TestLoweringIsAllowedDownToThatFloor(unittest.TestCase):
	def setUp(self):
		self.block = adjust_block()
		self.controller = read(CONTROLLER)

	def test_the_action_no_longer_refuses_every_cut(self):
		self.assertNotIn("A target can only be raised here, not lowered", self.block)

	def test_it_refuses_below_the_floor(self):
		self.assertIn("elif rt_qty < rt_recorded - 0.005:", self.block)

	def test_the_refusal_names_the_figure_and_what_to_do(self):
		at = self.block.index("elif rt_qty < rt_recorded - 0.005:")
		msg = self.block[at:at + 900]
		self.assertIn("is already recorded against this request", msg)
		self.assertIn("Lower it to ", msg)

	def test_the_desk_path_refuses_the_same_way(self):
		"""allow_on_submit opens the form too, where the action's gate does not
		run -- so the rule lives on the document."""
		self.assertIn("if now < floor - TOLERANCE:", self.controller)
		self.assertIn("cannot go below", self.controller)

	def test_the_budget_ceiling_only_applies_to_an_increase(self):
		"""A cut cannot exceed a line's remaining budget -- it gives budget
		back -- and checking it against a negative delta would refuse every
		lowering on a fully-committed line."""
		self.assertIn("elif rt_delta > 0 and rt_delta > rt_left_q", self.block)
		self.assertIn("elif rt_delta > 0 and rt_delta * rt_rate > rt_left_c", self.block)

	def test_the_audit_comment_reads_either_way(self):
		self.assertIn('"Target raised by " if rt_qty > rt_was_q else "Target lowered by "',
			self.block)

	def test_the_direction_comes_back_for_the_screen(self):
		self.assertIn('out["direction"]', self.block)

	def test_the_role_gate_is_unchanged(self):
		"""Adjusting is still the approver's decision, in both directions."""
		self.assertIn("rt_may", self.block)
		self.assertIn("may_raise_target(frappe.get_roles(), frappe.session.user)",
			self.controller)

	def test_the_snapshot_is_still_taken_once(self):
		self.assertIn("if not frappe.utils.flt(rd.original_qty):", self.block)


class TestTheScreenSaysBothDirections(unittest.TestCase):
	def setUp(self):
		self.js = read(SCREEN)

	def test_the_control_is_no_longer_called_raise(self):
		self.assertIn("Adjust target", self.js)

	def test_the_dialog_says_what_the_limit_is(self):
		self.assertIn("down to what has already been recorded", self.js)

	def test_the_floor_is_shown(self):
		self.assertIn("floor_qty", read(PLANNER_API))
		self.assertIn("recorded_qty", self.js)

	def test_the_toast_names_the_direction(self):
		self.assertIn('d.direction==="down"?"lowered":"raised"', self.js)


class TestTheMasterPlanPeriodEdit(unittest.TestCase):
	def setUp(self):
		self.src = read(MP_API)
		at = self.src.index("NARROWING THE PERIOD STRANDS")
		self.block = self.src[at:at + 3000]

	def test_it_checks_every_request_this_plan_is_charged_for(self):
		"""Not only ones whose task happened to be in the edit -- a request for
		an untouched line is stranded just as thoroughly."""
		self.assertIn('attributed_to_plan("p")', self.block)

	def test_it_catches_a_request_that_straddles_the_new_edge(self):
		"""Starting inside and ending after is exactly as uncontained, and the
		planner would refuse to raise it against these dates."""
		self.assertIn("NOT (p.from_date >= %(nfrom)s AND p.to_date <= %(nto)s)", self.block)

	def test_it_fires_on_widening_as_well_as_narrowing(self):
		"""Moving the start forward strands the same way."""
		self.assertIn('str(sv_from) != str(sv_old.period_from) or', self.block)
		self.assertIn('str(sv_to) != str(sv_old.period_to)', self.block)

	def test_the_refusal_names_the_offending_requests_and_their_dates(self):
		self.assertIn("would no longer cover", self.block)
		self.assertIn("x.from_date", self.block)

	def test_it_does_not_list_them_all_forever(self):
		self.assertIn("sv_lost[:6]", self.block)
		self.assertIn("and more", self.block)

	def test_the_period_change_is_audited(self):
		"""Only activity lines were ever recorded, so an approved plan could have
		its dates moved and the document said nothing -- the one edit most likely
		to strand somebody's week."""
		at = self.src.index("THE PERIOD ITSELF, when it moves")
		block = self.src[at:at + 900]
		self.assertIn('sv_changed.append("period from "', block)
		self.assertIn('sv_changed.append("period to "', block)

	def test_that_audit_reaches_the_document(self):
		self.assertIn('"; ".join(sv_changed)', self.src)
		at = self.src.index('"; ".join(sv_changed)')
		self.assertIn("add_comment", self.src[at - 500:at])


class TestWhatThisDidNotChange(unittest.TestCase):
	def setUp(self):
		self.src = read(MP_API)

	def test_who_may_edit_an_approved_plan_is_untouched(self):
		"""A named-user list in Settings, deliberately: its own description says
		"System Manager is deliberately not swept in". Widening that to a role
		reverses somebody's explicit decision about who may change an approved
		budget, so it is asked rather than assumed."""
		self.assertIn("master_plan_post_approval_editors", self.src)
		self.assertIn("CAN_EDIT_APPROVED = 1 if frappe.session.user.lower() in mp_post else 0",
			self.src)

	def test_activity_lines_still_follow_check_cut_allowed(self):
		"""Raises permitted, cuts below what is committed refused -- already
		true, and this does not rewrite it."""
		self.assertIn("is already planned at", self.src)
		self.assertIn("cannot be cut to", self.src)

	def test_the_line_cut_guard_still_names_who_holds_the_budget(self):
		self.assertIn("Held by ", self.src)


if __name__ == "__main__":
	unittest.main()
