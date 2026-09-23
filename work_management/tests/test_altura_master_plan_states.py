# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Where a master plan waits, asked of the chain rather than named.

Finding #3. `can_edit`, `can_decide`, `can_send_to_gm`, `can_gm_approve`, `save`,
`decide_line`, `decide_bulk`, `send_to_gm` and `reject` all compared
`workflow_state` against the literals `"Pending Consultant"` and `"Pending GM"`.

Altura's master-plan states happen to still be those two, so it half-works there.
That is not a reason to leave it: it is the same fault as the pills and the bulk
bar, armed and waiting for the first site that renames a state -- and for the one
that has already switched the consultant step OFF, where `Pending Consultant` is
a state no document can ever be in and every guard mentioning it is dead code
that silently refuses.

So this drives the resolution against a chain where BOTH are renamed and the
review step is off, which is what api/masterplan.py now resolves from:

    MP_GM_STATE          the enabled step whose approval reaches the end
    MP_CONSULTANT_STATE  the enabled step before it, or None
    MP_STATES_WAITING    the two of them, for "is it under review at all"

    PYTHONPATH=. ~/frappe-bench3/env/bin/python -m unittest \\
        work_management.tests.test_altura_master_plan_states -v
"""

import unittest

from work_management import chain
from work_management.tests import altura

MP = "Work Management Master Plan"


def resolve(rows, states):
	"""The three values api/masterplan.py computes, from the same inputs.

	Written out rather than imported for the reason the close tests give: the
	dispatcher is one function that cannot be entered without a site, so this
	pins the RULE and test_the_screens_speak_the_configured_chain pins that the
	dispatcher uses it and names neither state.
	"""
	terminal = states["terminal"]
	gm_step = None
	review_step = None
	for step in chain.approval_steps(rows, MP, enabled_only=True):
		if step.get("next_state") == terminal:
			gm_step = step
		elif review_step is None:
			review_step = step
	gm_state = (gm_step or {}).get("state")
	review_state = (review_step or {}).get("state")
	return {
		"gm_step": gm_step,
		"review_step": review_step,
		"gm_state": gm_state,
		"review_state": review_state,
		"waiting": [s for s in (review_state, gm_state) if s],
	}


def shipped_rows():
	"""The chain as it ships, for the control case."""
	from work_management import approvals

	return approvals.effective_chain(settings=None)


class TestTheShippedChainStillResolvesToItsOwnNames(unittest.TestCase):
	"""The control. If this failed, the new resolution would be changing
	behaviour on every existing site rather than generalising it."""

	def setUp(self):
		from work_management import approvals

		self.r = resolve(shipped_rows(), approvals.pipeline_states(
			settings=None, document_type=MP))

	def test_the_final_step_is_the_gm_step(self):
		self.assertEqual(self.r["gm_step"]["key"], "masterplan_gm")
		self.assertEqual(self.r["gm_state"], "Pending GM")

	def test_the_step_before_it_is_the_consultant(self):
		self.assertEqual(self.r["review_step"]["key"], "masterplan_consultant")
		self.assertEqual(self.r["review_state"], "Pending Consultant")

	def test_both_are_what_the_guards_used_to_compare_against(self):
		self.assertEqual(self.r["waiting"], ["Pending Consultant", "Pending GM"])


class TestAlturaRenamesBothAndSwitchesReviewOff(unittest.TestCase):
	def setUp(self):
		self.r = resolve(altura.chain_rows(), altura.states(MP))

	def test_neither_shipped_state_survives(self):
		self.assertNotIn("Pending GM", self.r["waiting"])
		self.assertNotIn("Pending Consultant", self.r["waiting"])

	def test_the_final_step_is_found_by_position_not_by_name(self):
		self.assertEqual(self.r["gm_step"]["key"], "masterplan_gm")
		self.assertEqual(self.r["gm_state"], "With the manager")

	def test_there_is_no_review_step_because_it_is_switched_off(self):
		"""`Budget: Review` is off, so no plan ever waits there -- and every
		guard that compared against `Pending Consultant` was refusing on a state
		that cannot occur."""
		self.assertIn("masterplan_consultant", altura.OFF)
		self.assertIsNone(self.r["review_step"])
		self.assertIsNone(self.r["review_state"])

	def test_only_one_state_is_a_waiting_state(self):
		self.assertEqual(self.r["waiting"], ["With the manager"])

	def test_submitting_goes_straight_to_the_manager(self):
		"""With the review step off the chain relinks through it, which is what
		makes `decide_line`'s guard unreachable rather than merely wrong."""
		submit = [s for s in altura.chain_rows(MP) if s["kind"] == "Submit"][0]
		self.assertEqual(submit["next_state"], "With the manager")

	def test_an_unset_state_never_matches_the_absent_review_step(self):
		"""The trap in resolving to None: `state == MP_CONSULTANT_STATE` is TRUE
		for a document whose workflow_state is empty. Every comparison in
		api/masterplan.py is guarded by `bool(MP_CONSULTANT_STATE) and ...`, and
		this is that guard stated as a fact."""
		for blank in (None, ""):
			with self.subTest(state=blank):
				self.assertFalse(bool(self.r["review_state"]) and blank == self.r["review_state"])

	def test_philip_decides_the_budget(self):
		self.assertIsNone(chain.may_take(self.r["gm_step"], [altura.MANAGER]))

	def test_the_shipped_gm_role_does_not(self):
		"""`CAN_GM` is `STAGE_ROLE["masterplan_gm"] in roles`, which was already
		configured -- so this is the half that was right, asserted so the state
		fix cannot quietly undo it."""
		self.assertIsNotNone(chain.may_take(self.r["gm_step"], ["General Manager"]))


class TestTheLabelsAreWhatARefusalShouldName(unittest.TestCase):
	"""`save` refused with "This plan is with the consultants" and "with the
	general manager" whatever the chain said, which sent an Altura reader to a
	desk the site has not got."""

	def test_the_final_step_has_altura_s_own_label(self):
		r = resolve(altura.chain_rows(), altura.states(MP))
		self.assertEqual(chain.label_of(r["gm_step"]), "Budget: Manager")

	def test_an_absent_review_step_still_has_a_word(self):
		r = resolve(altura.chain_rows(), altura.states(MP))
		self.assertEqual(chain.label_of(r["review_step"], "review"), "review")


if __name__ == "__main__":
	unittest.main()
