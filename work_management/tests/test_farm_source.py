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
