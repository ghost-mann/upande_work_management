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
