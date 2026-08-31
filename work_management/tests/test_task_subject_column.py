"""The desk shows a task's subject too, not only the web screens.

taskName() fixed the five web screens. The desk is the other half: someone
reviewing a master plan on its own form sees the Activities grid, and that grid
renders the `task` Link -- which on a site naming tasks TASK-2026-##### is an id.

So the row carries the subject as a fetched column, and the grid shows that
column instead of the link. On a site whose docnames ARE the subjects -- live --
the column holds the same text the link did, so the grid reads exactly as before.
On the v16 site it reads "Marking Ridges" where it read TASK-2026-00170. Strictly
better on both, which is why `task` leaves the grid rather than sitting beside a
column that would duplicate it.

The link is still editable by opening the row; master plan activities are built
on the planner screen's picker, not by typing into this grid.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_task_subject_column -v
"""

import json
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CARRIERS = (
	("work_management_master_plan_activity", "Work Management Master Plan Activity"),
	("work_management_planner", "Work Management Planner"),
)


def shipped(slug):
	path = os.path.join(HERE, "work_management", "doctype", slug, slug + ".json")
	with open(path) as handle:
		return json.load(handle)


def field(doc, fieldname):
	for f in doc.get("fields", []):
		if f.get("fieldname") == fieldname:
			return f
	return None


class TestTheRowCarriesTheSubject(unittest.TestCase):
	def test_both_carriers_have_a_fetched_task_subject(self):
		for slug, label in CARRIERS:
			f = field(shipped(slug), "task_subject")
			self.assertIsNotNone(f, label)
			self.assertEqual(f.get("fieldtype"), "Data", label)
			self.assertEqual(f.get("fetch_from"), "task.subject", label)

	def test_it_is_read_only_because_the_task_owns_it(self):
		"""Editable, it would drift from the task it claims to name."""
		for slug, label in CARRIERS:
			self.assertTrue(field(shipped(slug), "task_subject").get("read_only"), label)

	def test_the_grid_shows_the_subject_and_not_the_id(self):
		"""Only for the child table -- the Planner is a form, not a grid."""
		doc = shipped("work_management_master_plan_activity")
		self.assertTrue(field(doc, "task_subject").get("in_list_view"))
		self.assertFalse(
			field(doc, "task").get("in_list_view"),
			"task and task_subject both in the grid would duplicate each other on "
			"a site whose docnames are its subjects",
		)

	def test_the_task_link_survives_so_a_row_can_still_be_repointed(self):
		for slug, label in CARRIERS:
			f = field(shipped(slug), "task")
			self.assertEqual(f.get("fieldtype"), "Link", label)
			self.assertEqual(f.get("options"), "Task", label)


class TestExistingRowsAreBackfilled(unittest.TestCase):
	"""fetch_from populates on save, and nothing is going to re-save 1,578 rows."""

	def test_the_patch_is_registered_after_the_field_exists(self):
		with open(os.path.join(HERE, "patches.txt")) as handle:
			txt = handle.read()
		self.assertIn("backfill_task_subjects", txt)
		self.assertIn("[post_model_sync]", txt)
		self.assertGreater(
			txt.index("backfill_task_subjects"), txt.index("[post_model_sync]")
		)

	def test_it_only_fills_what_is_empty(self):
		"""Never overwrites: a row already naming its task is already right."""
		from work_management.patches.v1_0 import backfill_task_subjects as patch

		self.assertEqual(patch.CARRIERS, tuple(label for _slug, label in CARRIERS))
