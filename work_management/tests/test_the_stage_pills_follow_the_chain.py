"""Every Approvals tab strip is built from the configured chain, not from a list.

On Altura, Settings was reconfigured -- stages relabelled, roles remapped, five
switched off, new ones added -- the workflows regenerated, and the transitions
followed the new chain. Every tab strip still showed the old one:

    /work-assigner Approvals   Farm Manager / HR Head / GM
    /work-actuals  Approvals   HR Head / GM / Close Requests
    /work-planner  Master plan Consultant / General Manager / Approved /
                               Draft / Rejected

Three failures in one: a step switched off keeps a tab that can never fill, a
renamed step keeps its old name, and a step ADDED gets no tab at all -- its
documents reachable only from the desk.

**What is not in scope, and was checked.** The planner's own Approvals tab has
no strip: it renders one merged queue and already builds it from the chain
(`AP_STEPS`, filtered from `STAGE_ROWS`). It needed nothing.

Measured on kentrout.local against a reconfigured chain -- assigner_farm_manager
relabelled, assigner_hr_head switched off with one assignment sitting in it,
planner_hr_approval switched on::

    as shipped        Farm Manager / HR Head / GM
    reconfigured      Section Head · HR Head (off, 1) · GM
                      planner steps: Farm Approval, HR Approval
    drain, step off   "The HR Head step is switched off for this project."
    step back on      approved; switch off again -> the HR tab is gone,
                      GM's count is 1

That third line is the point of `legacy` and its limit. The tab makes stranded
work visible and countable; it cannot clear it, because the approve actions
refuse a switched-off step by design and that gate is not a display concern's to
move. The marker says what does clear it.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_the_stage_pills_follow_the_chain -v
"""

import os
import unittest

from work_management import stage_pills

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(APP, "public", "js")
WWW = os.path.join(APP, "www")
API = os.path.join(APP, "api")


def read(path):
	with open(path) as handle:
		return handle.read()


def js_function(src, name):
	"""One JS function body, declaration to the next one at column 2."""
	at = src.index("  function %s(" % name)
	nxt = src.find("\n  function ", at + 10)
	return src[at:nxt if nxt > 0 else len(src)]


def step(key, label, state, on=1, kind="Approval", **extra):
	row = {"key": key, "label": label, "state": state, "kind": kind, "on": on,
		"document_type": "Work Management Assigner", "action": key + "_approve",
		"role": "Farm Manager", "scoped": 0}
	row.update(extra)
	return row


#: A chain that has been reconfigured the way Altura's was.
RECONFIGURED = [
	step("assigner_submit", "Assigner: Submit", "Draft", kind="Submit"),
	step("assigner_farm_manager", "Assigner: Section Head", "Pending Farm Manager", scoped=1),
	step("assigner_hr_head", "Assigner: HR Head", "Pending HR Head", on=0),
	step("assigner_gm", "Assigner: GM", "Pending GM", on=0),
	step("assigner_finance", "Assigner: Finance", "Pending Finance"),
]


class TestWhatBecomesATab(unittest.TestCase):
	def pills(self, counts=None):
		return stage_pills.build(RECONFIGURED, counts or {})

	def labels(self, counts=None):
		return [pill["short_label"] for pill in self.pills(counts)]

	def test_a_renamed_step_shows_its_new_name(self):
		self.assertIn("Section Head", self.labels())

	def test_a_step_that_was_added_gets_a_tab(self):
		"""The failure with no visible symptom: before this, its documents were
		reachable only from the desk."""
		self.assertIn("Finance", self.labels())

	def test_a_switched_off_step_with_nothing_in_it_is_hidden(self):
		self.assertNotIn("GM", self.labels())

	def test_a_switched_off_step_holding_work_is_shown(self):
		self.assertIn("HR Head", self.labels({"Pending HR Head": 3}))

	def test_and_is_marked_as_the_leftover_it_is(self):
		pill = [p for p in self.pills({"Pending HR Head": 3})
			if p["state"] == "Pending HR Head"][0]
		self.assertEqual(pill["legacy"], 1)
		self.assertEqual(pill["on"], 0)
		self.assertEqual(pill["count"], 3)

	def test_it_goes_again_once_the_last_one_is_decided(self):
		self.assertNotIn("HR Head", self.labels({"Pending HR Head": 0}))

	def test_an_enabled_step_is_never_marked_legacy(self):
		for pill in self.pills({"Pending Farm Manager": 9}):
			if pill["on"]:
				with self.subTest(pill=pill["key"]):
					self.assertEqual(pill["legacy"], 0)

	def test_submit_is_not_a_queue(self):
		"""It moves a draft into the chain; nothing waits there to be approved."""
		self.assertNotIn("Submit", self.labels({"Draft": 12}))

	def test_a_step_with_no_state_is_not_a_tab(self):
		"""A half-filled Settings row is a hole in the chain, not a queue."""
		self.assertEqual(stage_pills.build([step("x", "X", None)], {}), [])

	def test_the_order_is_the_chain_s_own(self):
		self.assertEqual(self.labels({"Pending HR Head": 1}),
			["Section Head", "HR Head", "Finance"])

	def test_the_counts_come_from_the_caller_not_from_the_chain(self):
		pills = {p["state"]: p["count"] for p in
			self.pills({"Pending Farm Manager": 4, "Pending Finance": 7})}
		self.assertEqual(pills["Pending Farm Manager"], 4)
		self.assertEqual(pills["Pending Finance"], 7)


class TestWhatATabIsCalled(unittest.TestCase):
	def test_the_configured_label_wins(self):
		self.assertEqual(stage_pills.label_for(
			{"label": "Section Head", "role": "Farm Manager", "state": "X"}),
			"Section Head")

	def test_then_the_role(self):
		self.assertEqual(stage_pills.label_for(
			{"label": "", "role": "Farm Manager", "state": "X"}), "Farm Manager")

	def test_then_the_state(self):
		self.assertEqual(stage_pills.label_for({"state": "Pending GM"}), "Pending GM")

	def test_a_row_with_nothing_on_it_still_gets_a_name(self):
		"""A blank tab is unclickable in practice: nobody knows what it is."""
		self.assertEqual(stage_pills.label_for({"key": "k"}), "k")


class TestTheScreenPrefixIsNotRepeatedOnEveryTab(unittest.TestCase):
	"""The shipped labels name their screen -- `Assigner: HR Head` -- which reads
	well in Settings where all fifteen sit in one grid, and reads as stutter on
	the Assigner's own strip."""

	def test_a_prefix_every_label_shares_is_trimmed(self):
		self.assertEqual(stage_pills.shared_prefix(
			["Assigner: Farm Manager", "Assigner: HR Head"]), "Assigner: ")

	def test_one_label_out_of_the_convention_keeps_them_all_verbatim(self):
		"""Rather than a strip where some are abbreviated and some are not."""
		self.assertEqual(stage_pills.shared_prefix(
			["Assigner: Farm Manager", "Section Head"]), "")

	def test_two_different_prefixes_are_not_a_shared_one(self):
		self.assertEqual(stage_pills.shared_prefix(
			["Assigner: GM", "Actuals: GM"]), "")

	def test_a_label_that_is_only_a_prefix_is_left_alone(self):
		self.assertEqual(stage_pills.shared_prefix(["Assigner: ", "Assigner: GM"]), "")

	def test_nothing_is_lost_either_way(self):
		pills = stage_pills.build(RECONFIGURED, {})
		for pill in pills:
			with self.subTest(pill=pill["key"]):
				self.assertTrue(pill["label"].endswith(pill["short_label"]))


class TestTheCountShowsWhatTheQueueWillShow(unittest.TestCase):
	"""A farm-scoped step shows a farm manager their own farms and nobody
	else's, so a badge counting every farm's promises a queue that is not
	there."""

	ROLE = {"Kabarak": "Kabarak Manager", "Simo": "Simo Manager"}

	def test_an_unscoped_step_counts_everything(self):
		self.assertIsNone(stage_pills.scope_farms(
			step("k", "K", "S"), self.ROLE, ["Kabarak Manager"]))

	def test_a_scoped_step_counts_the_farms_the_viewer_approves_for(self):
		self.assertEqual(stage_pills.scope_farms(
			step("k", "K", "S", scoped=1), self.ROLE, ["Kabarak Manager"]),
			["Kabarak"])

	def test_the_bypass_roles_still_see_everything(self):
		for role in ("System Manager", "General Manager"):
			with self.subTest(role=role):
				self.assertIsNone(stage_pills.scope_farms(
					step("k", "K", "S", scoped=1), self.ROLE, [role]))

	def test_holding_no_approver_role_counts_nothing(self):
		self.assertEqual(stage_pills.scope_farms(
			step("k", "K", "S", scoped=1), self.ROLE, ["Employee"]), [])

	def test_it_reads_the_step_s_flag_not_a_state_name(self):
		"""`Pending Farm Manager` is the thing that moves when a chain is
		reconfigured; `scoped` is the thing that means it."""
		src = read(os.path.join(APP, "stage_pills.py"))
		at = src.index("def scope_farms(")
		block = src[at:src.index("\ndef _count(")]
		self.assertIn('step.get("scoped")', block)
		self.assertNotIn("Pending", block)


class TestTheServerSendsTheStrip(unittest.TestCase):
	PAYLOADS = {
		"assigner.py": "Work Management Assigner",
		"actuals.py": "Work Management Actuals",
		"masterplan.py": "Work Management Master Plan",
	}

	def test_each_module_builds_it_from_its_own_chain_rows(self):
		for module, doctype in self.PAYLOADS.items():
			with self.subTest(module=module):
				src = read(os.path.join(API, module))
				self.assertIn("stage_pills.for_document_type(", src)
				self.assertIn('"%s", STAGE_ROWS' % doctype, src)

	def test_the_strip_is_not_narrowed_by_who_is_asking(self):
		"""An HR person may read the farm manager's queue. Whether they can act
		on it is the buttons' question and the server's, and both answer it."""
		for module in self.PAYLOADS:
			with self.subTest(module=module):
				src = read(os.path.join(API, module))
				at = src.index("stage_pills.for_document_type(")
				statement = src[at:src.index(")\n", at)]
				self.assertNotIn("if ", statement)
				# the roles ARE passed -- they narrow a farm-scoped COUNT to the
				# farms the viewer approves for, so the badge matches the queue.
				# That is not the same as deciding which tabs exist.
				self.assertIn("FARM_APPROVER_ROLE", statement)


class TestTheScreensRenderWhatTheyAreSent(unittest.TestCase):
	SCREENS = ("work-assigner.js", "work-actuals.js")

	def queues(self, screen):
		return js_function(read(os.path.join(JS, screen)), "apprQueues")

	def test_the_queues_come_from_the_payload(self):
		for screen in self.SCREENS:
			with self.subTest(screen=screen):
				self.assertIn("stages", self.queues(screen))

	def test_no_screen_still_names_the_shipped_chain(self):
		"""The literal list this replaces. Each of these was a tab that the
		chain had already stopped agreeing with."""
		for screen in self.SCREENS:
			block = self.queues(screen)
			for literal in ('label:"Farm Manager"', 'label:"HR Head"', 'label:"GM"',
					'stage:"Pending Farm Manager"', 'stage:"Pending HR Head"',
					'stage:"Pending GM"'):
				with self.subTest(screen=screen, literal=literal):
					self.assertNotIn(literal, block)

	def test_a_tab_is_no_longer_hidden_by_role(self):
		"""work-actuals.js gated three of its tabs on is_farm_manager /
		is_hr_head / is_gm, which answered "is this queue yours?" with "does
		this queue exist?"."""
		block = self.queues("work-actuals.js")
		for gate in ("r.is_farm_manager", "r.is_hr_head"):
			with self.subTest(gate=gate):
				self.assertNotIn(gate, block)

	def test_close_requests_is_not_a_chain_step_and_stays_where_it_is(self):
		"""It is still a tab beside the chain's own, but it is no longer gated on
		a role name.

		`r.is_gm` -- "General Manager" in roles -- decided who saw this queue,
		and on Altura the last actuals step is taken by somebody else, so the
		person act_close_pending would have answered could not reach it.
		`may_close_plans` is that same step resolved from the chain, which is
		exactly what act_close_pending and act_close_confirm now gate on.
		"""
		block = self.queues("work-actuals.js")
		self.assertIn('key:"close"', block)
		self.assertIn("r.may_close_plans", block)
		self.assertNotIn("r.is_gm", block)

	def test_the_tab_prints_its_count_and_its_marker(self):
		for screen in self.SCREENS:
			src = read(os.path.join(JS, screen))
			at = src.index("function renderApprovals(")
			block = src[at:at + 1400]
			with self.subTest(screen=screen):
				self.assertIn("q.count", block)
				self.assertIn("q.legacy", block)
				self.assertIn("subtab-legacy", block)

	def test_the_marker_says_what_actually_clears_the_queue(self):
		"""Not just that the step is off. The approve action refuses a
		switched-off step, so a tab that only said "off" would be a dead end
		with no way out written anywhere."""
		for screen in self.SCREENS:
			with self.subTest(screen=screen):
				src = read(os.path.join(JS, screen))
				self.assertIn("switched back on in Settings", src)


class TestTheMasterPlanStrip(unittest.TestCase):
	def setUp(self):
		self.js = read(os.path.join(JS, "work-planner.js"))
		self.html = read(os.path.join(WWW, "work-planner.html"))

	def test_the_chain_half_comes_from_the_payload(self):
		self.assertIn("(m||{}).stages||[]", js_function(self.js, "mpStages"))

	def test_the_three_that_are_not_steps_stay(self):
		"""A plan is Approved, a Draft or Rejected whatever chain a site runs."""
		block = self.js[self.js.index("var MP_TERMINALS"):]
		for state in ("Approved", "Draft", "Rejected"):
			with self.subTest(state=state):
				self.assertIn('state:"%s"' % state, block[:400])

	def test_the_markup_no_longer_carries_the_tabs(self):
		at = self.html.index('id="mp-stages"')
		self.assertIn("</nav>", self.html[at:at + 80])
		for gone in ('data-stage="Pending Consultant"', 'data-stage="Pending GM"',
				'id="mpc-consultant"', 'id="mpc-gm"'):
			with self.subTest(gone=gone):
				self.assertNotIn(gone, self.html)

	def test_the_starting_state_is_not_compiled_in_either(self):
		"""`Pending Consultant` was the default and is a step a site may switch
		off, which left the strip opening on a tab it no longer drew."""
		at = self.html.index('id="mp-state"')
		self.assertIn('value=""', self.html[at:at + 60])

	def test_a_selection_that_has_gone_falls_back_to_the_first_tab(self):
		self.assertIn("if(!live && pills.length)", js_function(self.js, "renderMpStages"))

	def test_the_tabs_are_wired_after_they_are_drawn(self):
		"""They used to be wired once, in the `!MP.inited` block, which cannot
		reach a tab that did not exist yet."""
		block = js_function(self.js, "renderMpStages")
		self.assertLess(block.index("nav.innerHTML=h;"),
			block.index('nav.querySelectorAll("[data-stage]")'))

	def test_the_planner_approvals_tab_was_already_right(self):
		"""It has no strip -- one merged queue -- and builds it from the chain.
		Asserted so a later change does not quietly give it a literal list."""
		src = read(os.path.join(API, "planner.py"))
		at = src.index("AP_STEPS = [")
		self.assertIn("for sr_row in STAGE_ROWS", src[at:at + 400])


if __name__ == "__main__":
	unittest.main()
