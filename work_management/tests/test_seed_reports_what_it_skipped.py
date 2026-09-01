"""The seed must say which farms it could not give a cost project, and why.

"Lokitela has no cost project, so there are no tasks to offer" is what the Master
Plan screen says when a farm has no row on the farms table. The message is right
and it points at Settings, but it cannot say how the farm ended up without one.

There are two ways, and the seed was only honest about one of them. It reports a
farm Upande Core has not got. It said nothing at all about a farm whose project
does not exist on the site -- `if not frappe.db.exists("Project", project):
continue` -- so on a site without Kaitet's PROJ-0031 and PROJ-0032 the seed
printed "0 cost project(s)" and every farm silently kept none. Its own docstring
warns that "a farm quietly without one shows an empty task list and no reason
why", which is exactly what it then caused.

Both skips are now reported, separately, because the fix differs: a missing farm
is created in Upande Core, a missing project is either created or the mapping
points at the wrong one for this site.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_seed_reports_what_it_skipped -v
"""

import ast
import inspect
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = os.path.join(HERE, "seed", "kaitet.py")


def seed_source():
	with open(SEED) as handle:
		return handle.read()


def function_source(name):
	tree = ast.parse(seed_source())
	for node in ast.walk(tree):
		if isinstance(node, ast.FunctionDef) and node.name == name:
			return ast.get_source_segment(seed_source(), node)
	raise AssertionError("%s is not defined in the seed" % name)


class TestAMissingProjectIsNotSwallowed(unittest.TestCase):
	def test_ensure_farm_projects_collects_missing_projects(self):
		source = function_source("ensure_farm_projects")
		self.assertIn("missing_projects", source,
			"a farm whose project does not exist must be collected, not skipped")

	def test_it_is_not_a_bare_continue_any_more(self):
		"""The exact line that hid the problem."""
		source = function_source("ensure_farm_projects")
		lines = [l.strip() for l in source.splitlines()]
		for i, line in enumerate(lines):
			if line.startswith('if not frappe.db.exists("Project"'):
				following = lines[i + 1:i + 3]
				self.assertNotEqual(following[0], "continue",
					"a missing project is still skipped silently")

	def test_the_two_skips_are_reported_separately(self):
		"""A missing farm is created in Core; a missing project is created here or
		the mapping is wrong for this site. Different fixes, different messages."""
		source = function_source("ensure_farm_projects")
		self.assertIn("missing_farms", source)
		self.assertIn("missing_projects", source)


class TestExecuteTellsSomebodyWhatToDo(unittest.TestCase):
	def setUp(self):
		self.source = function_source("execute")

	def test_it_prints_the_missing_projects(self):
		self.assertIn("missing_projects", self.source)

	def test_it_still_prints_the_missing_farms(self):
		"""The half that already worked must not be lost in the fix."""
		self.assertIn("missing_farms", self.source)

	def test_the_project_message_names_the_project_not_only_the_farm(self):
		"""Knowing Lokitela was skipped is half an answer; knowing PROJ-0031 is
		what it wanted is the other half."""
		lines = [l for l in self.source.splitlines() if "missing_projects" in l]
		self.assertTrue(lines, "execute() does not mention missing_projects")

	def test_the_return_shape_is_documented(self):
		"""Three values now, and a caller unpacking two would break loudly --
		better than a caller silently dropping the new one."""
		doc = inspect.getdoc(__import__(
			"work_management.seed.kaitet", fromlist=["kaitet"]).ensure_farm_projects)
		self.assertIn("missing_projects", doc)


class TestTheCallerUnpacksAllOfIt(unittest.TestCase):
	def test_execute_unpacks_three_values(self):
		source = function_source("execute")
		call = next(l for l in source.splitlines() if "ensure_farm_projects()" in l)
		self.assertEqual(call.count(","), 2,
			"execute() must unpack (written, missing_farms, missing_projects)")


if __name__ == "__main__":
	unittest.main()
