"""The desk shows a task's subject, and the patch that makes it so is shipped.

`taskName()` handles the five web screens. The desk is the other surface: a Link
field to Task renders the docname, which on a site autonaming
`TASK-.YYYY.-.#####` is `TASK-2026-00131`.

Four doctypes here link a Task -- Actuals, Assigner, Work Management Task and
Work Task Rate -- and none carried a fetched subject column. Adding one to each
was the obvious move and the wrong one: frappe already renders a link by its
`title_field` when `show_title_field_in_link` is set, everywhere at once, and
Task declares `title_field = "subject"` already. So one Property Setter covers
the lot.

The per-doctype columns on Planner and Master Plan Activity are not made
redundant by it and stay: those are grid columns, and a grid shows a column
rather than a rendered link.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_task_links_show_subjects -v
"""

import ast
import os
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATCH = os.path.join(APP, "patches", "v1_0", "show_task_subjects_in_links.py")
PATCHES_TXT = os.path.join(APP, "patches.txt")


def patch_source():
	with open(PATCH) as handle:
		return handle.read()


class TestThePatchIsShipped(unittest.TestCase):
	def test_the_patch_exists(self):
		self.assertTrue(os.path.exists(PATCH))

	def test_it_is_registered_to_run(self):
		with open(PATCHES_TXT) as handle:
			listed = [line.strip() for line in handle if line.strip()
				and not line.lstrip().startswith("#")]
		self.assertIn("work_management.patches.v1_0.show_task_subjects_in_links", listed)

	def test_it_is_listed_once(self):
		with open(PATCHES_TXT) as handle:
			body = handle.read()
		self.assertEqual(body.count("show_task_subjects_in_links"), 1)

	def test_it_parses_and_defines_execute(self):
		tree = ast.parse(patch_source())
		names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
		self.assertIn("execute", names)


class TestItSetsTheRightThing(unittest.TestCase):
	def test_it_sets_show_title_field_in_link_on_task(self):
		text = patch_source()
		self.assertIn('"show_title_field_in_link"', text)
		self.assertIn('make_property_setter("Task"', text)

	def test_it_is_a_doctype_property_not_a_field_one(self):
		"""`show_title_field_in_link` belongs to the DocType, so the setter needs
		for_doctype -- a DocField setter would be written and then ignored."""
		text = patch_source()
		self.assertIn("for_doctype=True", text)

	def test_it_edits_no_shipped_json(self):
		"""ERPNext's Task JSON stays as ERPNext ships it; the app's own files stay
		identical on every site. Same reasoning as approvals.stage_picker_options."""
		self.assertNotIn("task.json", patch_source())


class TestItRefusesToMakeThingsWorse(unittest.TestCase):
	def test_it_checks_a_title_field_exists_first(self):
		"""Turning the flag on where there is no title_field renders blanks in
		place of ids, which is worse than the id."""
		text = patch_source()
		self.assertIn("title_field", text)
		self.assertRegex(text, r"if not meta\.title_field")

	def test_it_does_nothing_when_already_set(self):
		self.assertRegex(patch_source(), r"if meta\.show_title_field_in_link")

	def test_it_skips_a_site_without_task(self):
		"""Task is ERPNext's. A site without it must not fail migrate."""
		self.assertRegex(patch_source(), r'exists\("DocType",\s*"Task"\)')

	def test_it_clears_the_cache(self):
		"""Meta is cached, so the flag would not be honoured until something else
		happened to clear it."""
		self.assertIn('frappe.clear_cache(doctype="Task")', patch_source())


class TestTheGridColumnsAreLeftAlone(unittest.TestCase):
	"""The earlier per-doctype fix covered grids and is not superseded."""

	def test_planner_and_activity_keep_their_subject_column(self):
		import json

		for doctype, folder in (("Work Management Planner", "work_management_planner"),
				("Work Management Master Plan Activity",
					"work_management_master_plan_activity")):
			path = os.path.join(APP, "work_management", "doctype", folder, folder + ".json")
			with open(path) as handle:
				fields = {f["fieldname"] for f in json.load(handle).get("fields", [])}
			with self.subTest(doctype=doctype):
				self.assertIn("task_subject", fields,
					"%s lost its grid subject column; a grid renders a column, not "
					"a link, so show_title_field_in_link does not cover it" % doctype)


if __name__ == "__main__":
	unittest.main()
