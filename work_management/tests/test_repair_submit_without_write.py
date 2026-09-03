"""The live rows, on a site that already has the bad grant in its database.

Fixing the shipped JSON and the seed settles what a *new* site gets. It settles
nothing on kaitet.local, for a reason worth stating plainly: once a doctype has
Custom DocPerms, Frappe reads those and ignores the shipped permissions
altogether. So the corrected JSON never applies there, and the site goes on
refusing every permission write on the doctype:

    For Accounts Manager at level 0 in Work Management Planner in row 2:
    Cannot set Submit, Cancel, Amend without Write

kaitet.local carries two such rows for `Work Management Planner` -- Accounts
Manager and General Manager -- one inherited from the shipped JSON when the
doctype was customised, one put there by `seed.kaitet.restore_docperms()`. And
restore_docperms() skips a doctype/role that already has a row, so re-seeding
will not correct them either. Nothing short of touching the rows does.

The scope is the point of most of this file. That same site has eighteen more
invalid rows on doctypes belonging to other apps -- Pick List, Stock Entry, BOM,
Purchase Invoice, Tractor Daily Task and others. They are the same defect and
they are not this app's to repair: silently rewriting another app's permissions
during our migrate would be a far worse bug than the one being fixed. So the
repair is bounded by install.shipped_doctypes() and asserted to be.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_repair_submit_without_write -v
"""

import unittest

from work_management.patches.v1_0 import repair_submit_without_write as patch


class TestWhichRightsToClear(unittest.TestCase):
	def test_a_row_with_write_is_left_alone(self):
		"""Legal already. Every other submittable doctype in the app is this."""
		row = {"submit": 1, "cancel": 1, "amend": 1, "write": 1}
		self.assertEqual(patch.rights_to_clear(row), [])

	def test_submit_without_write_is_cleared(self):
		"""kaitet.local's Accounts Manager row, and its General Manager one."""
		self.assertEqual(patch.rights_to_clear({"submit": 1, "write": 0}), ["submit"])

	def test_every_offending_right_is_named_not_just_the_first(self):
		row = {"submit": 1, "cancel": 1, "amend": 1, "write": 0}
		self.assertEqual(patch.rights_to_clear(row), ["submit", "cancel", "amend"])

	def test_a_row_with_none_of_the_three_is_left_alone(self):
		self.assertEqual(patch.rights_to_clear({"read": 1, "write": 0}), [])

	def test_a_missing_write_key_counts_as_no_write(self):
		"""The shipped JSON omits a right rather than setting it to 0."""
		self.assertEqual(patch.rights_to_clear({"submit": 1}), ["submit"])

	def test_the_order_is_stable(self):
		"""So a second run's log reads the same as the first."""
		self.assertEqual(
			patch.rights_to_clear({"amend": 1, "submit": 1, "cancel": 1}),
			patch.rights_to_clear({"cancel": 1, "amend": 1, "submit": 1}),
		)


class TestTheRepairStaysInsideThisApp(unittest.TestCase):
	"""The rule that keeps a migrate of this app out of other apps' permissions."""

	OURS = {"Work Management Planner", "Work Management Actuals"}

	def test_a_doctype_this_app_ships_is_repaired(self):
		self.assertTrue(patch.is_ours("Work Management Planner", self.OURS))

	def test_another_apps_doctype_is_not_touched(self):
		"""All eighteen of kaitet.local's other invalid rows are these."""
		for outside in ("Pick List", "Stock Entry", "BOM", "Purchase Invoice",
				"Tractor Daily Task", "Leave Application", "Asset"):
			with self.subTest(doctype=outside):
				self.assertFalse(patch.is_ours(outside, self.OURS))

	def test_the_bound_is_the_apps_own_shipped_list(self):
		"""Not a literal list here -- it must follow what the app actually ships,
		or a doctype added later would fall outside the repair unnoticed."""
		from work_management import install

		source = open(patch.__file__).read()
		self.assertIn("install.shipped_doctypes()", source)
		self.assertIn("Work Management Planner", set(install.shipped_doctypes()))


if __name__ == "__main__":
	unittest.main()
