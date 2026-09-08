"""The Planner's second approval step, and the fact that it ships switched off.

Every other chain could be pointed at Altura's target by switching steps off and
swapping roles. The Planner could not: it had ONE approval step, and the target is
two -- the section head raises, the farm manager approves, HR approves after them.
So a step joins the catalogue, which is a different kind of change from the rest
of this work, because a catalogue entry reaches every installation that migrates.

That is what `default_off` is for. seed_stages() gives a row it has never seen
`enabled = 1`, which is correct for the fourteen steps that describe how this
pipeline has always run and wrong for a fifteenth nobody asked for: an existing
site would migrate and find a new approval standing between its planners and
their work. Off, `effective_chain()` relinks Farm Approval straight to Approved
and every existing chain reads exactly as it did.

The role is System Manager, not HOD HR. HOD HR is one of the five job titles this
app was deliberately stopped from inventing (test_no_shipped_roles), and a
Workflow Transition's role is a Link -- so a default naming a role the site may
not have breaks the generated workflow's save. Altura points the step at HOD HR
in Settings, beside the rest of its chain.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_the_planner_takes_a_second_approval -v
"""

import unittest

from work_management import approvals

PLANNER = "Work Management Planner"
TERMINAL = approvals.CHAIN_ENDS[PLANNER]["terminal"][0]

FARM_APPROVAL = "planner_farm_approval"
HR_APPROVAL = "planner_hr_approval"


class Row(dict):
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


def shipped(key):
	for stage in approvals.CATALOGUE:
		if stage.key == key:
			return stage
	raise AssertionError("no such shipped stage: " + key)


def planner_chain(**enabled):
	"""The Planner's shipped steps as Settings rows, with `enabled` overridden."""
	rows = []
	idx = 0
	for stage in approvals.CATALOGUE:
		if stage.document_type != PLANNER:
			continue
		idx += 1
		rows.append(Row({
			"stage": stage.key, "stage_label": stage.label, "idx": idx,
			"document_type": stage.document_type, "kind": stage.kind,
			"state": stage.state, "action": stage.action,
			"scoped": 1 if stage.scoped else 0,
			"required": 1 if stage.required else 0,
			"role": stage.role,
			"enabled": enabled.get(stage.key, 0 if stage.default_off else 1),
		}))
	return Settings(rows)


def resolved(settings):
	return {row["key"]: row
		for row in approvals.effective_chain(settings, document_type=PLANNER)}


class TestTheStepIsInTheCatalogue(unittest.TestCase):
	def test_it_sits_after_the_farm_approval(self):
		"""Order is position, so "after" is the whole of what makes it second."""
		keys = [s.key for s in approvals.CATALOGUE if s.document_type == PLANNER]
		self.assertEqual(keys, ["planner_submit", FARM_APPROVAL, HR_APPROVAL])

	def test_it_is_an_approval_with_its_own_state_and_action(self):
		stage = shipped(HR_APPROVAL)
		self.assertEqual(stage.kind, "Approval")
		self.assertEqual(stage.state, "Pending HR Approval")
		self.assertEqual(stage.action, "HR Approve")
		self.assertFalse(stage.required, "an approval step must stay switchable")

	def test_its_state_is_not_one_another_step_already_waits_in(self):
		"""Two steps sharing a state would make "what waits here" unanswerable."""
		states = [s.state for s in approvals.CATALOGUE
			if s.document_type == PLANNER and s.state]
		self.assertEqual(len(states), len(set(states)), states)

	def test_it_is_not_farm_scoped(self):
		"""HR approves for the business, not per farm -- the farm dimension is
		already carried by the step before it."""
		self.assertFalse(shipped(HR_APPROVAL).scoped)

	def test_it_ships_off(self):
		self.assertTrue(shipped(HR_APPROVAL).default_off)

	def test_it_is_the_only_step_that_ships_off(self):
		"""Everything else in the catalogue describes how the pipeline runs today."""
		off = [s.key for s in approvals.CATALOGUE if s.default_off]
		self.assertEqual(off, [HR_APPROVAL])

	def test_it_defaults_to_a_role_frappe_guarantees(self):
		self.assertEqual(shipped(HR_APPROVAL).role, "System Manager")

	def test_the_approver_picker_offers_it(self):
		"""The Stage Approvers row stores a LABEL, so an option it cannot name is
		a step nobody can be assigned to."""
		self.assertIn(shipped(HR_APPROVAL).label, approvals.stage_labels())


class TestWithTheStepOff(unittest.TestCase):
	"""The property that made this safe to add: nothing moves."""

	def setUp(self):
		self.by_key = resolved(planner_chain())

	def test_farm_approval_still_leads_straight_to_approved(self):
		self.assertEqual(self.by_key[FARM_APPROVAL]["next_state"], TERMINAL)

	def test_submitting_still_lands_on_the_farm_approval(self):
		self.assertEqual(self.by_key["planner_submit"]["next_state"],
			shipped(FARM_APPROVAL).state)

	def test_the_step_is_still_returned_so_its_action_can_refuse(self):
		"""A disabled step stays in the chain with `on` false: the screens need to
		know it exists, or its action writes a state nothing is waiting in."""
		self.assertIn(HR_APPROVAL, self.by_key)
		self.assertEqual(self.by_key[HR_APPROVAL]["on"], 0)

	def test_the_disabled_step_still_points_forward(self):
		"""A document somehow sitting in it can be moved on, not stranded."""
		self.assertEqual(self.by_key[HR_APPROVAL]["next_state"], TERMINAL)


class TestWithTheStepOn(unittest.TestCase):
	def setUp(self):
		self.by_key = resolved(planner_chain(**{HR_APPROVAL: 1}))

	def test_both_approvals_are_now_required(self):
		self.assertEqual(self.by_key[FARM_APPROVAL]["on"], 1)
		self.assertEqual(self.by_key[HR_APPROVAL]["on"], 1)

	def test_the_farm_approval_now_leads_to_hr_not_to_approved(self):
		self.assertEqual(self.by_key[FARM_APPROVAL]["next_state"],
			shipped(HR_APPROVAL).state)
		self.assertNotEqual(self.by_key[FARM_APPROVAL]["next_state"], TERMINAL)

	def test_hr_is_what_finishes_the_chain(self):
		self.assertEqual(self.by_key[HR_APPROVAL]["next_state"], TERMINAL)

	def test_the_two_steps_run_on_the_roles_configured_for_them(self):
		"""Altura's target: the farm manager approves, then HR."""
		settings = planner_chain(**{HR_APPROVAL: 1})
		for row in settings["approval_stages"]:
			if row["stage"] == FARM_APPROVAL:
				row["role"] = "Farm Manager"
			elif row["stage"] == HR_APPROVAL:
				row["role"] = "HOD HR"
		by_key = resolved(settings)
		self.assertEqual(by_key[FARM_APPROVAL]["role"], "Farm Manager")
		self.assertEqual(by_key[HR_APPROVAL]["role"], "HOD HR")

	def test_a_step_with_no_role_refuses_everybody(self):
		"""A misconfigured gate closes. An empty Role is visible in Settings; a
		silently open approval is not."""
		self.assertFalse(approvals.may_take_step(None, ["HOD HR", "System Manager"]))

	def test_hr_may_take_it_and_a_farm_manager_may_not(self):
		self.assertTrue(approvals.may_take_step("HOD HR", ["HOD HR"]))
		self.assertFalse(approvals.may_take_step("HOD HR", ["Farm Manager"]))

	def test_switching_the_farm_approval_off_instead_leaves_hr_alone_in_the_chain(self):
		by_key = resolved(planner_chain(**{FARM_APPROVAL: 0, HR_APPROVAL: 1}))
		self.assertEqual(by_key["planner_submit"]["next_state"],
			shipped(HR_APPROVAL).state)
		self.assertEqual(by_key[HR_APPROVAL]["next_state"], TERMINAL)


class TestReadsStillMatchEveryState(unittest.TestCase):
	"""pipeline_states() is deliberately not symmetric with the write chain: a
	list filter must not narrow because somebody changed a setting."""

	def test_the_new_state_is_readable_whether_the_step_is_on_or_off(self):
		for enabled in (0, 1):
			with self.subTest(enabled=enabled):
				states = approvals.pipeline_states(
					planner_chain(**{HR_APPROVAL: enabled}), document_type=PLANNER)
				# the buckets a list filter actually reads
				self.assertIn("Pending HR Approval", states["all"])
				self.assertIn("Pending HR Approval", states["waiting"])
				self.assertIn("Pending HR Approval", states["open"])

	def test_the_write_chain_does_narrow_when_the_step_is_off(self):
		"""The asymmetry itself: reads keep the state, writes skip the step."""
		off = resolved(planner_chain())
		on = resolved(planner_chain(**{HR_APPROVAL: 1}))
		self.assertEqual(off[FARM_APPROVAL]["next_state"], TERMINAL)
		self.assertEqual(on[FARM_APPROVAL]["next_state"], "Pending HR Approval")


class TestSeedingAnExistingSite(unittest.TestCase):
	"""The migrate-day question: what does a site that has never seen this step get?"""

	def test_seed_stages_writes_a_new_default_off_row_switched_off(self):
		source = open(approvals.__file__).read()
		block = source[source.index("def seed_stages"):]
		block = block[:block.index("\ndef ")]
		self.assertIn("0 if stage.default_off else 1", block,
			"a step joining the catalogue would switch itself on across every "
			"existing installation")

	def test_a_row_already_present_keeps_its_own_answer(self):
		"""Turning it ON must survive the next migrate."""
		source = open(approvals.__file__).read()
		block = source[source.index("def seed_stages"):]
		block = block[:block.index("\ndef ")]
		self.assertIn("previous.enabled if previous else", block)

	def test_an_unknown_step_is_still_honoured_as_written(self):
		"""configured_stages() reads rows the catalogue never shipped, and such a
		row has no `default_off` to fall back to."""
		rows = [Row({"stage": "finance_signoff", "stage_label": "Planner: Finance",
			"idx": 1, "document_type": PLANNER, "kind": "Approval",
			"state": "Pending Finance", "action": "Sign off", "enabled": 1,
			"role": "Accounts Manager"})]
		chain = approvals.configured_stages(Settings(rows))
		self.assertEqual([s.key for s in chain], ["finance_signoff"])
		self.assertFalse(chain[0].default_off)
