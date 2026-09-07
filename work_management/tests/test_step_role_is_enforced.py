"""Each step's configured Role actually gates that step.

Found while finishing the switchable-steps work, and worse than the thing being
fixed. Four approve actions had no role check at all:

    wm_assigner   a_hr_approve, a_gm_approve
    wm_actuals    act_hr_approve, act_gm_approve

They verified that the document was at the right stage and then approved it. No
outer gate exists either -- these are whitelisted API actions, so any
authenticated user who could reach the endpoint could take the HR Head or GM step
on somebody else's work, and the GM path also sets `docstatus = 1`, submitting the
document. `act_gm_approve` even carried the comment "Trusted script; GM stage
verified above", which is exactly the confusion: the *stage* was verified, never
the *person*.

Settings has held a Role against every step all along. It reached the generated
desk workflow, where Frappe enforced it, and reached the screens not at all --
and the screens are where the work happens. So this is the same shape as the
chain bug: configuration honoured in one world and ignored in the other.

The rule, kept here so both worlds share it:

  * the step's own configured role passes
  * `System Manager` passes, matching the bypass the farm-scoped check already
    allowed -- somebody has to be able to unstick a pipeline
  * anything else is refused, naming the role required, so the refusal is
    self-diagnosing rather than a dead end

Measured on live before enforcing, as the farm-permission work taught. Every HR
approver there holds `HOD HR`. One person has GM-approved 3 of 1249 actuals while
holding `HOD HR` and not `General Manager` -- so enforcement stops them, which is
either correct or a role somebody needs to grant. It is named in the deployment
notes rather than papered over.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_step_role_is_enforced -v
"""

import os
import re
import unittest

from work_management import approvals

from work_management.tests.mirror import SERVER_SCRIPTS as MIRROR

# Every action that advances a chain, and the step it takes.
GATED = {
	"wm_assigner": [
		("a_fm_approve", "assigner_farm_manager"),
		("a_hr_approve", "assigner_hr_head"),
		("a_gm_approve", "assigner_gm"),
	],
	"wm_actuals": [
		("act_fm_approve", "actuals_farm_manager"),
		("act_hr_approve", "actuals_hr_head"),
		("act_gm_approve", "actuals_gm"),
	],
}

MAY_TAKE = approvals.may_take_step


class TestWhoMayTakeAStep(unittest.TestCase):
	def test_holding_the_steps_role_passes(self):
		self.assertTrue(MAY_TAKE("HOD HR", ["HOD HR", "Employee"]))

	def test_not_holding_it_is_refused(self):
		self.assertFalse(MAY_TAKE("HOD HR", ["Employee", "HR User"]))

	def test_system_manager_passes_regardless(self):
		"""The established bypass -- the farm-scoped check already allowed it, and
		somebody has to be able to unstick a pipeline."""
		self.assertTrue(MAY_TAKE("HOD HR", ["System Manager"]))

	def test_general_manager_does_not_bypass_another_step(self):
		"""The farm check treated General Manager as a bypass. That is right for
		a farm dimension -- the GM oversees every farm -- and wrong for a step:
		it would let the GM take the HR Head step, which is the separation the
		chain exists to express. On live one person has done exactly that."""
		self.assertFalse(MAY_TAKE("HOD HR", ["General Manager"]))

	def test_a_step_with_no_role_configured_is_refused(self):
		"""Not open to everybody. A step whose role somebody cleared is
		misconfigured, and a misconfigured gate must close, not open."""
		self.assertFalse(MAY_TAKE(None, ["HOD HR", "System Manager"]))
		self.assertFalse(MAY_TAKE("", ["HOD HR"]))

	def test_no_roles_at_all_is_refused(self):
		self.assertFalse(MAY_TAKE("HOD HR", []))
		self.assertFalse(MAY_TAKE("HOD HR", None))

	def test_the_comparison_is_exact(self):
		"""`HR Manager` must not satisfy `HR Manager Kaitet`, nor the reverse."""
		self.assertFalse(MAY_TAKE("HR Manager Kaitet", ["HR Manager"]))
		self.assertFalse(MAY_TAKE("HR Manager", ["HR Manager Kaitet"]))


class TestTheRoleReachesTheScreens(unittest.TestCase):
	def test_the_chain_carries_each_steps_role(self):
		for step in approvals.effective_chain(settings=None):
			self.assertIn("role", step, step["key"])

	def test_config_hands_it_over(self):
		import inspect

		from work_management.api import config
		self.assertIn("stage_rows", inspect.getsource(config.get_config))

	def test_the_shipped_role_is_the_default(self):
		by_key = {s["key"]: s for s in approvals.effective_chain(settings=None)}
		shipped = {s.key: s.role for s in approvals.CATALOGUE}
		for key, role in shipped.items():
			if key in by_key:
				self.assertEqual(by_key[key]["role"], role)


class TestEveryApproveActionChecksIt(unittest.TestCase):
	def setUp(self):
		if not os.path.isdir(MIRROR):
			self.skipTest("mirror not present")

	def body(self, slug, action):
		"""The source of one action's branch, up to the next branch."""
		text = open(os.path.join(MIRROR, slug + ".py")).read()
		start = text.index('action == "%s":' % action)
		following = re.search(r"\nelif action == ", text[start:])
		return text[start:start + (following.start() if following else len(text))]

	def test_each_action_checks_the_configured_role(self):
		missing = []
		for slug, actions in GATED.items():
			for action, key in actions:
				if "STAGE_ROLE[" not in self.body(slug, action):
					missing.append("%s.%s does not check the step's role" % (slug, action))
		self.assertEqual(missing, [], "\n".join(missing))

	def test_each_action_checks_its_own_step(self):
		"""A copy-paste that checked the neighbouring step's role would gate the
		wrong people, and would look right."""
		for slug, actions in GATED.items():
			for action, key in actions:
				with self.subTest(action=action):
					self.assertIn('STAGE_ROLE["%s"]' % key, self.body(slug, action))

	def test_the_refusal_names_the_role_needed(self):
		for slug, actions in GATED.items():
			for action, key in actions:
				with self.subTest(action=action):
					body = self.body(slug, action)
					self.assertIn("MY_ROLES", body)

	def test_the_role_check_comes_before_the_write(self):
		for slug, actions in GATED.items():
			for action, key in actions:
				body = self.body(slug, action)
				if "set_value" not in body:
					continue
				with self.subTest(action=action):
					self.assertLess(body.index("STAGE_ROLE["), body.index("set_value"))


class TestTheMirrorHasWhatItNeeds(unittest.TestCase):
	def setUp(self):
		if not os.path.isdir(MIRROR):
			self.skipTest("mirror not present")

	def test_each_script_defines_the_callers_roles(self):
		for slug in GATED:
			text = open(os.path.join(MIRROR, slug + ".py")).read()
			with self.subTest(script=slug):
				self.assertTrue(re.search(r"^MY_ROLES\s*=", text, re.M))

	def test_each_fallback_carries_a_role_per_step(self):
		"""Live runs on the fallback. A step there with no role would refuse
		everybody -- a closed gate rather than an open one, which is the safe
		direction, but it would stop the pipeline."""
		for slug in GATED:
			text = open(os.path.join(MIRROR, slug + ".py")).read()
			fallback = text[text.index("STAGE_ROWS = ["):text.index("STAGE_STATE = {}")]
			for _action, key in GATED[slug]:
				with self.subTest(script=slug, key=key):
					entry = fallback[fallback.index('"%s"' % key):]
					entry = entry[:entry.index("}")]
					self.assertIn('"role"', entry)


class TestTheSubmitStepIsGated(unittest.TestCase):
	"""The step that moves a draft into the chain is a step, and needs the same gate.

	Found on kaitet-group when a section head could not submit a plan. The planner
	moves it by assigning `workflow_state` and calling `save()`, and Frappe validates
	that against the generated workflow -- `ignore_permissions` does not reach that
	check, only `flags.ignore_validate` would. So the role WAS enforced, by the
	framework, at the bottom of the stack, as:

	    WorkflowPermissionError: Workflow State transition not allowed from
	    Draft to Pending Approval

	which names neither the role required nor the person's own, and arrives as a 417
	with a traceback.

	The other two screens had already met this and gone the other way -- around it.
	Both write the state with `frappe.db.set_value()`, which no validator sees, under
	comments saying so outright:

	    assigner   # bypass workflow engine transition-role gate
	    actuals    # bypass the workflow engine (save() enforces transition roles
	               # the enterer doesn't hold) -- write the state directly.
	               # Access is gated by the completion check above.

	A completion check gates the *document*, never the *person*: that is the same
	confusion TestEveryApproveActionChecksIt was written about. So the framework
	enforced the role noisily on one screen and not at all on two, and no screen
	enforced it in words.

	The gate refuses the submit, never the recording. Saving a draft crosses no
	transition and stays open to whoever may enter the work.

	Master plan is deliberately absent. Its submit IS gated -- by the
	`edit_master_plan` capability -- so it needs a decision about which check should
	govern, not a missing one added.
	"""

	APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

	# module, its submit action, and the step that action takes
	SUBMITS = [
		("planner", "submit", "planner_submit"),
		("assigner", "a_submit", "assigner_submit"),
		("actuals", "act_submit", "actuals_submit"),
	]

	def body(self, module, action):
		"""The source of one module's submit branch, up to the next branch."""
		with open(os.path.join(self.APP, "api", module + ".py")) as handle:
			text = handle.read()
		start = text.index('elif action == "%s":' % action)
		following = re.search(r"\n    elif action == ", text[start + 1:])
		return text[start:start + 1 + following.start()] if following else text[start:]

	def test_it_checks_the_configured_role(self):
		for module, action, key in self.SUBMITS:
			with self.subTest(action=action):
				self.assertIn('STAGE_ROLE["%s"]' % key, self.body(module, action),
					"%s never reads its step's role" % action)

	def test_it_compares_against_the_callers_own_roles(self):
		for module, action, _key in self.SUBMITS:
			with self.subTest(action=action):
				self.assertIn("MY_ROLES", self.body(module, action),
					"%s never reads the caller's roles" % action)

	def test_it_checks_its_own_step(self):
		"""A copy-paste naming the neighbouring step would gate the wrong people
		and would look right -- the trap TestEveryApproveActionChecksIt names."""
		for module, action, key in self.SUBMITS:
			others = [k for _m, _a, k in self.SUBMITS if k != key]
			body = self.body(module, action)
			for other in others:
				with self.subTest(action=action, other=other):
					self.assertNotIn('STAGE_ROLE["%s"]' % other, body)

	def test_the_refusal_names_the_role_required(self):
		"""A dead end says no. A self-diagnosing refusal says who may.

		Twice, then: once to decide, once to say so.
		"""
		for module, action, key in self.SUBMITS:
			with self.subTest(action=action):
				self.assertGreaterEqual(self.body(module, action).count('STAGE_ROLE["%s"]' % key), 2,
					"%s tests the role but does not name it in the refusal" % action)

	def test_only_submitting_is_gated_not_saving_a_draft(self):
		for module, action, key in self.SUBMITS:
			body = self.body(module, action)
			condition = body[:body.index('STAGE_ROLE["%s"]' % key)].rsplit("if ", 1)[1]
			with self.subTest(action=action):
				self.assertIn("submit_now", condition,
					"%s gates more than submitting: %s" % (action, condition.strip()))

	def test_the_check_comes_before_the_state_moves(self):
		for module, action, key in self.SUBMITS:
			body = self.body(module, action)
			with self.subTest(action=action):
				self.assertLess(body.index('STAGE_ROLE["%s"]' % key),
					body.index('STAGE_NEXT["%s"]' % key),
					"%s moves the state before checking who may" % action)

	def test_neither_bypass_comment_survives(self):
		"""The two screens wrote their way around the framework's gate and said so.
		With a gate of their own the comments are not just stale, they are wrong."""
		for module, action, _key in self.SUBMITS:
			with self.subTest(action=action):
				self.assertNotIn("bypass workflow engine", self.body(module, action))
				self.assertNotIn("bypass the workflow engine", self.body(module, action))


class TestTheConsultantStepIsRoleBased(unittest.TestCase):
	"""The master plan's consultant step is a step, so its configured Role gates it.

	Every other step in the chain asks Settings who may take it. This one asked a
	comma-separated list of email addresses in `Work Management Settings.
	consultant_users`, plus System Manager:

	    IS_CONSULTANT = 1 if (MP_LISTED_CONSULTANT or "System Manager" in mp_roles)

	So the one step whose Role column reached the generated desk workflow and
	nothing else. On kaitet-group that meant the HR head could be named for the
	step in Settings, see the role on the workflow, and still be refused by the
	screen -- because the screen never asked. Naming individuals also does not
	survive people leaving, which is the thing roles exist to fix.

	The list stays. It is how a consultant who holds no role at all is named, and
	it is what the site is configured with today; this widens the question rather
	than replacing it. `STAGE_ROLE` is read in the same block that builds it --
	the same reason CAN_GM is resolved there and not at its declaration.
	"""

	APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	ROLE = 'STAGE_ROLE'
	KEY = 'masterplan_consultant'

	def src(self):
		with open(os.path.join(self.APP, "api", "masterplan.py")) as handle:
			return handle.read()

	def grant(self):
		"""The line that grants consultant rights from the configured role."""
		for line in self.src().splitlines():
			if self.KEY in line and self.ROLE in line and "STAGE_STATE" not in line \
					and "STAGE_NEXT" not in line and "STAGE_ON" not in line:
				return line
		return ""

	def test_the_configured_consultant_role_is_honoured(self):
		self.assertTrue(self.grant(),
			"masterplan.py never reads STAGE_ROLE for the consultant step, so the "
			"Role column on that step gates nothing on the screen")

	def test_it_is_compared_against_the_callers_roles(self):
		self.assertIn("mp_roles", self.grant(),
			"the consultant role is read but not compared with who is asking: "
			+ self.grant().strip())

	def test_holding_it_makes_you_a_consultant(self):
		src = self.src()
		after = src[src.index(self.grant()):]
		self.assertIn("IS_CONSULTANT = 1", after[:400],
			"the configured role is checked but grants nothing")

	def test_the_named_list_still_works(self):
		"""Widened, not replaced -- a consultant holding no role is still named."""
		src = self.src()
		self.assertIn("consultant_users", src)
		self.assertIn("MP_LISTED_CONSULTANT", src)

	def test_the_role_is_read_after_stage_role_is_built(self):
		"""STAGE_ROLE is filled in mid-request; reading it earlier reads nothing."""
		src = self.src()
		built = src.index('STAGE_ROLE[sr_row["key"]]')
		self.assertLess(built, src.index(self.grant()),
			"the consultant role is read before STAGE_ROLE has been populated")


class TestAnAdministratorIsShownEveryStage(unittest.TestCase):
	"""`is_hr_head` is the one of these flags that System Manager cannot satisfy.

	The screens ask the endpoint who the caller is and draw the approval tabs from
	the answer. Four of the five flags let an administrator through:

	    is_clerk        ("System Manager" in rl) or enter_work roles
	    is_accounts     ("System Manager" in rl) or handle_payments roles
	    is_hr_head      HR_HEAD_ROLES only            <-- no bypass
	    is_gm           "General Manager" only        <-- no bypass

	So on kaitet-group an administrator holding System Manager, HR Manager and
	General Manager could not see the HR Head tab in actuals, and there was
	nothing on screen to say why: the answer was that `HR_HEAD_ROLES` resolves to
	`HOD HR` alone and he did not hold it. Meanwhile the *action* behind that tab,
	`act_hr_approve`, does accept System Manager -- so the endpoint permitted the
	step and the screen hid the way to reach it.

	A System Manager already passes every approve gate in these modules. Hiding a
	tab from them reports a permission that is not actually withheld, which is the
	same class of thing as the assigner reporting an unread presence as an absence.

	`is_gm` has the identical gap and is deliberately left alone here: the GM step
	is a real separation and widening it is a decision, not a consistency fix.
	"""

	APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	MODULES = ("assigner", "actuals")

	def line(self, module, flag):
		with open(os.path.join(self.APP, "api", module + ".py")) as handle:
			for line in handle:
				if 'out["%s"]' % flag in line:
					return line
		return ""

	def test_the_hr_head_flag_lets_a_system_manager_through(self):
		for module in self.MODULES:
			with self.subTest(module=module):
				self.assertIn("System Manager", self.line(module, "is_hr_head"),
					"%s hides the HR Head stage from an administrator who may take it: %s"
					% (module, self.line(module, "is_hr_head").strip()))

	def test_it_still_asks_the_configured_hr_head_roles(self):
		"""Widened, not replaced -- the configured role is still what grants it."""
		for module in self.MODULES:
			with self.subTest(module=module):
				self.assertIn("HR_HEAD_ROLES", self.line(module, "is_hr_head"))

	def test_its_neighbours_are_unchanged(self):
		"""is_clerk and is_accounts already had the bypass; this must not disturb them."""
		for module in self.MODULES:
			for flag in ("is_clerk", "is_accounts"):
				with self.subTest(module=module, flag=flag):
					self.assertIn("System Manager", self.line(module, flag))


if __name__ == "__main__":
	unittest.main()
