"""Every state the app's own code writes has to be an option it accepts.

Pure -- reads the shipped JSON and the generated api modules, no site::

    ./env/bin/python -m unittest work_management.tests.test_select_options -v
"""

import json
import os
import re
import unittest

from work_management import install

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def shipped_options(doctype, fieldname):
	with open(install.doctype_json(doctype)) as handle:
		doc = json.load(handle)
	for field in doc.get("fields", []):
		if field["fieldname"] == fieldname:
			return (field.get("options") or "").split("\n")
	raise AssertionError(f"{doctype} has no field {fieldname}")


class TestThePlanCloseStates(unittest.TestCase):
	"""The app wrote a state into custom_close_state that its own Select refused.

	A plan closes two ways. Somebody asks for it and it is granted -- "Close
	Requested" then "Closed" -- or the confirmed quantity reaches the target and
	the app closes it itself, which it records as "Completed" (api/actuals.py,
	"mark the plan complete so it drops out of the pickers"). Both count as
	closed everywhere it is read.

	Only three of the four were shipped as options. Nothing caught it because
	the writer is frappe.db.set_value, which does not validate -- so 591 of the
	live site's 1,518 plans carry a value the app would refuse, and any form
	save of one of them fails:

	    Close State cannot be "Completed". It should be one of "",
	    "Close Requested", "Closed"

	which is also what stopped those plans importing into a v16 site.
	"""

	FIELD = ("Work Management Planner", "custom_close_state")
	# every value the app itself puts in the field or branches on
	USED = ["", "Close Requested", "Closed", "Completed"]

	def test_every_state_the_app_uses_is_an_allowed_option(self):
		options = shipped_options(*self.FIELD)
		for state in self.USED:
			self.assertIn(state, options, f"the app uses {state!r} and the Select refuses it")

	def test_the_app_really_does_write_completed(self):
		"""Guards the pair: drop the writer and this test says so, so nobody
		removes the option because it "looks unused"."""
		with open(os.path.join(HERE, "api", "actuals.py")) as handle:
			source = handle.read()
		self.assertRegex(
			source,
			r'set_value\(\s*"Work Management Planner",\s*\w+,\s*"custom_close_state",\s*"Completed"',
		)

	def test_closed_and_completed_are_both_read_as_closed(self):
		with open(os.path.join(HERE, "api", "actuals.py")) as handle:
			source = handle.read()
		self.assertIn('("Closed", "Completed")', source)


class TestNoShippedSelectIsMissingAValueTheAppWrites(unittest.TestCase):
	"""The same class of bug, looked for everywhere rather than in one field.

	Scans the generated api modules for set_value calls that put a literal
	string into a Select field of a doctype this app ships, and checks the
	string is an option. It found custom_close_state; it will find the next one.
	"""

	CALL = re.compile(
		r'set_value\(\s*"(?P<doctype>[^"]+)",\s*[^,]+,\s*"(?P<field>\w+)",\s*"(?P<value>[^"]*)"'
	)

	def _selects(self, doctype):
		path = install.doctype_json(doctype)
		if not os.path.exists(path):
			return {}
		with open(path) as handle:
			doc = json.load(handle)
		return {f["fieldname"]: (f.get("options") or "").split("\n")
		        for f in doc.get("fields", []) if f.get("fieldtype") == "Select"}

	def test_every_literal_written_to_a_select_is_an_option(self):
		shipped = set(install.shipped_doctypes())
		offences = []
		api = os.path.join(HERE, "api")
		for filename in sorted(os.listdir(api)):
			if not filename.endswith(".py"):
				continue
			with open(os.path.join(api, filename)) as handle:
				source = handle.read()
			for match in self.CALL.finditer(source):
				doctype, field, value = (match.group("doctype"), match.group("field"),
				                         match.group("value"))
				if doctype not in shipped:
					continue
				options = self._selects(doctype).get(field)
				if options is not None and value not in options:
					offences.append(f"{filename}: {doctype}.{field} = {value!r} not in {options}")
		self.assertEqual(offences, [], "\n".join(offences))
