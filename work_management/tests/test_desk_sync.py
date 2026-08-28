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
		self.assertEqual(desk.nav_label("Farm", names), "Estates")
		self.assertEqual(desk.nav_label("Work Management Section", names), "Zones")

	def test_the_default_template_leaves_the_shipped_wording(self):
		self.assertEqual(desk.nav_label("Farm", self.names()), "Farms")

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


class TestTheAppsScreenIcon(unittest.TestCase):
	"""The icon was there and dead: link_type "External" with link_to null, and
	no icon name, so nothing rendered on the apps screen and clicking it went
	nowhere.

	Frappe 16.27's create_desktop_icons_from_workspace() cannot produce a
	working one -- it files the icon with link_type "Workspace Sidebar" while
	link_to names a Workspace, the insert fails link validation, and its own
	handler raises a second time on the way out. desk.py lets that fail rather
	than take the migrate down, which left the icon half-made. So the icon is
	built here instead, from the one shape known to work on a v16 site:

	    link_type "Workspace Sidebar", link_to and sidebar naming the app's
	    own Workspace Sidebar record, and an icon name that actually resolves.
	"""

	def test_it_is_the_shape_every_other_upande_app_uses(self):
		"""App + External + a real link + a real logo.

		Read off the working icons on a real v16 site: Ecommerce (upande_webshop),
		Upande Sensors and T&A all carry exactly this, and all three render their
		own logo on the apps screen. Ours was icon_type "Link" with no logo_url at
		all, so it drew a generic glyph while its neighbours drew themselves.

		The earlier note here warned that "External" had been tried and shown
		nothing -- but that attempt had link_to and icon both null, which is the
		actual reason it had nothing to draw. These three prove the shape works
		when the link and the logo are really there.
		"""
		f = desk.desktop_icon_fields()
		self.assertEqual(f["icon_type"], "App")
		self.assertEqual(f["link_type"], "External")
		self.assertEqual(f["link"], "/app/work-management")

	def test_the_link_is_the_route_the_apps_screen_hook_sends_people_to(self):
		"""Two destinations for one app is how the icon and the apps screen part."""
		from work_management import hooks

		self.assertEqual(desk.desktop_icon_fields()["link"], hooks.app_home)
		self.assertEqual(hooks.add_to_apps_screen[0]["route"], hooks.app_home)

	def test_it_carries_a_logo_so_it_draws_itself(self):
		"""The one field whose absence made this icon look unlike the others."""
		logo = desk.desktop_icon_fields().get("logo_url") or ""
		self.assertTrue(logo.startswith("/assets/work_management/"), logo)

	def test_the_logo_is_a_file_this_app_actually_ships(self):
		"""Each Upande app ships its own asset rather than pointing at another's,
		so the icon cannot break when a neighbour is absent or renames a file."""
		import os

		logo = desk.desktop_icon_fields()["logo_url"]
		here = os.path.dirname(os.path.dirname(os.path.abspath(desk.__file__)))
		path = os.path.join(here, "work_management",
			logo.replace("/assets/work_management/", "public/"))
		self.assertTrue(os.path.exists(path), path)

	def test_the_logo_is_the_one_the_apps_screen_hook_already_names(self):
		"""hooks.py add_to_apps_screen and this record must agree, or the apps
		screen and the desk switcher show two different pictures."""
		from work_management import hooks

		self.assertEqual(
			desk.desktop_icon_fields()["logo_url"],
			hooks.add_to_apps_screen[0]["logo"],
		)

	def test_it_clears_the_fields_the_old_shape_used(self):
		"""Omitting them is not enough, because the record is updated in place.

		The previous shape set link_to, sidebar and icon. Leaving them out of this
		dict left them behind, and a stale link_to beside link_type "External"
		made Frappe resolve it as a doctype -- `DocType External not found` when
		saving an otherwise correct record.
		"""
		f = desk.desktop_icon_fields()
		for vacated in ("link_to", "sidebar", "icon"):
			self.assertIn(vacated, f, vacated)
			self.assertFalse(f[vacated], vacated)

	def test_it_is_attributed_to_this_app(self):
		self.assertEqual(desk.desktop_icon_fields()["app"], desk.APP)

	def test_it_is_visible(self):
		self.assertFalse(desk.desktop_icon_fields().get("hidden"))

	def test_a_caller_can_override_the_label(self):
		self.assertEqual(desk.desktop_icon_fields(label="Estates")["label"], "Estates")


class TestALinkToSomethingAbsentHidesItself(unittest.TestCase):
	"""A workspace link whose doctype is not on the site is a 404 waiting for
	somebody to click it. The app ships links for every doctype it owns, but a
	site can be missing one -- installed over an older layout, or without the
	app that owns a shared target like Task. Hiding is reversible: the link
	comes back the moment the doctype does.
	"""

	ROWS = [
		{"name": "a", "link_type": "DocType", "link_to": "Farm", "hidden": 0},
		{"name": "b", "link_type": "DocType", "link_to": "Nonexistent Doctype", "hidden": 0},
		{"name": "c", "link_type": "DocType", "link_to": "Farm", "hidden": 1},
		{"name": "d", "link_type": "DocType", "link_to": "Gone Away", "hidden": 1},
	]
	HAVE = {"Farm"}

	def test_a_link_whose_target_is_missing_is_hidden(self):
		hide, show = desk.plan_link_visibility(self.ROWS, self.HAVE)
		self.assertIn("b", hide)

	def test_a_link_already_hidden_for_a_missing_target_is_left_alone(self):
		hide, show = desk.plan_link_visibility(self.ROWS, self.HAVE)
		self.assertNotIn("d", hide)

	def test_a_link_hidden_for_a_target_that_came_back_is_shown_again(self):
		hide, show = desk.plan_link_visibility(self.ROWS, self.HAVE)
		self.assertIn("c", show)

	def test_a_working_visible_link_is_not_touched(self):
		hide, show = desk.plan_link_visibility(self.ROWS, self.HAVE)
		self.assertNotIn("a", hide)
		self.assertNotIn("a", show)

	def test_a_non_doctype_link_is_never_judged(self):
		"""A URL or a report link has no doctype to look up."""
		rows = [{"name": "u", "link_type": "URL", "link_to": "https://example.com", "hidden": 0},
			{"name": "r", "link_type": "Report", "link_to": "Some Report", "hidden": 0}]
		hide, show = desk.plan_link_visibility(rows, set())
		self.assertEqual((hide, show), ([], []))

	def test_nothing_to_do_is_two_empty_lists(self):
		self.assertEqual(desk.plan_link_visibility([], set()), ([], []))


class TestTheAppsScreenOpensTheDesk(unittest.TestCase):
	"""Clicking the app on the apps screen must land in the desk, on this app's
	workspace, so the sidebar is there and the reader chooses where to go.

	It used to point at /work-management -- the web dashboard -- so the app
	icon jumped straight past the desk into one screen. The apps screen reads
	this from hooks, not from the Desktop Icon, which is why fixing the icon
	did not fix the destination.
	"""

	@classmethod
	def setUpClass(cls):
		import work_management.hooks as h
		cls.entry = h.add_to_apps_screen[0]
		cls.app_home = getattr(h, "app_home", None)

	def test_it_is_a_desk_route(self):
		self.assertTrue(self.entry["route"].startswith("/app/"), self.entry["route"])

	def test_it_is_not_the_web_dashboard(self):
		"""The regression this guards: /work-management is a www page."""
		self.assertNotEqual(self.entry["route"].rstrip("/"), "/work-management")

	def test_it_names_the_workspace_the_app_ships(self):
		slug = desk.WORKSPACE.lower().replace(" ", "-")
		self.assertEqual(self.entry["route"], "/app/" + slug)

	def test_app_home_agrees_with_it(self):
		"""Two doors, one destination."""
		self.assertEqual(self.app_home, self.entry["route"])
