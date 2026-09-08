"""The controls that decide how a payment is sent live under a Payments heading.

They did not. `salary_component` sat alone under "Payroll", and the five controls
that actually govern sending -- the pay week's shape and the two toggles that
widen it -- sat at the bottom of "Who this system pays", a section otherwise
holding employment types, designations and categories.

So the heading a reader scans for send rules describes *eligibility*, and the
send rules hide beneath it. On kaitet-group that cost a real afternoon: the
payment screen refused with "no completed pay week", the fix was two checkboxes
that had shipped months earlier, and nobody found them -- the ask that reached me
was to build the feature and add a toggle for it.

A setting nobody can find is a setting that does not exist, so this is a layout
change with a behaviour: `allow_part_week_send` and `allow_day_range` are the two
that unstick a stuck payment run, and they belong beside the pay week they widen.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_the_payment_settings_are_findable -v
"""

import json
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(HERE, "work_management", "doctype",
	"work_management_settings", "work_management_settings.json")

# What governs how a payment run is sent, as opposed to who is eligible for one.
SEND_CONTROLS = ("salary_component", "pay_week_starts_on", "pay_week_ends_on",
	"pay_day", "allow_part_week_send", "allow_day_range")

# What "Who this system pays" is actually about.
ELIGIBILITY = ("tw_employment_type_rows", "tw_designation_rows", "tw_category_rows")


def doctype():
	with open(PATH) as handle:
		return json.load(handle)


def sections():
	"""{section label: [fieldnames under it]}, in the order the form renders."""
	d = doctype()
	by_name = {f["fieldname"]: f for f in d["fields"]}
	out, current = {}, None
	for fieldname in d["field_order"]:
		field = by_name.get(fieldname, {})
		kind = field.get("fieldtype")
		if kind in ("Section Break", "Tab Break"):
			current = field.get("label") or fieldname
			out.setdefault(current, [])
		elif current is not None and kind != "Column Break":
			out[current].append(fieldname)
	return out


class TestTheSendControlsAreUnderPayments(unittest.TestCase):
	def setUp(self):
		self.sections = sections()

	def test_there_is_a_payments_section(self):
		self.assertIn("Payments", self.sections,
			"no section called Payments; headings are: "
			+ ", ".join(repr(s) for s in self.sections))

	def test_every_send_control_is_in_it(self):
		payments = self.sections.get("Payments", [])
		for fieldname in SEND_CONTROLS:
			with self.subTest(field=fieldname):
				self.assertIn(fieldname, payments)

	def test_the_two_toggles_sit_with_the_pay_week_they_widen(self):
		"""Separating them is how they got lost the first time."""
		payments = self.sections.get("Payments", [])
		for fieldname in ("allow_part_week_send", "allow_day_range", "pay_week_starts_on"):
			self.assertIn(fieldname, payments, fieldname)

	def test_who_this_system_pays_is_left_to_eligibility(self):
		whopays = self.sections.get("Who this system pays", [])
		for fieldname in ELIGIBILITY:
			with self.subTest(field=fieldname):
				self.assertIn(fieldname, whopays)
		leaked = [f for f in SEND_CONTROLS if f in whopays]
		self.assertEqual(leaked, [],
			"send controls still filed under eligibility: " + ", ".join(leaked))

	def test_no_field_was_dropped_or_duplicated(self):
		d = doctype()
		self.assertEqual(sorted(d["field_order"]), sorted({f["fieldname"] for f in d["fields"]}),
			"field_order and fields disagree")
		self.assertEqual(len(d["field_order"]), len(set(d["field_order"])),
			"a fieldname appears twice in field_order")


if __name__ == "__main__":
	unittest.main()
