"""One answer to "what comes after this step", shared by the workflow and the screens.

The **On** checkbox against each approval step already worked for the desk
workflow: `plan_workflow()` drops a disabled step and joins its neighbours. The
five web screens did not honour it at all -- they had the chain written into them
as literal state names, 189 mentions across six scripts. So switching off
`Assigner: HR Head` sent the generated workflow to `Pending GM` while the screen
still wrote `Pending HR Head`, a state the regenerated workflow no longer
contained, and the document stranded.

Two implementations of one rule is the bug. So the rule lives here once:
`effective_chain()` resolves, for every step, the state it waits in and the state
approving it leads to. `plan_workflow()` and `get_config()` both read it, so the
desk and the screens cannot disagree again.

`pipeline_states()` is the other half, and it is deliberately *not* symmetric.
Writes follow the enabled chain; reads match every state a document could be
carrying, switched off or not, so a list filter cannot make documents disappear
because somebody changed a setting.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_effective_chain -v
"""

import unittest

from work_management import approvals

ASSIGNER = "Work Management Assigner"
# What CHAIN_ENDS says the Assigner finishes as, so the tests below assert
# against the shipped value rather than restating it.
TERMINAL = approvals.CHAIN_ENDS[ASSIGNER]["terminal"][0]


class Row(dict):
	"""A Settings child row, as frappe hands one over."""

	def __getattr__(self, name):
		try:
			return self[name]
		except KeyError:
			return None


class Settings(dict):
	def __init__(self, stage_rows):
		super().__init__(approval_stages=stage_rows)

	def get(self, key, default=None):
		return dict.get(self, key, default)


def chain(*specs):
	"""Build a settings doc holding these steps, in this order."""
	out = []
	for i, spec in enumerate(specs, 1):
		row = Row(spec)
		row.setdefault("idx", i)
		row.setdefault("document_type", ASSIGNER)
		row.setdefault("kind", "Approval")
		row.setdefault("enabled", 1)
		row.setdefault("stage_label", row.get("stage"))
		out.append(row)
	return Settings(out)


def step(key, state, action="Approve", **extra):
	spec = {"stage": key, "state": state, "action": action}
	spec.update(extra)
	return spec


FULL = (
	step("assigner_submit", "Draft", "Submit for Approval", kind="Submit", required=1),
	step("assigner_farm_manager", "Pending Farm Manager", "FM Approve"),
	step("assigner_hr_head", "Pending HR Head", "HR Approve"),
	step("assigner_gm", "Pending GM", "GM Approve"),
)


def resolved(*specs):
	return {row["key"]: row for row in approvals.effective_chain(chain(*specs))}


class TestTheWholeChainOn(unittest.TestCase):
	def setUp(self):
		self.by_key = resolved(*FULL)

	def test_every_step_is_present(self):
		self.assertEqual(len(self.by_key), 4)

	def test_each_step_knows_the_state_it_waits_in(self):
		self.assertEqual(self.by_key["assigner_hr_head"]["state"], "Pending HR Head")

	def test_each_step_leads_to_the_next(self):
		self.assertEqual(
			self.by_key["assigner_farm_manager"]["next_state"], "Pending HR Head")
		self.assertEqual(
			self.by_key["assigner_hr_head"]["next_state"], "Pending GM")

	def test_the_last_step_leads_to_the_terminal_state(self):
		self.assertEqual(self.by_key["assigner_gm"]["next_state"], TERMINAL)

	def test_the_submit_step_leads_into_the_chain(self):
		self.assertEqual(
			self.by_key["assigner_submit"]["next_state"], "Pending Farm Manager")

	def test_every_step_reports_itself_on(self):
		self.assertTrue(all(row["on"] for row in self.by_key.values()))


class TestAStepInTheMiddleSwitchedOff(unittest.TestCase):
	"""The case that stranded documents: HR Head off between FM and GM."""

	def setUp(self):
		self.by_key = resolved(
			FULL[0], FULL[1],
			step("assigner_hr_head", "Pending HR Head", "HR Approve", enabled=0),
			FULL[3])

	def test_the_step_before_it_skips_straight_past(self):
		self.assertEqual(
			self.by_key["assigner_farm_manager"]["next_state"], "Pending GM")

	def test_the_disabled_step_is_still_reported(self):
		"""The screens need to know it exists and is off, so its action can
		refuse rather than silently writing a state nothing waits in."""
		self.assertIn("assigner_hr_head", self.by_key)
		self.assertFalse(self.by_key["assigner_hr_head"]["on"])

	def test_a_disabled_step_still_points_forward(self):
		"""So a document somehow sitting in it can still be moved on, rather
		than being stuck because its step was switched off underneath it."""
		self.assertEqual(self.by_key["assigner_hr_head"]["next_state"], "Pending GM")


class TestTwoConsecutiveStepsOff(unittest.TestCase):
	def setUp(self):
		self.by_key = resolved(
			FULL[0], FULL[1],
			step("assigner_hr_head", "Pending HR Head", "HR Approve", enabled=0),
			step("assigner_gm", "Pending GM", "GM Approve", enabled=0))

	def test_the_chain_jumps_both(self):
		self.assertEqual(self.by_key["assigner_farm_manager"]["next_state"], TERMINAL)

	def test_both_disabled_steps_point_at_the_terminal_state(self):
		self.assertEqual(self.by_key["assigner_hr_head"]["next_state"], TERMINAL)
		self.assertEqual(self.by_key["assigner_gm"]["next_state"], TERMINAL)


class TestTheLastStepOff(unittest.TestCase):
	def test_the_step_before_becomes_the_last(self):
		by_key = resolved(FULL[0], FULL[1], FULL[2],
			step("assigner_gm", "Pending GM", "GM Approve", enabled=0))
		self.assertEqual(by_key["assigner_hr_head"]["next_state"], TERMINAL)


class TestEveryOptionalStepOff(unittest.TestCase):
	def test_submit_leads_straight_to_the_terminal_state(self):
		"""Nobody approves anything: submitting completes the document. Worth
		allowing rather than refusing -- a site may genuinely not review this
		pipeline -- and worth testing because it is the degenerate case where an
		off-by-one in the resolution shows up."""
		by_key = resolved(
			FULL[0],
			step("assigner_farm_manager", "Pending Farm Manager", "FM Approve", enabled=0),
			step("assigner_hr_head", "Pending HR Head", "HR Approve", enabled=0),
			step("assigner_gm", "Pending GM", "GM Approve", enabled=0))
		self.assertEqual(by_key["assigner_submit"]["next_state"], TERMINAL)


class TestARequiredStepIsNeverOff(unittest.TestCase):
	def test_the_row_saying_off_does_not_switch_it_off(self):
		"""Submit steps and Payment: Accounts are structural. `is_enabled()`
		already ignores the row for those, and this must not diverge from it."""
		by_key = resolved(
			step("assigner_submit", "Draft", "Submit for Approval",
				kind="Submit", required=1, enabled=0),
			FULL[1])
		self.assertTrue(by_key["assigner_submit"]["on"])
		self.assertEqual(by_key["assigner_submit"]["next_state"], "Pending Farm Manager")


class TestTheChainIsJsonSafe(unittest.TestCase):
	"""It travels through get_config() into a Server Script, so it has to survive
	being serialised -- no namedtuples, no Frappe objects."""

	def test_it_is_plain_lists_and_dicts(self):
		import json

		out = approvals.effective_chain(chain(*FULL))
		self.assertEqual(json.loads(json.dumps(out)), out)

	def test_each_row_carries_what_a_screen_needs(self):
		for row in approvals.effective_chain(chain(*FULL)):
			for field in ("key", "document_type", "state", "action", "next_state", "on"):
				self.assertIn(field, row)


class TestStatesAReadShouldMatch(unittest.TestCase):
	"""Reads are permissive on purpose. A document that passed through a step
	which was later switched off must not vanish from a list because the filter
	stopped naming its state.

	Note this is the union of every *known* state, not of states found in the
	data -- so it needs no query, and it cannot be wrong the way a snapshot of
	the data could be.

	Grouped, because the screens' filters mean different things. A flat list of
	everything would silently widen `IN (...)` to include drafts and rejects,
	which is how a "live work" list starts showing abandoned drafts.
	"""

	def states(self, *specs):
		return approvals.pipeline_states(chain(*specs), document_type=ASSIGNER)

	def test_all_includes_a_switched_off_step(self):
		states = approvals.pipeline_states(
			chain(FULL[0], FULL[1],
				step("assigner_hr_head", "Pending HR Head", "HR Approve", enabled=0),
				FULL[3]),
			document_type=ASSIGNER)
		self.assertIn("Pending HR Head", states["all"])

	def test_waiting_includes_a_switched_off_step_too(self):
		"""A read must still find a document parked in a retired state."""
		states = approvals.pipeline_states(
			chain(FULL[0], FULL[1],
				step("assigner_hr_head", "Pending HR Head", "HR Approve", enabled=0),
				FULL[3]),
			document_type=ASSIGNER)
		self.assertIn("Pending HR Head", states["waiting"])

	def test_all_includes_the_terminal_and_reject_states(self):
		states = self.states(*FULL)
		self.assertIn(TERMINAL, states["all"])
		self.assertIn(approvals.CHAIN_ENDS[ASSIGNER]["reject"], states["all"])

	def test_waiting_is_the_approval_steps_only(self):
		states = self.states(*FULL)
		self.assertEqual(states["waiting"],
			["Pending Farm Manager", "Pending HR Head", "Pending GM"])

	def test_waiting_excludes_draft_and_the_terminal_state(self):
		states = self.states(*FULL)
		self.assertNotIn("Draft", states["waiting"])
		self.assertNotIn(TERMINAL, states["waiting"])

	def test_active_is_waiting_plus_the_terminal_state(self):
		"""What the screens' IN lists have always meant: submitted, not rejected."""
		states = self.states(*FULL)
		self.assertEqual(states["active"],
			["Pending Farm Manager", "Pending HR Head", "Pending GM", TERMINAL])

	def test_active_excludes_draft_and_rejected(self):
		states = self.states(*FULL)
		self.assertNotIn("Draft", states["active"])
		self.assertNotIn("Rejected", states["active"])

	def test_open_is_everything_still_editable(self):
		states = self.states(*FULL)
		self.assertIn("Draft", states["open"])
		self.assertIn("Rejected", states["open"])
		self.assertIn("Pending GM", states["open"])
		self.assertNotIn(TERMINAL, states["open"])

	def test_the_individual_states_are_named(self):
		states = self.states(*FULL)
		self.assertEqual(states["draft"], "Draft")
		self.assertEqual(states["terminal"], TERMINAL)
		self.assertEqual(states["reject"], approvals.CHAIN_ENDS[ASSIGNER]["reject"])

	def test_it_is_scoped_to_the_document_type_asked_about(self):
		mixed = chain(
			FULL[1],
			step("planner_farm_approval", "Pending Approval",
				document_type="Work Management Planner"))
		self.assertNotIn("Pending Approval",
			approvals.pipeline_states(mixed, document_type=ASSIGNER)["all"])
		self.assertIn("Pending Approval",
			approvals.pipeline_states(
				mixed, document_type="Work Management Planner")["all"])

	def test_no_duplicates_and_a_stable_order(self):
		states = self.states(*FULL)
		for group in ("waiting", "active", "open", "all"):
			self.assertEqual(len(states[group]), len(set(states[group])), group)
		self.assertEqual(states, self.states(*FULL))


class TestTheWorkflowGeneratorUsesTheSameRule(unittest.TestCase):
	"""The point of the helper. If `plan_workflow` kept its own resolution, the
	two could drift apart again -- which is the bug being fixed."""

	def test_plan_workflow_calls_the_shared_helper(self):
		import inspect

		source = inspect.getsource(approvals.plan_workflow)
		self.assertIn("effective_chain", source)

	def test_it_no_longer_resolves_the_next_state_itself(self):
		import inspect

		source = inspect.getsource(approvals.plan_workflow)
		self.assertNotIn("chain[index + 1].state", source)


if __name__ == "__main__":
	unittest.main()
