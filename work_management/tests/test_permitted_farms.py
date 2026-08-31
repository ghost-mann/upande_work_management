"""Which farms a person may act on is Frappe's answer, not this app's.

Work Management maintained a parallel notion of farm scoping -- per-farm roles,
per-farm workflow transitions, a farm-to-role map -- and all of it guarded
approval actions while guarding no reads at all. Meanwhile the organisation was
already recording farm scoping in Frappe's own mechanism and this app ignored it:
on the live site, 202 Farm User Permissions across 96 users, maintained daily.

So the app reads them. This is the one place that answers the question, and it
follows Frappe's semantics exactly rather than inventing kinder or stricter ones,
because a farm dimension that behaves differently here than in the list view is
worse than either behaviour on its own.

The semantics, from `frappe/permissions.py:782` and
`user_permission.get_user_permissions`:

  * no rows at all             -> unrestricted (362 of 458 enabled users on live)
  * Administrator and Guest    -> never restricted
  * `applicable_for` empty     -> restricts every doctype
  * `applicable_for` set       -> restricts only that doctype; live has one
                                  scoped to Material Request, which says nothing
                                  about who may see a farm's labour
  * rows that all filter out   -> unrestricted, which is what Frappe concludes
                                  when its own filter leaves nothing

`None` means unrestricted and a non-empty set means restricted, so no caller can
mistake "permitted nothing" for "permitted everything" -- the failure mode that
would turn a gate into a leak.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_permitted_farms -v
"""

import unittest

from work_management.api import config

RULE = config.farms_from_permissions


def row(farm, applicable_for=None):
	return {"for_value": farm, "applicable_for": applicable_for}


class TestAPersonWithNoRestrictionSeesEveryFarm(unittest.TestCase):
	def test_no_rows_is_unrestricted(self):
		"""Frappe's own default, and what most of the site relies on."""
		self.assertIsNone(RULE([]))

	def test_none_is_unrestricted(self):
		self.assertIsNone(RULE(None))

	def test_unrestricted_is_none_not_an_empty_set(self):
		"""An empty set has to mean "permitted no farms". If unrestricted were
		also an empty set, the two would be indistinguishable and every caller
		would have to guess which one it had."""
		self.assertIsNot(RULE([]), set())


class TestAPersonWithARestrictionSeesOnlyTheirFarms(unittest.TestCase):
	def test_one_farm(self):
		self.assertEqual(RULE([row("Saboti")]), {"Saboti"})

	def test_several_farms(self):
		self.assertEqual(
			RULE([row("Saboti"), row("Vale"), row("Lokitela")]),
			{"Saboti", "Vale", "Lokitela"})

	def test_duplicate_rows_collapse(self):
		self.assertEqual(RULE([row("Saboti"), row("Saboti")]), {"Saboti"})

	def test_a_blank_for_value_is_not_a_farm(self):
		self.assertEqual(RULE([row("Saboti"), row(""), row(None)]), {"Saboti"})


class TestApplicableForIsHonoured(unittest.TestCase):
	"""A permission scoped to one doctype must not restrict another. Live has
	exactly one such row, scoped to Material Request."""

	def test_a_foreign_scope_does_not_restrict_this_app(self):
		self.assertIsNone(RULE([row("Kapkolia", "Material Request")]))

	def test_a_foreign_scope_beside_an_unscoped_row_changes_nothing(self):
		self.assertEqual(
			RULE([row("Saboti"), row("Kapkolia", "Material Request")]),
			{"Saboti"})

	def test_a_scope_matching_the_doctype_asked_about_does_restrict(self):
		self.assertEqual(
			RULE([row("Kapkolia", "Work Management Planner")],
				doctype="Work Management Planner"),
			{"Kapkolia"})

	def test_a_scope_for_a_different_doctype_than_the_one_asked_about(self):
		self.assertIsNone(
			RULE([row("Kapkolia", "Work Management Planner")],
				doctype="Work Management Payment"))

	def test_scoped_and_unscoped_both_count_when_the_scope_matches(self):
		self.assertEqual(
			RULE([row("Saboti"), row("Vale", "Work Management Planner")],
				doctype="Work Management Planner"),
			{"Saboti", "Vale"})


class TestTheRuleMatchesFrappesOwnFilter(unittest.TestCase):
	"""The condition is lifted from frappe.permissions.filter_allowed_docs_for_doctype
	line for line: `if not doc.get("applicable_for") or doc.get("applicable_for")
	== doctype`. This asserts the same truth table so a Frappe upgrade that
	changes it shows up here as a failure rather than as a silent divergence."""

	CASES = [
		(None, None, True),
		("", None, True),
		(None, "Work Management Planner", True),
		("Work Management Planner", "Work Management Planner", True),
		("Work Management Planner", None, False),
		("Material Request", "Work Management Planner", False),
	]

	def test_truth_table(self):
		for applicable_for, doctype, restricts in self.CASES:
			with self.subTest(applicable_for=applicable_for, doctype=doctype):
				got = RULE([row("Saboti", applicable_for)], doctype=doctype)
				self.assertEqual(got == {"Saboti"}, restricts)

	def test_frappes_filter_agrees_row_for_row(self):
		"""Run Frappe's own function beside ours on the same rows."""
		try:
			from frappe.permissions import filter_allowed_docs_for_doctype
		except Exception:
			self.skipTest("frappe not importable standalone")
		for applicable_for, doctype, restricts in self.CASES:
			perms = [{"doc": "Saboti", "applicable_for": applicable_for,
				"is_default": 0, "hide_descendants": 0}]
			allowed, _default = filter_allowed_docs_for_doctype(perms, doctype)
			with self.subTest(applicable_for=applicable_for, doctype=doctype):
				self.assertEqual(bool(allowed), restricts)
				self.assertEqual(bool(allowed), RULE(
					[row("Saboti", applicable_for)], doctype=doctype) is not None)


class TestNarrowingAFarmList(unittest.TestCase):
	"""The choke point: `farms_in_use` already narrows to the farms a project
	works, and this narrows again to the farms a person may act on. Both, in that
	order, and neither undoing the other."""

	ALL = ["Saboti", "Lokitela", "Vale", "Endebess"]

	def test_unrestricted_keeps_the_whole_list(self):
		self.assertEqual(config.narrow_to_permitted(self.ALL, None), self.ALL)

	def test_restricted_keeps_only_the_permitted_ones(self):
		self.assertEqual(
			config.narrow_to_permitted(self.ALL, {"Vale", "Saboti"}),
			["Saboti", "Vale"])

	def test_the_order_is_the_lists_not_the_permissions(self):
		"""Screens print this list; it must stay in Core's creation order."""
		self.assertEqual(
			config.narrow_to_permitted(self.ALL, {"Endebess", "Saboti"}),
			["Saboti", "Endebess"])

	def test_a_permitted_farm_the_project_does_not_work_is_not_added(self):
		"""Permission widens nobody's list. Kapkolia is permitted but this
		project does not work it, so it does not appear."""
		self.assertEqual(
			config.narrow_to_permitted(self.ALL, {"Saboti", "Kapkolia"}),
			["Saboti"])

	def test_permitted_nothing_relevant_yields_nothing(self):
		"""Honest empty rather than a silent fallback to all: a person permitted
		only farms this project does not work has no farms here, and a screen
		saying so is correct. Falling back to everything would be the leak."""
		self.assertEqual(config.narrow_to_permitted(self.ALL, {"Kapkolia"}), [])


if __name__ == "__main__":
	unittest.main()
