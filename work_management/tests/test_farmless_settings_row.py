"""A Settings farm row naming no farm must be dropped before anything saves.

`WM Farm.farm` has been reqd since this app's first commit, so no validated save
can produce a row without one. kentrout.local carried one anyway -- farm NULL,
project NULL, area_ha 0 -- written out of band: no tabVersion row, no Activity
Log entry, and nothing in this app sets `ignore_mandatory`.

A row like that says nothing and cannot: the project and area it could hold
belong to a farm it does not name. What it does do is refuse every save of Work
Management Settings, because `_validate_mandatory()` walks the children. That
took out `after_migrate -> approvals.after_migrate -> seed_stages()`, which
saves Settings on every migrate, and the error named the field rather than the
row:

    frappe.exceptions.MandatoryError: [Work Management Settings, ...]: farm

So one unattributable row made `bench migrate` unrunnable for the whole bench,
including the other seven apps, until somebody deleted it by hand in SQL.

Two things have to hold, and both are about order:

  - the cleanup runs from after_migrate, so a site repairs itself
  - it runs *before* the hook that saves Settings, or it repairs nothing this
    migrate and the migrate still dies

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_farmless_settings_row -v
"""

import ast
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CLEANUP = "work_management.install.drop_farmless_settings_rows"
# The hook that saves Work Management Settings, via seed_stages().
SAVES_SETTINGS = "work_management.approvals.after_migrate"


def after_migrate_hooks():
	from work_management import hooks

	value = hooks.after_migrate
	return [value] if isinstance(value, str) else list(value)


class TestTheCleanupIsWiredIn(unittest.TestCase):
	def test_it_runs_at_every_after_migrate(self):
		"""Not a patch: a patch runs once and cannot reach a site that logged it.

		The row was written outside the document path, so it can be written
		again the same way. A repair that only ever fires once would leave the
		next occurrence to be found the way this one was -- by a failed migrate.
		"""
		self.assertIn(CLEANUP, after_migrate_hooks())

	def test_it_runs_before_the_hook_that_saves_settings(self):
		hooks = after_migrate_hooks()
		self.assertLess(
			hooks.index(CLEANUP),
			hooks.index(SAVES_SETTINGS),
			"the cleanup has to precede the save it exists to unblock; after it, "
			"the migrate dies before the repair is reached",
		)


class TestTheCleanupItself(unittest.TestCase):
	"""Read off the source: the site-touching body cannot run without a site."""

	def source(self):
		with open(os.path.join(HERE, "install.py")) as handle:
			return handle.read()

	def function(self):
		for node in ast.walk(ast.parse(self.source())):
			if isinstance(node, ast.FunctionDef) and node.name == "drop_farmless_settings_rows":
				return node
		self.fail("install.drop_farmless_settings_rows is gone")

	def test_it_exists_and_is_callable_with_no_arguments(self):
		"""after_migrate calls it by dotted path with nothing to pass it."""
		args = self.function().args
		self.assertEqual(args.args, [])
		self.assertIsNone(args.vararg)
		self.assertIsNone(args.kwarg)

	def test_it_does_not_load_the_document_it_is_repairing(self):
		"""Loading Settings and saving it is exactly what the bad row prevents.

		So the repair goes through the query builder's delete, not get_doc().
		A get_doc here would raise the MandatoryError it is meant to clear.
		"""
		body = ast.dump(self.function())
		self.assertNotIn("get_doc", body)
		self.assertNotIn("get_single", body)

	def test_it_only_deletes_rows_with_no_farm(self):
		"""A row that names a farm is somebody's configuration, whatever else it holds."""
		body = ast.get_source_segment(self.source(), self.function())
		self.assertIn("IFNULL(farm, '') = ''", body)
		self.assertIn("parentfield = 'farms'", body)
		self.assertIn("parenttype = 'Work Management Settings'", body)

	def test_it_asks_table_exists_rather_than_the_raw_table_list(self):
		"""The mistake this very function shipped with first time round.

		See test_table_existence_checks -- get_tables() returns prefixed names,
		so `"WM Farm" not in frappe.db.get_tables()` returned every time and the
		cleanup silently did nothing while the migrate went on failing.
		"""
		body = ast.get_source_segment(self.source(), self.function())
		self.assertIn('frappe.db.table_exists("WM Farm")', body)

	def test_it_names_what_a_dropped_row_was_holding(self):
		"""A row with a project or an area held something. The print is the record."""
		body = ast.get_source_segment(self.source(), self.function())
		self.assertIn("print(", body)
		for field in ("project", "area_ha"):
			self.assertIn(field, body)
