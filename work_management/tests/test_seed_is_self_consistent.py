"""The seed must write a configuration that its own validation accepts.

It did not. `seed.kaitet` names four farms, gives each its cost project, and adds
a per-farm approver for each -- and left the app scoped to all sixteen farms
Upande Core carries. The stranded-farm check then refused the save:

    Planner: Farm Approval has approvers for some farms but not cheptiret,
    Karen, Kaptumbo, Simotwo, Torongo, Kapkolia, Chepsito, Eldama, Westwood,
    Greenville, SIMO, Post Harvest

So the seed aborted, nothing was committed -- including the cost projects it had
already written, since they were in the same transaction -- and the visible
symptom was a farm with no cost project and a Master Plan screen offering no
activities.

Declaring the four farms and then not restricting to them is the contradiction.
A seed that says "these are the farms this project works" has to say it in the
place the app reads, which is the `farms_restrict` checkbox; otherwise it writes
a list the app ignores.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_seed_is_self_consistent -v
"""

import ast
import os
import unittest

from work_management import approvals
from work_management.api import config
from work_management.seed import kaitet

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = os.path.join(HERE, "seed", "kaitet.py")


def seed_source():
	with open(SEED) as handle:
		return handle.read()


def function_source(name):
	text = seed_source()
	for node in ast.walk(ast.parse(text)):
		if isinstance(node, ast.FunctionDef) and node.name == name:
			return ast.get_source_segment(text, node)
	raise AssertionError("%s is not defined in the seed" % name)


class TestTheSeedNarrowsToTheFarmsItNames(unittest.TestCase):
	def test_it_sets_farms_restrict(self):
		self.assertIn("farms_restrict", seed_source(),
			"the seed names four farms and must say so where the app reads it")

	def test_the_farms_table_owns_the_switch(self):
		"""Set by the function that writes the rows, so the two cannot drift."""
		self.assertIn("farms_restrict", function_source("ensure_farm_projects"))

	def test_it_is_set_before_approvers_are_seeded(self):
		"""Order matters: seeding approvers saves Settings, and that save is what
		runs the stranded-farm check. Restricting afterwards is too late."""
		text = function_source("execute")
		self.assertLess(text.index("ensure_farm_projects()"),
			text.index("seed_stage_approvers()"))


class TestTheResultingConfigurationValidates(unittest.TestCase):
	"""The check the seed tripped over, run against what the seed produces."""

	KAITET_FARMS = [farm for farm, _project in kaitet.FARMS]
	CORE_FARMS = KAITET_FARMS + ["Karen", "Kapkolia", "Chepsito", "Kaptumbo",
		"Simotwo", "Torongo", "Post Harvest", "Eldama", "Westwood", "SIMO",
		"Greenville", "cheptiret"]

	def test_restricted_the_scope_is_exactly_the_farms_the_seed_names(self):
		self.assertEqual(
			sorted(config.farms_in_use(self.CORE_FARMS, self.KAITET_FARMS, restrict=True)),
			sorted(self.KAITET_FARMS))

	def test_unrestricted_the_scope_is_every_core_farm(self):
		"""The state that broke it: four approvers, sixteen farms in scope."""
		self.assertEqual(
			len(config.farms_in_use(self.CORE_FARMS, self.KAITET_FARMS, restrict=False)),
			len(self.CORE_FARMS))

	def test_the_seed_names_an_approver_role_for_every_farm_it_works(self):
		"""If it named a farm with no approver role, restricting would not be
		enough -- that farm would be in scope and uncovered."""
		for farm in self.KAITET_FARMS:
			with self.subTest(farm=farm):
				self.assertIn(farm, kaitet.FARM_APPROVER_ROLE)

	def test_no_approver_role_names_a_farm_the_seed_does_not_work(self):
		"""The other direction: an approver for a farm outside the scope is a row
		that can never be reached."""
		for farm in kaitet.FARM_APPROVER_ROLE:
			with self.subTest(farm=farm):
				self.assertIn(farm, self.KAITET_FARMS)


class TestTheScopedStagesAreCoverable(unittest.TestCase):
	def test_every_scoped_approval_stage_can_be_covered_per_farm(self):
		"""The validation only fires on scoped Approval stages. This asserts the
		seed's per-farm approvers are written for exactly those, so a stage
		cannot be left half-covered."""
		scoped = [s for s in approvals.CATALOGUE
			if s.scoped and s.kind == "Approval"]
		self.assertTrue(scoped, "no scoped approval stages to cover")
		text = function_source("seed_stage_approvers")
		self.assertIn("scoped", text)
		self.assertIn("FARM_APPROVER_ROLE", text)


if __name__ == "__main__":
	unittest.main()
