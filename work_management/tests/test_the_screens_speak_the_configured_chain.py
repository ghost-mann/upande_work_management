# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""No screen holds a piece of the chain's vocabulary.

Altura reconfigured Settings -- stages relabelled, roles remapped, five stages
switched off -- and the workflows regenerated correctly while all five web
screens went on speaking the chain this app happens to ship with. Every symptom
reported on 2026-09-22 is one sentence:

    unknown action: FM Approve              the tab's WORKFLOW action, posted as
                                            the dispatcher's own action
    stage must be one of fm, gm, hr         `a_fm_approve`.split("_")[1], which
                                            a configured action makes `undefined`
    the Approvals tab is missing            "does a role begin with `Farm
                                            Manager`", asked of a Production
                                            Manager
    the header reads "· HR Head"            a shipped role name printed at
                                            whoever the shipped HR test matched
    the chip reads "Pending GM"             a workflow state printed where the
                                            step is labelled something else

A screen may hold exactly one name of a step: its KEY, and only because the
server handed the key over with the tab. Everything else -- the action, the
state, the label, the role -- is the server's to resolve and the screen's to
print, never to compare against.

So this reads the five screens and fails on any of the shipped names appearing
in live code. Comments are stripped first: a comment saying what the old code
did is documentation, and this file is full of them.

    PYTHONPATH=. ~/frappe-bench3/env/bin/python -m unittest \\
        work_management.tests.test_the_screens_speak_the_configured_chain -v
"""

import os
import re
import unittest

from work_management import approvals, chain

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(APP, "public", "js")
API = os.path.join(APP, "api")

#: The five web screens. All of them, not the three that approve: the dashboard
#: reports on every chain and carried four hardcoded state lists of its own.
SCREENS = (
	"work-planner.js",
	"work-assigner.js",
	"work-actuals.js",
	"work-payment.js",
	"work-management-dashboard.js",
)

#: A block a screen is allowed to name shipped values in, for the one case that
#: needs it: a default to fall back on when the server has said nothing. Nothing
#: claims it today; it exists so that widening the rule is a visible act with a
#: marker and a reason attached, rather than a literal slipped back in.
FALLBACK_OPEN = "// WM-SHIPPED-FALLBACK"
FALLBACK_SHUT = "// WM-END-SHIPPED-FALLBACK"


def read(name):
	with open(os.path.join(JS, name), encoding="utf-8") as handle:
		return handle.read()


def without_comments(src):
	"""Strip // and /* */ comments. Same rule as test_page_bootstrap.

	A comment naming `Pending GM` is documentation -- half the comments this
	change added say exactly what the literal it replaced used to do -- and this
	test is about what the code COMPARES and PRINTS.
	"""
	src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
	return re.sub(r"(?<![:\\])//[^\n]*", "", src)


def without_fallbacks(src):
	"""Strip any declared fallback-constant block."""
	while FALLBACK_OPEN in src and FALLBACK_SHUT in src:
		at = src.index(FALLBACK_OPEN)
		end = src.index(FALLBACK_SHUT, at) + len(FALLBACK_SHUT)
		src = src[:at] + src[end:]
	return src


def live_code(name):
	return without_fallbacks(without_comments(read(name)))


#: The dispatchers behind those five screens. A screen that stopped naming a job
#: title is only half the fix: `act_close_confirm` went on asking
#: `"General Manager" in roles` and `a_add_crew` went on asking
#: `role.startswith("Farm Manager")`, so on Altura the control was drawn for the
#: Production Manager the chain names and the server refused him anyway. The
#: workaround on site was to grant him a role whose name means something else.
#:
#: wm_payment is absent for the reason it is absent from test_no_hardcoded_chain:
#: its single step is `Payment: Accounts`, required and unreachable past, and who
#: handles payments is a capability rather than a step.
DISPATCHERS = ("actuals.py", "assigner.py", "planner.py", "masterplan.py")


def read_api(name):
	with open(os.path.join(API, name), encoding="utf-8") as handle:
		return handle.read()


def without_python_comments(src):
	"""Drop whole-line `#` comments and triple-quoted blocks.

	Same reasoning as without_comments() above: most of the comments in these
	files quote the literal they replaced -- that is the record of the fix, not a
	relapse -- and this test is about what the code COMPARES.
	"""
	src = re.sub(r'"""".*?"""', "", src, flags=re.S)
	src = re.sub(r'""".*?"""', "", src, flags=re.S)
	return "\n".join(
		line for line in src.splitlines() if not line.lstrip().startswith("#"))


def live_api(name):
	return without_python_comments(read_api(name))


#: Every state the shipped chain has, taken from the catalogue rather than typed
#: out -- so a step added to CATALOGUE is covered here the day it lands, and this
#: list cannot fall behind the thing it guards.
#:
#: Two exclusions. `Draft` is where a document sits before the chain, not a step,
#: and nothing configures it. And the Payment chain's own state is left out for
#: the reason test_no_hardcoded_chain leaves wm_payment out entirely: its single
#: step is `Payment: Accounts`, which is `required` and so can never be switched
#: off or reached past, and `Unpaid` is the word the whole payment screen is
#: built on -- for a worker's balance as much as for the document. Converting it
#: would be risk without capability.
PAYMENT_STATES = {s.state for s in approvals.CATALOGUE
	if s.document_type == "Work Management Payment" and s.state}
SHIPPED_STATES = sorted(
	{s.state for s in approvals.CATALOGUE if s.state} - {"Draft"} - PAYMENT_STATES)

#: The shipped actions that name WHO takes the step -- `FM Approve`, `GM
#: Approve`, `HR Approve`, `Send to GM`. Those are the ones that go wrong on a
#: reconfigured chain, and they are derived rather than typed so a role-flavoured
#: action added to the catalogue is caught without anyone remembering to add it.
#:
#: The generic ones are deliberately NOT banned. `Approve`, `Reject`, `Submit for
#: Approval` are ordinary English and are what a button says when the server has
#: sent no word of its own -- a default, not a claim about the chain.
_ROLE_TOKENS = ("FM", "GM", "HR", "Consultant", "Farm Manager", "HR Head",
	"General Manager")


def _names_a_role(action):
	return any(re.search(r"\b%s\b" % re.escape(token), action) for token in _ROLE_TOKENS)


SHIPPED_ACTIONS = sorted(
	{s.action for s in approvals.CATALOGUE if s.action and _names_a_role(s.action)})

#: The role names this app was deliberately stopped from shipping (see
#: test_no_shipped_roles) plus the two generic ones the screens used to name.
#: `Draft` is absent from the states above and these are absent from any chain:
#: a screen printing "Draft" is printing a state nothing configures, which is
#: allowed, and a screen printing "Farm Manager" is naming somebody's job.
SHIPPED_ROLES = (
	"Farm Manager", "HR Head", "HOD HR", "HR Clerk",
	"General Manager", "Production Section Head",
)

#: The two roles a dispatcher MAY still name, because chain.may_take() names them
#: too and for the reasons written in its docstring:
#:
#:   System Manager    the unstick-the-pipeline bypass. Frappe guarantees it, so
#:                     it is the one role every site has.
#:   General Manager   the FARM dimension's bypass -- somebody who oversees every
#:                     farm is not narrowed to one. It is deliberately NOT a
#:                     bypass for a step, and a dispatcher using it as one would
#:                     let the GM take the HR step.
#:
#: Both are load-bearing and neither is a job title this app invented. Everything
#: else in SHIPPED_ROLES is.
BYPASS_ROLES = ("System Manager", "General Manager")
SERVER_FORBIDDEN_ROLES = tuple(r for r in SHIPPED_ROLES if r not in BYPASS_ROLES)


#: The bulk whitelist. `"fm"`, `"gm"`, `"hr"` as quoted tokens -- the three
#: abbreviations the screens derived by splitting an action name.
TRIPLE = re.compile(r"""["'](fm|gm|hr)["']""")


class TestNoScreenNamesAShippedAction(unittest.TestCase):
	"""A step's action is Frappe's vocabulary: it names a Workflow Transition and
	is what the desk button says. It is handed to a screen as a LABEL to print
	and is never an argument."""

	def test_the_shipped_actions_are_the_ones_we_think(self):
		for action in ("FM Approve", "GM Approve", "HR Approve", "Send to GM"):
			self.assertIn(action, SHIPPED_ACTIONS)

	def test_the_generic_ones_are_left_alone(self):
		"""A button reading "Approve" when the server has sent no word of its own
		is a default, not a claim about the chain."""
		for action in ("Approve", "Reject", "Submit for Approval"):
			self.assertNotIn(action, SHIPPED_ACTIONS)

	def test_no_screen_contains_one(self):
		offenders = []
		for screen in SCREENS:
			src = live_code(screen)
			for action in SHIPPED_ACTIONS:
				if action in src:
					offenders.append("%s names the action %r" % (screen, action))
		self.assertEqual(offenders, [], "\n".join(offenders))


class TestNoScreenNamesAChainState(unittest.TestCase):
	"""A state is where a step waits, and which state that is comes from
	Settings. Printing one is the visible half; COMPARING against one is the half
	that silently changes what a screen offers."""

	def test_the_shipped_states_are_the_ones_we_think(self):
		for state in ("Pending Farm Manager", "Pending GM", "Pending HR Head",
				"Pending Approval", "Pending Consultant"):
			self.assertIn(state, SHIPPED_STATES)

	def test_no_screen_contains_one(self):
		offenders = []
		for screen in SCREENS:
			src = live_code(screen)
			for state in SHIPPED_STATES:
				if state in src:
					offenders.append("%s names the state %r" % (screen, state))
		self.assertEqual(offenders, [], "\n".join(offenders))


class TestNoScreenNamesARole(unittest.TestCase):
	"""Who takes a step is a Role this project chose. A screen that names one is
	either gating on it -- which is the server's job and the server does it -- or
	telling somebody to go and find a person the site may not have."""

	def test_no_screen_contains_one(self):
		offenders = []
		for screen in SCREENS:
			src = live_code(screen)
			for role in SHIPPED_ROLES:
				if role in src:
					offenders.append("%s names the role %r" % (screen, role))
		self.assertEqual(offenders, [], "\n".join(offenders))


class TestNoScreenCarriesTheBulkWhitelist(unittest.TestCase):
	"""`fm`, `gm`, `hr` were never a vocabulary -- they were three substrings of
	three action names, and the screen produced them by splitting on `_`."""

	def test_no_screen_quotes_the_triple(self):
		offenders = []
		for screen in SCREENS:
			for hit in set(TRIPLE.findall(live_code(screen))):
				offenders.append("%s quotes %r as a stage" % (screen, hit))
		self.assertEqual(offenders, [], "\n".join(offenders))

	def test_no_screen_derives_a_stage_from_an_action_name(self):
		for screen in SCREENS:
			with self.subTest(screen=screen):
				self.assertNotIn('.split("_")[1]', live_code(screen))


class TestTheScreensReadTheChainInstead(unittest.TestCase):
	"""The other direction. A screen with none of the literals above could have
	earned that by doing nothing at all -- printing no status, offering no tab --
	so each one has to be reading the chain it was handed."""

	#: Screens that render a workflow state. work-payment.js is not among them:
	#: its one step is `Payment: Accounts`, which is required and so can never be
	#: switched off, and it prints Paid / Unpaid, which are not steps.
	RENDERING = ("work-planner.js", "work-assigner.js", "work-actuals.js",
		"work-management-dashboard.js")

	def test_each_reads_the_chain_the_page_delivered(self):
		for screen in self.RENDERING:
			with self.subTest(screen=screen):
				self.assertIn("window.WM_CHAIN", read(screen))

	def test_each_prints_a_state_through_the_label_map(self):
		for screen in self.RENDERING:
			with self.subTest(screen=screen):
				self.assertIn("function stateLabel(", read(screen))

	def test_each_asks_the_chain_which_states_are_which(self):
		for screen in self.RENDERING:
			with self.subTest(screen=screen):
				self.assertIn("function chainStates(", read(screen))

	def test_the_three_approving_screens_gate_the_tab_on_the_chain(self):
		"""`is_approver` is answered by chain.takeable() -- the same question the
		approve action asks -- so the tab appears exactly when a press would be
		allowed."""
		for screen in ("work-planner.js", "work-assigner.js", "work-actuals.js"):
			with self.subTest(screen=screen):
				src = live_code(screen)
				self.assertIn("is_approver", src)
				self.assertIn('"Approvals"', src)

	def test_the_header_suffix_comes_from_the_server(self):
		for screen in ("work-planner.js", "work-assigner.js", "work-actuals.js"):
			with self.subTest(screen=screen):
				self.assertIn("approver_label", live_code(screen))


class TestNoDispatcherGatesOnAShippedRole(unittest.TestCase):
	"""Finding #2: the SERVER half of the same fault.

	`act_close_roles`, `act_close_request`, `act_close_pending`,
	`act_close_confirm`, `a_add_crew`, `a_release` and the absent-day override in
	`act_submit` all gated on `r.startswith("Farm Manager")`, `r ==
	"Production Section Head"` or `"General Manager" in roles`. On Altura those
	steps are taken by a Production Manager, so the person the chain names could
	neither close a plan nor change a crew -- worked around on site by granting
	him a role whose name means something else.

	Every one of them now asks chain.may_take() / chain.takeable(), which is the
	same question the approve actions have asked since the chain became
	configurable.
	"""

	def test_the_dispatchers_are_all_there(self):
		for name in DISPATCHERS:
			with self.subTest(dispatcher=name):
				self.assertTrue(os.path.exists(os.path.join(API, name)))

	def test_none_of_them_names_a_shipped_job_title(self):
		offenders = []
		for name in DISPATCHERS:
			src = live_api(name)
			for role in SERVER_FORBIDDEN_ROLES:
				if '"%s"' % role in src or "'%s'" % role in src:
					offenders.append("api/%s names the role %r" % (name, role))
		self.assertEqual(offenders, [], "\n".join(offenders))

	def test_the_two_bypasses_are_the_only_role_names_left(self):
		"""The other direction, so the exception cannot quietly widen: a
		dispatcher may name System Manager and General Manager and nothing
		else."""
		for name in DISPATCHERS:
			src = live_api(name)
			for role in BYPASS_ROLES:
				del role  # named for the reader; the assertion is the set below
			quoted = {r for r in SHIPPED_ROLES if ('"%s"' % r) in src}
			with self.subTest(dispatcher=name):
				self.assertTrue(quoted <= set(BYPASS_ROLES),
					"api/%s names %s" % (name, sorted(quoted - set(BYPASS_ROLES))))

	def test_no_dispatcher_prefix_matches_a_role_name(self):
		"""`role.startswith("Farm Manager")` was how a per-farm role was
		recognised, and it recognised only one company's. Where a prefix match is
		still wanted it must be against a CONFIGURED name -- a variable -- never
		a literal."""
		offenders = []
		for name in DISPATCHERS:
			for line in live_api(name).splitlines():
				if ".startswith(" not in line:
					continue
				if re.search(r'\.startswith\(\s*["\']', line):
					offenders.append("api/%s: %s" % (name, line.strip()))
		self.assertEqual(offenders, [], "\n".join(offenders))

	def test_the_close_and_crew_gates_go_through_the_chain(self):
		"""Not merely that the literals are gone -- a gate deleted outright would
		pass that too. Each file must resolve the question it used to answer by
		name."""
		actuals = live_api("actuals.py")
		for token in ("ACT_MAY_DECIDE", "ACT_MAY_REQUEST", "chain.may_take",
				"chain.takeable"):
			with self.subTest(token=token):
				self.assertIn(token, actuals)
		assigner = live_api("assigner.py")
		for token in ("ASG_MAY_CHANGE_CREW", "chain.takeable"):
			with self.subTest(token=token):
				self.assertIn(token, assigner)

	def test_the_crew_verbs_are_the_ones_that_were_broken(self):
		"""a_add_crew and a_release, by name, so this cannot pass by their
		disappearing."""
		assigner = live_api("assigner.py")
		for act in ('"a_add_crew"', '"a_release"'):
			with self.subTest(action=act):
				self.assertIn(act, assigner)
				at = assigner.index(act)
				self.assertIn("ASG_MAY_CHANGE_CREW", assigner[at:at + 2500])


class TestNoDispatcherDecidesByStateName(unittest.TestCase):
	"""Finding #3: the master plan compared `workflow_state` against
	`Pending Consultant` and `Pending GM` in nine places.

	Altura's master-plan states happen to be the shipped ones, so it half-works
	there -- which is the same fault armed rather than a different one. The
	states a step waits in are Settings' answer, and `STAGE_STATE[key]` is how
	every other screen asks.
	"""

	#: The two the master plan compared against. Derived from the catalogue, so a
	#: renamed shipped state cannot leave this list behind.
	MASTER_PLAN_STATES = tuple(sorted(
		{s.state for s in approvals.CATALOGUE
			if s.document_type == "Work Management Master Plan"
			and s.kind == "Approval" and s.state}))

	def test_the_states_are_the_ones_we_think(self):
		self.assertEqual(self.MASTER_PLAN_STATES,
			("Pending Consultant", "Pending GM"))

	def test_the_master_plan_dispatcher_names_neither(self):
		src = live_api("masterplan.py")
		offenders = [state for state in self.MASTER_PLAN_STATES
			if ('"%s"' % state) in src or ("'%s'" % state) in src]
		self.assertEqual(offenders, [],
			"api/masterplan.py compares against %s" % (offenders,))

	def test_it_asks_the_chain_instead(self):
		src = live_api("masterplan.py")
		for token in ("STAGE_STATE[", "MP_CONSULTANT_STATE", "MP_GM_STATE"):
			with self.subTest(token=token):
				self.assertIn(token, src)


class TestTheFallbackBlockIsRealAndUnused(unittest.TestCase):
	"""The escape hatch exists so that widening the rule is deliberate. If it is
	ever used, it must actually work."""

	def test_a_marked_block_is_excluded(self):
		src = 'var a="Pending GM";\n%s\nvar b="FM Approve";\n%s\nvar c=1;' % (
			FALLBACK_OPEN, FALLBACK_SHUT)
		self.assertIn("Pending GM", without_fallbacks(src))
		self.assertNotIn("FM Approve", without_fallbacks(src))

	def test_no_screen_claims_it_today(self):
		for screen in SCREENS:
			with self.subTest(screen=screen):
				self.assertNotIn(FALLBACK_OPEN, read(screen))


class TestTheServerAnswersWhatTheScreensStoppedAsking(unittest.TestCase):
	"""Pure checks on the helpers the screens now lean on, so the rule above is
	enforceable without leaving anything unanswered."""

	CHAIN = [
		{"key": "asg_submit", "document_type": "X", "kind": "Submit",
		 "state": "Draft", "on": 1, "role": "Clerk"},
		{"key": "asg_manager", "document_type": "X", "kind": "Approval",
		 "state": "Awaiting Manager", "label": "Assigner: Manager",
		 "action": "Manager Approve", "next_state": "Awaiting HR",
		 "on": 1, "role": "Production Manager", "scoped": 1},
		{"key": "asg_hr", "document_type": "X", "kind": "Approval",
		 "state": "Awaiting HR", "label": "Assigner: HR", "action": "HR Approve",
		 "next_state": "Assigned", "on": 1, "role": "HR Officer", "scoped": 0},
		{"key": "asg_gm", "document_type": "X", "kind": "Approval",
		 "state": "Awaiting GM", "label": "Assigner: GM", "action": "GM Approve",
		 "next_state": "Assigned", "on": 0, "role": "Boss", "scoped": 0},
	]

	def test_a_state_resolves_to_the_configured_label(self):
		labels = chain.state_labels(self.CHAIN, "X")
		self.assertEqual(labels["Awaiting Manager"], "Assigner: Manager")
		self.assertEqual(labels.get("Draft"), None, "Submit is not a queue")

	def test_a_switched_off_step_still_has_a_label(self):
		"""Its documents are still on screen and still have to say where they
		are; whether it can be TAKEN is a different question."""
		self.assertIn("Awaiting GM", chain.state_labels(self.CHAIN, "X"))

	def test_the_tab_follows_the_configured_role(self):
		self.assertEqual(
			[s["key"] for s in chain.takeable(self.CHAIN, "X", ["HR Officer"])],
			["asg_hr"])
		self.assertEqual(chain.takeable(self.CHAIN, "X", ["HR Head"]), [],
			"the SHIPPED role must not open a step configured for another")

	def test_a_farm_scoped_step_is_theirs_when_they_decide_a_farm(self):
		self.assertEqual(
			[s["key"] for s in chain.takeable(self.CHAIN, "X", ["Production Manager"],
				farms=["Altura"])],
			["asg_manager"])
		self.assertEqual(
			chain.takeable(self.CHAIN, "X", ["Production Manager"], farms=[]), [])

	def test_a_switched_off_step_is_nobody_s(self):
		self.assertEqual(chain.takeable(self.CHAIN, "X", ["Boss"]), [])

	def test_the_header_names_the_step_not_the_role(self):
		self.assertEqual(
			chain.approver_suffix(self.CHAIN, ["X"], ["HR Officer"]), "HR")
		self.assertEqual(
			chain.approver_suffix(self.CHAIN, ["X"], ["Nobody"]), "",
			"somebody who approves nothing gets no suffix at all")

	def test_past_two_steps_it_says_approver(self):
		"""Naming four steps in a header is noise, not information."""
		wide = self.CHAIN + [
			{"key": "asg_x%d" % i, "document_type": "X", "kind": "Approval",
			 "state": "S%d" % i, "label": "Assigner: S%d" % i, "on": 1,
			 "role": "Everyone"} for i in range(3)
		]
		self.assertEqual(
			chain.approver_suffix(wide, ["X"], ["Everyone"]), "Approver")

	def test_a_stage_that_is_not_a_step_is_refused_by_name(self):
		step, why = chain.resolve(self.CHAIN, "X", stage="fm")
		self.assertIsNone(step)
		self.assertIn("asg_manager", why)
		self.assertNotIn("fm, gm, hr", why)

	def test_a_stage_key_resolves(self):
		step, why = chain.resolve(self.CHAIN, "X", stage="asg_hr")
		self.assertIsNone(why)
		self.assertEqual(step["key"], "asg_hr")

	def test_a_state_resolves_too(self):
		"""The other name the server publishes for a step, so a caller holding a
		pill's `state` is not wrong."""
		step, why = chain.resolve(self.CHAIN, "X", stage="Awaiting HR")
		self.assertIsNone(why)
		self.assertEqual(step["key"], "asg_hr")

	def test_no_stage_falls_back_to_where_the_document_is(self):
		step, why = chain.resolve(self.CHAIN, "X", state="Awaiting Manager")
		self.assertIsNone(why)
		self.assertEqual(step["key"], "asg_manager")


if __name__ == "__main__":
	unittest.main()
