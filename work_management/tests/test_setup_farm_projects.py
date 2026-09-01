"""Setting each farm's cost project in one command.

Doing this by hand means opening Settings, adding a row per farm, and picking a
project from a Link that offers every project on the site -- 105 on the dev site,
of which 86 have Tasks and two are the answer. That is a lot of chances to pick
the greenhouse build instead of the activity list, and the mistake is quiet: the
Master Plan screen simply offers the wrong activities.

So there are two commands. One shows which projects look like activity
catalogues, ranked, so the right ids can be read off. The other writes the
mapping, validating each farm and project before it does.

The parts with judgement in them are tested here. The two database reads are one
query each and are exercised by running both commands against a real site.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_setup_farm_projects -v
"""

import unittest

from work_management import setup


def row(farm, project=None):
	"""A farms-table row as the planner sees it."""
	return {"farm": farm, "project": project}


class TestPlanningWhatToWrite(unittest.TestCase):
	PLAN = staticmethod(setup.plan_farm_projects)

	def test_a_farm_with_no_row_is_added(self):
		plan = self.PLAN([], {"Lokitela": "PROJ-0031"})
		self.assertEqual(plan["add"], [("Lokitela", "PROJ-0031")])
		self.assertEqual(plan["change"], [])
		self.assertEqual(plan["unchanged"], [])

	def test_a_farm_whose_row_has_no_project_is_changed(self):
		plan = self.PLAN([row("Lokitela")], {"Lokitela": "PROJ-0031"})
		self.assertEqual(plan["add"], [])
		self.assertEqual(plan["change"], [("Lokitela", None, "PROJ-0031")])

	def test_a_farm_pointed_at_a_different_project_is_changed(self):
		plan = self.PLAN([row("Lokitela", "PROJ-0005")], {"Lokitela": "PROJ-0031"})
		self.assertEqual(plan["change"], [("Lokitela", "PROJ-0005", "PROJ-0031")])

	def test_a_farm_already_correct_is_left_alone(self):
		"""Idempotent: running it twice must not rewrite Settings the second
		time, so a save that could trip the stranded-approver check is skipped."""
		plan = self.PLAN([row("Lokitela", "PROJ-0031")], {"Lokitela": "PROJ-0031"})
		self.assertEqual(plan["unchanged"], ["Lokitela"])
		self.assertEqual(plan["add"], [])
		self.assertEqual(plan["change"], [])

	def test_rows_the_mapping_does_not_mention_are_untouched(self):
		"""A partial mapping must not clear the farms it says nothing about."""
		plan = self.PLAN(
			[row("Saboti", "PROJ-0031"), row("Endebess", "PROJ-0032")],
			{"Saboti": "PROJ-0031"})
		self.assertEqual(plan["add"], [])
		self.assertEqual(plan["change"], [])
		self.assertNotIn("Endebess", str(plan["add"] + plan["change"]))

	def test_several_farms_at_once(self):
		plan = self.PLAN([], {
			"Saboti": "PROJ-0031", "Lokitela": "PROJ-0031",
			"Vale": "PROJ-0031", "Endebess": "PROJ-0032"})
		self.assertEqual(len(plan["add"]), 4)

	def test_the_order_is_the_mappings_not_a_dict_accident(self):
		"""Printed output has to be stable to be reviewable."""
		plan = self.PLAN([], {"Vale": "P1", "Endebess": "P2", "Saboti": "P3"})
		self.assertEqual([f for f, _p in plan["add"]],
			["Endebess", "Saboti", "Vale"])

	def test_nothing_to_do_is_a_valid_plan(self):
		plan = self.PLAN([], {})
		self.assertEqual(plan["add"], [])
		self.assertEqual(plan["change"], [])

	def test_a_blank_project_is_refused_rather_than_written(self):
		"""Clearing a project is what causes "no cost project"; if somebody means
		to do it they can do it in the form, not by passing an empty string."""
		with self.assertRaises(ValueError):
			self.PLAN([], {"Lokitela": ""})

	def test_a_blank_farm_is_refused(self):
		with self.assertRaises(ValueError):
			self.PLAN([], {"": "PROJ-0031"})


class TestRankingTheCandidates(unittest.TestCase):
	"""Which projects look like activity catalogues. The signal is how many Tasks
	a project carries, but the count alone is not enough -- an employee separation
	carries 14 and a greenhouse build 21, and neither is something a week's labour
	is planned against."""

	RANK = staticmethod(setup.rank_candidates)

	ROWS = [
		{"name": "P-SEP-1", "project_name": "Employee Separation : A B", "tasks": 14},
		{"name": "PROJ-0031", "project_name": "Kaitet Avocado Tasks", "tasks": 64},
		{"name": "PROJ-0026", "project_name": "Kapkolia Greenhouse 19", "tasks": 21},
		{"name": "PROJ-0032", "project_name": "Kaitet Coffee Tasks", "tasks": 49},
		{"name": "P-EMPTY", "project_name": "Nothing Here", "tasks": 0},
	]

	def test_projects_with_no_tasks_are_dropped(self):
		"""A project with no Tasks offers no activities, so it can never be the
		answer."""
		names = [r["name"] for r in self.RANK(self.ROWS)]
		self.assertNotIn("P-EMPTY", names)

	def test_the_likely_ones_come_first(self):
		names = [r["name"] for r in self.RANK(self.ROWS)]
		self.assertEqual(names[:2], ["PROJ-0031", "PROJ-0032"])

	def test_a_task_catalogue_is_flagged_as_likely(self):
		flagged = {r["name"]: r["likely"] for r in self.RANK(self.ROWS)}
		self.assertTrue(flagged["PROJ-0031"])
		self.assertTrue(flagged["PROJ-0032"])

	def test_one_off_jobs_are_not_flagged(self):
		flagged = {r["name"]: r["likely"] for r in self.RANK(self.ROWS)}
		self.assertFalse(flagged["PROJ-0026"])
		self.assertFalse(flagged["P-SEP-1"])

	def test_an_employee_separation_is_never_likely_however_many_tasks(self):
		"""These are generated per leaver, so on a big site they crowd out the
		real answer by sheer number."""
		rows = [{"name": "X", "project_name": "Employee Separation : Somebody",
			"tasks": 500}]
		self.assertFalse(self.RANK(rows)[0]["likely"])

	def test_unlikely_ones_are_still_listed(self):
		"""Ranked, not filtered: a site may well name its activity project
		something this heuristic does not recognise, and hiding it would send
		somebody to the form to guess again."""
		names = [r["name"] for r in self.RANK(self.ROWS)]
		self.assertIn("PROJ-0026", names)
		self.assertIn("P-SEP-1", names)

	def test_ties_break_by_name_so_the_list_is_stable(self):
		rows = [{"name": "B", "project_name": "B Tasks", "tasks": 10},
			{"name": "A", "project_name": "A Tasks", "tasks": 10}]
		self.assertEqual([r["name"] for r in self.RANK(rows)], ["A", "B"])


class TestNeitherCommandGuesses(unittest.TestCase):
	def test_setting_projects_takes_an_explicit_mapping(self):
		"""It must not pick for somebody. Which project a farm's costs land in is
		an accounting decision, and a wrong guess is a plan budgeted against the
		wrong cost centre."""
		import inspect

		signature = inspect.signature(setup.set_farm_cost_projects)
		self.assertIn("mapping", signature.parameters)
		self.assertIsNone(signature.parameters["mapping"].default)

	def test_the_candidate_listing_writes_nothing(self):
		import inspect

		source = inspect.getsource(setup.cost_project_candidates)
		for forbidden in (".save(", ".insert(", "set_value", "db.commit", "delete"):
			self.assertNotIn(forbidden, source)


if __name__ == "__main__":
	unittest.main()
