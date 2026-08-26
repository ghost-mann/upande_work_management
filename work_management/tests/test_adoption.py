"""Guards on adopting doctypes a site already owns as custom ones.

The decisions are pure and tested without a site::

    ./env/bin/python -m unittest work_management.tests.test_adoption -v
"""

import glob
import json
import os
import unittest

from work_management import install


class TestWhatTheAppShips(unittest.TestCase):
	"""Adoption used to work from a hand-written list of nine names, frozen when
	the app had nine doctypes. It ships twenty-one. The twelve added since --
	Farm, Settings, Section and the rest -- had no adoption path at all, so a
	site owning one of them as a custom doctype kept it, and the app's own
	definition never landed.
	"""

	# The nine the old hand-list carried. None of them may be lost.
	ORIGINAL = [
		"Work Actuals Employee", "Work Assignment Employee", "Work Management Actuals",
		"Work Management Assigner", "Work Management Payment", "Work Management Planner",
		"Work Management Task", "Work Payment Line", "Work Planner Block",
	]
	# Added after the list was frozen; these are what the staleness cost.
	ADDED_SINCE = [
		"Work Management Farm", "Work Management Section", "Work Management Section Block",
		"Work Management Settings", "Work Management Master Plan",
	]

	def test_the_nine_the_old_list_named_are_still_covered(self):
		shipped = install.shipped_doctypes()
		for name in self.ORIGINAL:
			self.assertIn(name, shipped, name)

	def test_the_doctypes_added_since_are_covered_too(self):
		shipped = install.shipped_doctypes()
		for name in self.ADDED_SINCE:
			self.assertIn(name, shipped, f"{name} would keep a site's custom copy")

	def test_it_reads_the_files_rather_than_a_list_someone_maintains(self):
		"""Every name it returns has a folder of its own on disk."""
		here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
		for name in install.shipped_doctypes():
			folder = os.path.join(here, "work_management", "doctype", install.scrub(name))
			self.assertTrue(os.path.isdir(folder), f"{name} -> {folder}")

	def test_it_covers_every_doctype_json_the_app_ships(self):
		here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
		on_disk = set()
		for path in glob.glob(os.path.join(here, "work_management", "doctype", "*", "*.json")):
			with open(path) as handle:
				doc = json.load(handle)
			if doc.get("doctype") == "DocType":
				on_disk.add(doc["name"])
		self.assertEqual(set(install.shipped_doctypes()), on_disk)

	def test_it_does_not_pick_up_json_that_is_not_a_doctype(self):
		"""The app ships workspaces and a sidebar as JSON too."""
		for name in install.shipped_doctypes():
			self.assertNotIn(name, ("Work Management Setup", "Work Planning", "Work Delivery"))


class TestNothingDisappearsWithoutSaying(unittest.TestCase):
	"""Adopting force-imports the app's definition over the site's own copy. A
	custom doctype keeps every field on the DocType record itself, so a field
	the site added and the app does not define comes off the form. The column
	and its data stay in the table, but a reader has to be told."""

	def test_a_field_the_app_does_not_define_is_reported(self):
		self.assertEqual(
			install.extra_fieldnames(["farm", "block", "site_specific_note"], ["farm", "block"]),
			["site_specific_note"],
		)

	def test_a_definition_that_matches_reports_nothing(self):
		self.assertEqual(install.extra_fieldnames(["farm", "block"], ["farm", "block"]), [])

	def test_fields_the_app_adds_are_not_reported_as_losses(self):
		"""The app defining more than the site is the normal upgrade direction."""
		self.assertEqual(install.extra_fieldnames(["farm"], ["farm", "block", "disabled"]), [])

	def test_the_report_is_ordered_so_two_runs_read_the_same(self):
		self.assertEqual(install.extra_fieldnames(["z", "a", "farm"], ["farm"]), ["a", "z"])
