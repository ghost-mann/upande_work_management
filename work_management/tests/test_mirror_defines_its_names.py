"""A name the mirror uses, the mirror must define.

This exists because of a live outage I caused. The farm guard references `FARMS`,
five of the six scripts define it at module top, and `wm_masterplan` did not --
so every Master Plan request naming a farm answered
`NameError: name 'FARMS' is not defined`. The screen was down until it was
restored.

The app's own tests passed throughout, and could not have failed: `port_app.py`
gives every ported module a header that assigns `FARMS` from `get_config()`,
whether the mirror it came from had one or not. So testing the ported copies
tests a world where these names always exist. The only place the bug was visible
was in the mirror sources, and nothing read those.

That is the gap this closes. It reads the mirror's own files and checks that every
module-level name they use is one they define -- module level specifically,
because a Server Script has no imports and no `def`: whatever is not defined in
the file does not exist, and the sandbox's own globals are the only exception.

Skipped when the mirror is not checked out beside the app, following
`test_master_plan_resolution`.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_mirror_defines_its_names -v
"""

import os
import re
import unittest

MIRROR = "/home/austin/vscodeProjects/kaitet-work-management/server_scripts"

# The screens whose farm dimension the guard defends. Named rather than globbed:
# a new script appearing should be a deliberate addition here, not silently
# covered or silently missed.
SCRIPTS = ("wm_dashboard", "wm_planner", "wm_masterplan", "wm_assigner",
	"wm_actuals", "wm_payment")

# Names the port's header supplies to the app and the mirror must therefore
# supply itself. These are exactly the ones `port_app.py` strips and rebuilds,
# which is why their absence in the mirror is invisible from the app side.
PORTED_CONSTANTS = ("FARMS", "FARM_PROJECT", "DEFAULT_COMPANY", "BLOCK_EXCLUDE",
	"FARM_APPROVER_ROLE", "HR_HEAD_ROLES", "STAGE_ROWS", "STAGE_STATES")


def source(script):
	with open(os.path.join(MIRROR, script + ".py")) as handle:
		return handle.read()


def defines(text, name):
	"""Is `name` assigned at module level -- column zero, no indentation?

	Indentation matters: an assignment inside a branch runs only when that branch
	does, and the guard runs before any of them.
	"""
	return re.search(r"^%s\s*=" % re.escape(name), text, re.M) is not None


def uses(text, name):
	return re.search(r"\b%s\b" % re.escape(name), text) is not None


class TestTheMirrorIsCheckedOut(unittest.TestCase):
	def setUp(self):
		if not os.path.isdir(MIRROR):
			self.skipTest("mirror not present")

	def test_every_script_is_there(self):
		for script in SCRIPTS:
			with self.subTest(script=script):
				self.assertTrue(os.path.exists(os.path.join(MIRROR, script + ".py")))


class TestEveryNameUsedIsDefined(unittest.TestCase):
	def setUp(self):
		if not os.path.isdir(MIRROR):
			self.skipTest("mirror not present")

	def test_a_ported_constant_a_script_uses_is_one_it_defines(self):
		"""The exact shape of the outage: used, not defined, NameError at runtime."""
		missing = []
		for script in SCRIPTS:
			text = source(script)
			for name in PORTED_CONSTANTS:
				if uses(text, name) and not defines(text, name):
					missing.append("%s uses %s and does not define it" % (script, name))
		self.assertEqual(missing, [], "\n".join(missing))

	def test_the_definition_is_at_module_level(self):
		"""Not inside a branch. The guard runs before every branch, so a name
		defined in one is not defined when the guard reads it."""
		for script in SCRIPTS:
			text = source(script)
			for name in PORTED_CONSTANTS:
				if not uses(text, name):
					continue
				with self.subTest(script=script, name=name):
					self.assertTrue(defines(text, name),
						"%s.%s is not assigned at column zero" % (script, name))


class TestTheGuardHasSomethingToCheckAgainst(unittest.TestCase):
	"""Narrower and more direct: the guard is the thing that broke, so assert its
	own precondition on every script that carries it."""

	def setUp(self):
		if not os.path.isdir(MIRROR):
			self.skipTest("mirror not present")

	def test_every_guarded_script_defines_farms(self):
		for script in SCRIPTS:
			text = source(script)
			if "FARM_ASKED" not in text:
				continue
			with self.subTest(script=script):
				self.assertTrue(defines(text, "FARMS"),
					"%s carries the farm guard and defines no FARMS -- this is the "
					"NameError that took the Master Plan screen down" % script)

	def test_farms_is_defined_before_the_guard_reads_it(self):
		"""Order, not just presence: Python runs the file top to bottom."""
		for script in SCRIPTS:
			text = source(script)
			if "FARM_ASKED" not in text:
				continue
			with self.subTest(script=script):
				definition = re.search(r"^FARMS\s*=", text, re.M)
				self.assertIsNotNone(definition)
				self.assertLess(definition.start(), text.index("FARM_ASKED ="))

	def test_every_screen_that_reads_a_farm_carries_the_guard(self):
		"""The other direction: a script reading a farm from the request without
		the guard is an open door."""
		for script in SCRIPTS:
			text = source(script)
			if 'form_dict.get("farm")' not in text:
				continue
			with self.subTest(script=script):
				self.assertIn("FARM_ASKED =", text)


class TestTheDefinitionSurvivesThePort(unittest.TestCase):
	"""`port_app.py` strips module-level `FARMS =` lines and rebuilds them from
	get_config(). A definition it cannot strip would be left beside the header's
	own, and the mirror's would win -- handing the app the site's raw farm list
	and undoing the permission narrowing entirely."""

	def setUp(self):
		if not os.path.isdir(MIRROR):
			self.skipTest("mirror not present")

	def test_every_stripped_constant_can_be_found_and_ended(self):
		"""The strip drops the assignment line and keeps dropping until the
		brackets opened on it have closed. So a value may span lines -- the chain
		fallback is a list of dicts and reads better over several -- but its
		brackets must balance, and it must not be continued with a backslash,
		which the strip has no way to follow."""
		for script in SCRIPTS:
			text = source(script)
			lines = text.splitlines()
			for name in PORTED_CONSTANTS:
				if not defines(text, name):
					continue
				start = next(i for i, l in enumerate(lines)
					if re.match(r"^%s\s*=" % re.escape(name), l))
				with self.subTest(script=script, name=name):
					self.assertFalse(lines[start].rstrip().endswith("\\"),
						"%s.%s uses a backslash continuation" % (script, name))
					depth = 0
					for line in lines[start:]:
						depth += sum(line.count(c) for c in "([{")
						depth -= sum(line.count(c) for c in ")]}")
						if depth <= 0:
							break
					self.assertLessEqual(depth, 0,
						"%s.%s never closes its brackets" % (script, name))

	def test_the_app_gets_farms_from_config_not_from_the_mirror(self):
		import inspect

		from work_management.api import masterplan
		source_text = inspect.getsource(masterplan.wm_masterplan)
		self.assertIn('FARMS = _cfg["farms"]', source_text)
		self.assertNotIn('frappe.db.get_all("Farm", fields=["name"]', source_text)


if __name__ == "__main__":
	unittest.main()
