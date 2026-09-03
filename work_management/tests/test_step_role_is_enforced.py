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


if __name__ == "__main__":
	unittest.main()
