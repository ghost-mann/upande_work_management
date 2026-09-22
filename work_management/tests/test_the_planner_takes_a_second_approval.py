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

import os
import re
import unittest

from work_management import approvals

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLANNER_API = os.path.join(APP, "api", "planner.py")
PLANNER_JS = os.path.join(APP, "public", "js", "work-planner.js")


def read(path):
	with open(path) as handle:
		return handle.read()

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


# --------------------------------------------------------------------------
# The other half: the step reaches the screen, not only the desk.
# --------------------------------------------------------------------------


class TestTheChainSaysWhichDimensionGatesAStep(unittest.TestCase):
	"""A screen deciding whether to offer an approve button has to know which
	question to ask. A farm-scoped step asks "which farms may you decide"; an
	unscoped one asks "do you hold this step's role". Asking the wrong one
	refuses everybody or nobody -- and without `scoped` on the chain row, the
	screens had to recognise the step by key, which is the hardcoding the
	configurable chain exists to remove."""

	def test_every_step_carries_it(self):
		for step in approvals.effective_chain(settings=None):
			with self.subTest(step=step["key"]):
				self.assertIn("scoped", step)

	def test_the_farm_approval_is_scoped_and_the_hr_one_is_not(self):
		by_key = resolved(planner_chain(**{HR_APPROVAL: 1}))
		self.assertTrue(by_key[FARM_APPROVAL]["scoped"])
		self.assertFalse(by_key[HR_APPROVAL]["scoped"],
			"HR approves for the business; the farm dimension is already carried "
			"by the step before it")


class TestTheApproveActionReadsTheChain(unittest.TestCase):
	"""It named planner_farm_approval and nothing else, which WAS the whole chain
	while the Planner had one approval. Switch a second one on and the request
	reached Pending HR Approval and stopped: the generated desk workflow moved it
	correctly, and the screen -- where the work happens -- had no button."""

	def setUp(self):
		self.src = read(PLANNER_API)
		at = self.src.index('elif action == "approve":')
		self.block = self.src[at:self.src.index('elif action == "reject":')]

	def test_the_planner_s_steps_are_derived_from_the_configured_chain(self):
		self.assertIn('sr_row.get("document_type") == "Work Management Planner"', self.src)
		self.assertIn('sr_row.get("kind") == "Approval"', self.src)
		self.assertIn('sr_row.get("on")', self.src)

	def test_approve_no_longer_names_a_step(self):
		self.assertNotIn("planner_farm_approval", self.block,
			"one approval action serves every approval the chain holds, or adding "
			"a step is a release again")

	def test_it_finds_the_step_by_the_state_the_request_waits_in(self):
		"""Or by the stage key the row carries, which is the same resolution --
		see work_management/chain.py. Both go through one helper, so the planner,
		the assigner and actuals cannot answer "which step is this" differently."""
		self.assertIn("chain.resolve(STAGE_ROWS", self.block)
		self.assertIn("state=cur_ws", self.block)
		self.assertIn('stage=frappe.form_dict.get("stage")', self.block)

	def test_it_moves_to_that_step_s_own_next_state(self):
		self.assertIn('ap_step.get("next_state")', self.block)

	def test_only_the_last_step_submits_the_document(self):
		"""docstatus was set on every approval. With two of them that submits a
		request HR has not seen, and `approved_by` would name the wrong person."""
		self.assertIn("if ap_next == AP_TERMINAL:", self.block)
		at = self.block.index("if ap_next == AP_TERMINAL:")
		terminal_branch = self.block[at:self.block.index("else:", at)]
		self.assertIn('"docstatus", 1', terminal_branch)
		self.assertIn('"approved_by"', terminal_branch)
		self.assertNotIn('"docstatus", 1', self.block[:at],
			"an intermediate approval submits the document")

	def test_an_intermediate_step_is_recorded_somewhere(self):
		"""The Planner has one approved_by field and it means the final approval.
		Who took a middle step still has to be answerable."""
		self.assertIn("add_comment", self.block)

	def test_a_scoped_step_is_gated_on_the_farm_and_an_unscoped_one_on_its_role(self):
		self.assertIn('ap_step.get("scoped")', self.block)
		self.assertIn("AP_FARMS", self.block)
		self.assertIn('ap_step.get("role") in MY_ROLES', self.block)

	def test_general_manager_is_not_a_bypass_for_an_unscoped_step(self):
		"""may_take_step()'s rule. GM bypassing the farm dimension is right; GM
		taking the HR step erases the separation the chain exists to express."""
		at = self.block.index('ap_step.get("role") in MY_ROLES')
		gate = self.block[at:at + 200]
		self.assertIn("System Manager", gate)
		self.assertNotIn("General Manager", gate)

	def test_a_step_with_no_role_refuses_everybody(self):
		"""A misconfigured gate must close, not open."""
		self.assertIn('ap_step.get("role") and', self.block)


class TestRejectingIsAvailableAtEveryStep(unittest.TestCase):
	"""HR refusing a request is a rejection like the farm manager's. Keyed to one
	state, HR could approve and not refuse."""

	def setUp(self):
		src = read(PLANNER_API)
		at = src.index('elif action == "reject":')
		self.block = src[at:src.index("# ===== ASSIGNER (a_) =====")]

	def test_it_finds_the_step_the_same_way(self):
		self.assertIn("chain.at_state(STAGE_ROWS", self.block)

	def test_it_no_longer_names_a_step(self):
		self.assertNotIn("planner_farm_approval", self.block)

	def test_whoever_may_approve_a_step_may_refuse_it(self):
		self.assertIn('rj_step.get("scoped")', self.block)
		self.assertIn('rj_step.get("role") in MY_ROLES', self.block)


class TestThePendingListServesEveryStep(unittest.TestCase):
	"""One filtered query for all the steps would either hide HR's queue from an
	HR head with no farm role, or hand a farm manager every farm's HR queue."""

	def setUp(self):
		src = read(PLANNER_API)
		at = src.index('elif action == "pending":')
		self.block = src[at:src.index('# WHAT APPROVING THIS LEAVES', at)]

	def test_it_loops_the_steps_rather_than_naming_one(self):
		self.assertIn("for p_step in AP_STEPS:", self.block)
		self.assertNotIn('STAGE_STATE["planner_farm_approval"]', self.block)

	def test_the_farm_filter_is_applied_only_to_the_scoped_step(self):
		at = self.block.index('if p_step.get("scoped"):')
		scoped_branch = self.block[at:self.block.index("else:", at)]
		self.assertIn('pflt["farm"]', scoped_branch)
		self.assertNotIn('pflt["farm"]', self.block[self.block.index("else:", at):])

	def test_each_row_carries_the_step_it_waits_in(self):
		for field in ('p_row["step"]', 'p_row["step_label"]', 'p_row["step_action"]'):
			with self.subTest(field=field):
				self.assertIn(field, self.block)

	def test_the_steps_are_reported_even_when_nothing_is_waiting(self):
		""""Nothing awaiting approval" and "no step here is yours" are different
		answers, and the screen gave the first for both."""
		self.assertIn('out["steps"]', self.block)
		self.assertIn('"mine": 1 if p_may else 0', self.block)


class TestTheScreenOffersTheStepsButton(unittest.TestCase):
	"""Until this, Altura's Planner HR approval worked from the desk and not from
	the planner screen -- a caveat that had to be written into
	docs/ALTURA_APPROVAL_CHAINS.md."""

	def setUp(self):
		self.js = read(PLANNER_JS)

	def test_the_screen_keeps_the_steps_it_was_given(self):
		self.assertIn("ST._apprSteps", self.js)

	def test_the_button_is_labelled_with_the_step_s_own_action(self):
		""""HR Approve" is what the step calls the decision. A button reading
		"Approve" on a screen running two of them says nothing about which."""
		self.assertIn("r.step_action", self.js)

	def test_a_second_step_earns_a_column_saying_which(self):
		self.assertIn("r.step_label", self.js)
		self.assertIn("multi", self.js)

	def test_the_empty_state_can_say_no_step_here_is_yours(self):
		at = self.js.index("function renderAppr(")
		block = self.js[at:at + 2000]
		self.assertIn("No approval step here is yours", block)

	def test_the_detail_row_spans_the_extra_column(self):
		"""A colspan short by one leaves the panel misaligned under the table.

		13 base + 1 for the Step column when the chain runs two approvals + 1 for
		the bulk tick-box column."""
		self.assertIn("multi?15:14", self.js)


class TestTheMasterPlanRefusalNamesTheConfiguredStep(unittest.TestCase):
	"""The gate already asked the chain which role takes the GM step. The refusal
	said "the general manager" regardless, so on Altura's chain -- where HR takes
	it -- the message named the wrong person and sent them to the wrong desk."""

	def setUp(self):
		self.src = read(os.path.join(APP, "api", "masterplan.py"))

	def test_the_chain_s_label_is_available_to_the_messages(self):
		self.assertIn("STAGE_LABEL[sr_row[\"key\"]] = sr_row.get(\"label\")", self.src)

	def test_no_approval_refusal_still_hardcodes_the_general_manager(self):
		stale = re.findall(r'"[^"]*[Oo]nly the general manager[^"]*"', self.src)
		self.assertEqual(stale, [],
			"a refusal naming a role the chain may not use: " + ", ".join(stale))

	def test_the_gm_approve_refusal_names_the_role_and_the_step(self):
		at = self.src.index('elif action == "gm_approve":')
		block = self.src[at:at + 900]
		self.assertIn('STAGE_ROLE.get("masterplan_gm")', block)
		self.assertIn('STAGE_LABEL.get("masterplan_gm")', block)
