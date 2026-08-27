"""Reading a doctype the site has not got must be guarded.

frappe.get_all() on an absent doctype raises rather than returning nothing, and
the app's screens run on two shapes of site: one where this app owns the
doctypes, and one that built the system in the UI first and has its own. A read
without a guard is not a narrower result, it is a dead screen -- it took out the
payment screen once and the Master Plan screen once.

Pure -- reads the generated api modules, no site::

    ./env/bin/python -m unittest work_management.tests.test_api_doctype_guards -v
"""

import glob
import json
import os
import re
import unittest

from work_management import install

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = os.path.join(HERE, "api")

# Doctypes this app ships that a legacy site genuinely may not have. Settings is
# left out: it is read through get_single_value, which answers None on a site
# without it rather than raising.
FRAGILE = ["Work Management Farm", "Work Management Section", "Work Management Section Block",
           "Work Management Payable Employment Type", "Work Management Payable Designation",
           "Work Management Payable Category"]

READ = re.compile(r'(?:frappe\.db\.get_all|frappe\.get_all|frappe\.get_list)\(\s*"(?P<dt>[^"]+)"')


def parent_of():
	"""{child doctype: parent doctype} from the shipped definitions.

	A child table cannot exist on a site without its parent, so a guard naming
	the parent guards the child too -- which is how the dashboard does it, with
	one exists() check on Work Management Section standing in front of every
	read of its block table.
	"""
	owners = {}
	for path in glob.glob(os.path.join(HERE, "work_management", "doctype", "*", "*.json")):
		with open(path) as handle:
			doc = json.load(handle)
		if doc.get("doctype") != "DocType":
			continue
		for field in doc.get("fields", []):
			if field.get("fieldtype") == "Table" and field.get("options"):
				owners[field["options"]] = doc["name"]
	return owners


class TestEveryFragileReadIsGuarded(unittest.TestCase):
	def test_the_fragile_list_is_all_doctypes_this_app_ships(self):
		shipped = set(install.shipped_doctypes())
		for name in FRAGILE:
			self.assertIn(name, shipped, name)

	def test_a_module_that_reads_one_asks_whether_it_exists(self):
		offences = []
		for filename in sorted(os.listdir(API)):
			if not filename.endswith(".py"):
				continue
			with open(os.path.join(API, filename)) as handle:
				source = handle.read()
			owners = parent_of()
			for match in READ.finditer(source):
				doctype = match.group("dt")
				if doctype not in FRAGILE:
					continue
				acceptable = [doctype]
				if doctype in owners:
					acceptable.append(owners[doctype])
				guard = 'exists("DocType", "%s")' % doctype
				if not any('exists("DocType", "%s")' % d in source for d in acceptable):
					line = source[: match.start()].count("\n") + 1
					offences.append("%s:%d reads %s with no %s anywhere in the module"
					                % (filename, line, doctype, guard))
		self.assertEqual(offences, [], "\n".join(offences))
