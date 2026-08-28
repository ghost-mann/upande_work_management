"""Farms come from Upande Core, and this app keeps its hands off that doctype.

Every check here reads the app's own source and shipped JSON, so it runs without
a site::

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_farm_source -v

The rules are worth a test rather than a habit because each one has a way of
looking harmless. Declaring a Custom Field on `Farm` reads like configuration
until two apps disagree about it on the same site. A Property Setter relabelling
`Farm.farm_name` reads like this app's taxonomy until it renames the field for
the spray plan, irrigation and sales screens too. And an exists() guard around a
`Farm` read reads like caution until it silently answers "no farms" on a site
where the whole app depends on there being some.
"""

import glob
import json
import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCTYPE_DIR = os.path.join(HERE, "work_management", "doctype")

OLD = "Work Management Farm"


def read(relpath):
	with open(os.path.join(HERE, relpath)) as handle:
		return handle.read()


def shipped_json():
	"""Every DocType definition this app ships, as (name, parsed json)."""
	out = []
	for path in glob.glob(os.path.join(DOCTYPE_DIR, "*", "*.json")):
		with open(path) as handle:
			doc = json.load(handle)
		if doc.get("doctype") == "DocType":
			out.append((doc["name"], doc))
	return out


def links_to(target):
	"""[(doctype, fieldname)] for every shipped Link field aimed at `target`."""
	hits = []
	for name, doc in shipped_json():
		for field in doc.get("fields", []):
			if field.get("fieldtype") == "Link" and field.get("options") == target:
				hits.append((name, field.get("fieldname")))
	return sorted(hits)


class TestUpandeCoreIsRequired(unittest.TestCase):
	def test_hooks_declares_upande_core_required(self):
		"""`Farm` is only unambiguous where Upande Core is the app that owns it.

		A doctype name is global. Upande Kaitet ships a `Farm` of its own, and on
		a site carrying that one instead, an unguarded read of "Farm" would find
		the wrong records rather than none -- the failure that a guard cannot
		catch and a required app prevents.
		"""
		self.assertIn('required_apps = ["upande_core"]', read("hooks.py"))


def core_field(dt, fieldname):
	"""The CORE_CUSTOM_FIELDS row for one field, or None."""
	from work_management import install

	for row in install.CORE_CUSTOM_FIELDS:
		if row[0] == dt and row[1] == fieldname:
			return row
	return None


class TestTheCustomFarmFieldsOnOtherDoctypes(unittest.TestCase):
	def test_employee_farm_is_declared_exactly_as_upande_kaitet_declares_it(self):
		"""Two apps declare Employee.custom_farm. They must not disagree.

		upande_kaitet ships it as `Unit/Division`, a Link to `Farm`, after
		`grade`. This app shipped it as a Link to its own farm doctype, after
		`department` -- and since the app's own definitions became authoritative,
		the next migrate would have moved the box up the form and repointed 3,241
		employees at a farm list missing three of the names in use. Declaring the
		same field identically settles it without either app having to win.
		"""
		row = core_field("Employee", "custom_farm")
		self.assertIsNotNone(row)
		label, fieldtype, options, insert_after = row[2:6]
		self.assertEqual(label, "Unit/Division")
		self.assertEqual(fieldtype, "Link")
		self.assertEqual(options, "Farm")
		self.assertEqual(insert_after, "grade")

	def test_warehouse_farm_is_not_declared_here_at_all(self):
		"""Warehouse.custom_farm is Upande Core's field, in every sense.

		Core ships it, exports it as the fixture `Warehouse-custom_farm`, hangs
		warehouse_hooks.py off it, orders the Warehouse form around it in its own
		install, and Row, Section and Bed all fetch_from it. Declaring it here
		too gains nothing and gives two apps a field to fight over.
		"""
		self.assertIsNone(core_field("Warehouse", "custom_farm"))

	def test_nothing_is_declared_on_core_farm(self):
		"""This app adds no field to Farm. It is read-only to us.

		Beyond it being another app's doctype: every row on the live site is
		missing `farm_type`, which is reqd, so a write would be rejected anyway.
		What this app knows and Core does not lives on the Settings farms table.
		"""
		from work_management import install

		self.assertEqual([row for row in install.CORE_CUSTOM_FIELDS if row[0] == "Farm"], [])


class TestTheFarmDoctypeIsGone(unittest.TestCase):
	def test_no_shipped_link_points_at_the_retired_doctype(self):
		"""Every farm link is a link to Upande Core's Farm now.

		The values behind these fields are farm names, and every name in use
		already exists in core `Farm` -- which is what made this a change of
		`options` rather than a rewrite of ten tables.
		"""
		self.assertEqual(links_to(OLD), [])

	def test_every_shipped_farm_link_points_at_core_farm(self):
		"""The count is asserted so a field cannot quietly stop being a farm.

		A future field that should carry a farm and does not would otherwise pass
		every other test here. Eleven: the nine on this app's own doctypes, the
		Settings farms table, and the farms-in-use picker.
		"""
		self.assertEqual(len(links_to("Farm")), 11)

	def test_the_app_no_longer_ships_a_farm_doctype(self):
		from work_management import install

		self.assertNotIn(OLD, install.shipped_doctypes())

	def test_nothing_reads_the_retired_doctype_any_more(self):
		"""No module asks the database about `Work Management Farm`.

		Scoped to reads rather than to the string: two docstrings still name it
		while explaining history, which is worth keeping. What must not survive
		is a live query, including a guarded one -- a guard around a doctype that
		no longer exists answers "no farms" forever, silently.
		"""
		read = re.compile(
			r"(get_all|get_list|get_value|get_doc|set_value|count|exists)\("
			r"[^)]*\"Work Management Farm\""
		)
		offenders = []
		for path in glob.glob(os.path.join(HERE, "**", "*.py"), recursive=True):
			rel = os.path.relpath(path, HERE)
			if rel.startswith("tests" + os.sep) or rel.startswith("patches" + os.sep):
				continue
			with open(path) as handle:
				if read.search(handle.read()):
					offenders.append(rel)
		self.assertEqual(sorted(offenders), [])

	def test_no_property_setter_is_written_against_core_farm(self):
		"""Relabelling `Farm` would relabel it for every app that reads it.

		taxonomy.FIELD_LABELS is the only place this app writes label Property
		Setters, so keeping `Farm` out of it is the whole rule. The cost is
		accepted and documented: a project can rename this app's own farm links,
		but not the farm record's own fields.
		"""
		from work_management import taxonomy

		for doctype, _fieldname, _template in taxonomy.FIELD_LABELS:
			self.assertNotIn(doctype, ("Farm", OLD), doctype)


class TestTheNavigationPointsAtCoreFarm(unittest.TestCase):
	"""The shipped workspace and sidebar name Core's Farm, not the retired one.

	Worth its own check because the site's copy of a workspace does not follow
	the shipped one automatically: desk.sync() re-imports only when the site's
	copy has fallen behind in *size*, and a link whose target was renamed is the
	same size as one that was not. On kaitet.local the old link survived, was
	hidden by hide_links_to_missing_doctypes() for pointing at nothing, and left
	the Setup workspace with no Farms link at all -- which is why the migration
	patch repoints it rather than trusting the import.
	"""

	PATHS = (
		os.path.join("work_management", "workspace", "work_management_setup",
			"work_management_setup.json"),
		os.path.join("workspace_sidebar", "work_management.json"),
	)

	def test_no_shipped_navigation_entry_names_the_retired_doctype(self):
		for relpath in self.PATHS:
			self.assertNotIn(OLD, read(relpath), relpath)

	def test_an_entry_a_site_already_has_gets_repointed(self):
		"""Not by the patch alone -- a patch runs once and cannot reach a site
		that logged an earlier version of it. desk.repoint_retired_links() does
		it at every after_migrate; the detail is in test_no_dangling_references.
		"""
		from work_management import desk

		self.assertEqual(desk.RETIRED.get(OLD), "Farm")
		self.assertIn(
			"work_management.desk.sync",
			read("hooks.py"),
			"the repair must be reachable from after_migrate",
		)


class TestTheNavigationBlockNamesNothingRetired(unittest.TestCase):
	"""The workspace's body is hand-written HTML, and it had the dead route in it.

	The Work Management workspace is a Custom HTML Block of tiles, each carrying
	`href`, `data-desk` (the route, rewritten per desk version) and `data-count`
	(the doctype whose row count the tile shows). None of that is a Workspace
	Link, so every structured scan came back clean while the "Farms" tile went on
	pointing at /app/work-management-farm -- `DocType Work Management Farm not
	found`, straight off the workspace's own landing page.

	Checked against what the app actually ships rather than against a list, so
	retiring any doctype in future fails here until its tile is dealt with.
	"""

	def block(self, suffix):
		path = os.path.join(HERE, "custom_html_block", "work_management_navigation" + suffix)
		with open(path) as handle:
			return handle.read()

	def test_no_tile_routes_to_the_retired_doctype(self):
		html = self.block(".html")
		self.assertNotIn("work-management-farm", html)
		self.assertNotIn(OLD, html)

	def test_every_counted_doctype_is_one_a_site_will_have(self):
		"""data-count drives a row-count query, so a stale name is a failing call.

		Allowed: a doctype this app ships, or one of the core/Upande doctypes the
		tiles deliberately point at.
		"""
		from work_management import install

		outside = {"Task", "Farm"}
		allowed = set(install.shipped_doctypes()) | outside
		counted = set(re.findall(r'data-count="([^"]+)"', self.block(".html")))
		self.assertTrue(counted, "no counted tiles found -- has the markup changed?")
		self.assertEqual(sorted(counted - allowed), [])

	def test_every_route_matches_the_doctype_the_tile_counts(self):
		"""href, data-desk and data-count must describe the same doctype.

		They drifted apart exactly once, and it took the Farms tile with it.
		"""
		from work_management.install import scrub

		pattern = re.compile(
			r'data-count="(?P<dt>[^"]+)"\s+data-desk="(?P<desk>[^"]+)"\s+href="/app/(?P<href>[^"]+)"'
		)
		mismatched = []
		for match in pattern.finditer(self.block(".html")):
			slug = scrub(match.group("dt")).replace("_", "-")
			if match.group("desk") != slug or match.group("href") != slug:
				mismatched.append(
					f'{match.group("dt")}: desk={match.group("desk")} href={match.group("href")} '
					f'expected {slug}'
				)
		self.assertEqual(mismatched, [])
