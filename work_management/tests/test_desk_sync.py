# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Guards on keeping the desk surfaces attached to this app.

Frappe skips a standard JSON when the record in the database has a `modified`
newer than the one in the file (frappe/modules/import_file.py). A Work
Management workspace built in the desk therefore beats the one this app ships,
and the surviving record keeps its own module and app -- typically Projects and
erpnext. Every desk surface is derived from those two fields:

  * bootinfo.app_data joins Workspace.module to Module Def.app_name, so the app
    ends up with no workspaces and an empty route;
  * create_desktop_icons_from_workspace() files the icon under the wrong app;
  * get_workspaces() raises PermissionError for anyone without the other app's
    module, so the workspace disappears entirely.

The repair decision is pure, so it is tested here without a site::

    ./env/bin/python -m unittest work_management.tests.test_desk_sync -v
"""

import contextlib
import io
import json
import unittest

import frappe

from work_management import desk, taxonomy


def record(module=desk.MODULE, app=desk.APP, parent_page=""):
	return {"name": desk.WORKSPACE, "module": module, "app": app, "parent_page": parent_page}


def counts(links=0, shortcuts=0, custom_blocks=0):
	return {"links": links, "shortcuts": shortcuts, "custom_blocks": custom_blocks}


def shipped(links=0, shortcuts=0, custom_blocks=0, parent_page=""):
	return {
		"links": [None] * links,
		"shortcuts": [None] * shortcuts,
		"custom_blocks": [None] * custom_blocks,
		"parent_page": parent_page,
	}


class TestWorkspaceRepairDecision(unittest.TestCase):
	def test_a_workspace_matching_what_the_app_ships_is_left_alone(self):
		self.assertIsNone(
			desk.workspace_repair_reason(record(), counts(links=14), shipped(links=14))
		)

	def test_a_missing_workspace_is_repaired(self):
		self.assertEqual(
			desk.workspace_repair_reason(None, counts(), shipped(links=14)), "missing"
		)

	def test_a_workspace_owned_by_another_module_is_repaired(self):
		"""The live site's workspace was built in the desk under Projects."""
		self.assertEqual(
			desk.workspace_repair_reason(
				record(module="Projects"), counts(links=14), shipped(links=14)
			),
			"module",
		)

	def test_a_workspace_attributed_to_another_app_is_repaired(self):
		self.assertEqual(
			desk.workspace_repair_reason(
				record(app="erpnext"), counts(links=14), shipped(links=14)
			),
			"app",
		)

	def test_a_blank_app_counts_as_wrong_attribution(self):
		self.assertEqual(
			desk.workspace_repair_reason(record(app=None), counts(links=5), shipped(links=5)),
			"app",
		)

	def test_a_child_workspace_detached_from_its_parent_is_repaired(self):
		"""A child with no parent_page stops nesting under Work Management."""
		self.assertEqual(
			desk.workspace_repair_reason(
				record(parent_page=""), counts(links=3), shipped(links=3, parent_page="Work Management")
			),
			"parent",
		)

	def test_a_workspace_missing_cards_the_app_ships_is_resynced(self):
		"""Bumping `modified` in the JSON is easy to forget; this does not rely on it."""
		self.assertEqual(
			desk.workspace_repair_reason(record(), counts(links=9), shipped(links=14)),
			"stale",
		)

	def test_a_lost_shortcut_is_noticed_as_well_as_a_lost_link(self):
		self.assertEqual(
			desk.workspace_repair_reason(
				record(), counts(links=14, shortcuts=0), shipped(links=14, shortcuts=5)
			),
			"stale",
		)

	def test_a_tile_grid_workspace_with_no_links_is_not_treated_as_empty(self):
		"""The parent's whole body is one custom block, so zero links is correct.

		Reading "no links" as broken would make the repair fire on every migrate
		and never settle.
		"""
		self.assertIsNone(
			desk.workspace_repair_reason(
				record(), counts(custom_blocks=1), shipped(custom_blocks=1)
			)
		)

	def test_a_tile_grid_workspace_that_lost_its_block_is_repaired(self):
		self.assertEqual(
			desk.workspace_repair_reason(record(), counts(), shipped(custom_blocks=1)),
			"stale",
		)

	def test_module_is_checked_before_content(self):
		"""Reporting the most fundamental problem makes the log useful."""
		self.assertEqual(
			desk.workspace_repair_reason(
				record(module="Projects"), counts(), shipped(links=14)
			),
			"module",
		)


class TestShippedDefinitions(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.definitions = list(desk.workspace_definitions())

	def test_the_app_ships_a_parent_and_its_children(self):
		names = {name for name, _p, _s in self.definitions}
		self.assertIn(desk.WORKSPACE, names)
		self.assertGreater(len(names), 1, "the sidebar's per-area Overviews need child workspaces")

	def test_every_shipped_workspace_claims_this_module_and_app(self):
		for name, _path, shipped in self.definitions:
			self.assertEqual(shipped["module"], desk.MODULE, name)
			self.assertEqual(shipped["app"], desk.APP, name)

	def test_children_nest_under_the_parent_and_the_parent_does_not(self):
		for name, _path, shipped in self.definitions:
			parent = shipped.get("parent_page") or ""
			if name == desk.WORKSPACE:
				self.assertEqual(parent, "", "the parent must not nest under anything")
			else:
				self.assertEqual(parent, desk.WORKSPACE, name)

	def test_the_parent_renders_the_navigation_block(self):
		import json

		shipped = json.loads(desk.WORKSPACE_JSON.read_text())
		blocks = [b["custom_block_name"] for b in shipped.get("custom_blocks") or []]
		self.assertEqual(blocks, [desk.NAV_BLOCK])
		content = json.loads(shipped["content"])
		self.assertEqual([b["type"] for b in content], ["custom_block"])

	def test_the_navigation_block_sources_are_shipped(self):
		for ext in ("html", "css", "js"):
			path = desk.BLOCK_DIR / f"{desk.BLOCK_SLUG}.{ext}"
			self.assertTrue(path.exists(), path)
			self.assertGreater(path.stat().st_size, 200, path)

	def test_the_shipped_sidebar_json_is_where_the_repair_looks_for_it(self):
		self.assertTrue(desk.SIDEBAR_JSON.exists(), desk.SIDEBAR_JSON)

	def test_repairing_to_the_shipped_files_settles(self):
		"""A repair that never satisfies its own rule would run on every migrate."""
		for name, _path, shipped in self.definitions:
			settled = {
				"name": name,
				"module": shipped["module"],
				"app": shipped["app"],
				"parent_page": shipped.get("parent_page") or "",
			}
			self.assertIsNone(
				desk.workspace_repair_reason(settled, desk.shipped_counts(shipped), shipped),
				name,
			)


if __name__ == "__main__":
	unittest.main()


class TestARebuildStepThatFails(unittest.TestCase):
	"""A broken desk rebuild step must not take `bench migrate` down with it.

	Frappe 16.27 ships a create_desktop_icons_from_workspace() that raises on
	every workspace it tries to file, and whose own error handler raises a
	second time on the way out. That reaches sites through this app's
	after_migrate hook, so the call has to be survivable.
	"""

	def test_a_step_that_works_reports_nothing(self):
		self.assertIsNone(desk.without_aborting_the_migrate(lambda: None, "do the thing"))

	def test_a_step_that_raises_is_reported_not_propagated(self):
		def boom():
			raise TypeError("'list' object is not callable")

		# The note is printed and logged on purpose; swallow it so a passing
		# run stays quiet and a real failure still stands out.
		noise = io.StringIO()
		with contextlib.redirect_stdout(noise), contextlib.redirect_stderr(noise):
			note = desk.without_aborting_the_migrate(boom, "rebuild the desktop icons")
		self.assertIn("rebuild the desktop icons", note)
		self.assertIn("TypeError", note)
		self.assertIn("'list' object is not callable", note)

	def test_the_step_actually_ran(self):
		calls = []
		desk.without_aborting_the_migrate(lambda: calls.append(1), "count")
		self.assertEqual(calls, [1])


class TestNavigationLabelsFollowTheTaxonomy(unittest.TestCase):
	"""A Workspace Link and a Sidebar Item are records, not doctype fields, so
	the Property Setters that relabel the forms never reach them: a site
	calling them Estates and Plots still read "Farms" and "Sections" down the
	side of the desk.
	"""

	def names(self, **overrides):
		base = {
			"tax_bu_enabled": 0, "tax_bu_singular": "", "tax_bu_plural": "",
			"tax_top_singular": "", "tax_top_plural": "",
			"tax_unit_singular": "", "tax_unit_plural": "",
			"tax_section_singular": "", "tax_section_plural": "",
		}
		base.update(overrides)
		return taxonomy.resolve(frappe._dict(base))

	def test_a_renamed_level_reaches_the_navigation(self):
		names = self.names(tax_top_plural="Estates", tax_section_plural="Zones")
		self.assertEqual(desk.nav_label("Work Management Farm", names), "Estates")
		self.assertEqual(desk.nav_label("Work Management Section", names), "Zones")

	def test_the_default_template_leaves_the_shipped_wording(self):
		self.assertEqual(desk.nav_label("Work Management Farm", self.names()), "Farms")

	def test_an_entry_that_names_no_level_is_left_alone(self):
		"""Returning "" or the label would invite a caller to write it back."""
		self.assertIsNone(desk.nav_label("Task", self.names()))

	def test_every_shipped_navigation_label_that_names_a_level_is_covered(self):
		"""The reverse guard, as for the field catalogue: a link added later
		must not quietly opt out of the taxonomy."""
		import re

		words = sorted(
			{w for level in taxonomy.LEVELS for w in (level.singular, level.plural)},
			key=len, reverse=True,
		)
		pattern = re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b")
		missing = []
		for entries in self.shipped_navigation():
			for entry in entries:
				label = entry.get("label") or ""
				if pattern.search(label) and entry.get("link_to") not in desk.NAV_LABELS:
					missing.append(f"{label!r} -> {entry.get('link_to')!r}")
		self.assertEqual(sorted(missing), [], "\n".join(sorted(missing)))

	@staticmethod
	def shipped_navigation():
		"""Every navigation entry the app ships, workspace links and sidebar
		items alike."""
		for _name, path, shipped in desk.workspace_definitions():
			yield shipped.get("links") or []
		yield json.loads(desk.SIDEBAR_JSON.read_text()).get("items") or []

	def test_the_covered_links_are_really_shipped(self):
		"""A stale entry in NAV_LABELS would relabel nothing and hide a gap."""
		shipped = {
			entry.get("link_to")
			for entries in self.shipped_navigation() for entry in entries
		}
		for link_to in desk.NAV_LABELS:
			self.assertIn(link_to, shipped, link_to)
