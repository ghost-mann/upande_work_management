"""The audit that has to run before farm scoping is enforced.

Enforcing a permission the app has ignored since it was written changes what 96
people see. The rollout's first step measures who that would affect and who is
already in breach, so the decision is made on evidence rather than discovered
after a deploy.

These cover the two rules with judgement in them. The queries are not mocked --
they are one GROUP BY each and their shape is checked by running the audit on a
real site, which the deployment notes record.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_farm_permission_audit -v
"""

import unittest

from work_management import farm_permission_audit as audit


class TestWorkingOutsideAPermission(unittest.TestCase):
	def test_a_farm_worked_and_not_permitted_is_reported(self):
		self.assertEqual(
			audit.worked_outside({"Saboti"}, {"Saboti": 10, "Vale": 3}),
			[("Vale", 3)])

	def test_nothing_outside_is_empty(self):
		self.assertEqual(audit.worked_outside({"Saboti", "Vale"},
			{"Saboti": 10, "Vale": 3}), [])

	def test_worst_first(self):
		"""The person who did 40 requests on a farm they may not touch is a more
		urgent question than the one who did 1."""
		self.assertEqual(
			audit.worked_outside({"Saboti"},
				{"Vale": 3, "Endebess": 40, "Lokitela": 12}),
			[("Endebess", 40), ("Lokitela", 12), ("Vale", 3)])

	def test_ties_break_by_name_so_the_report_is_stable(self):
		self.assertEqual(
			audit.worked_outside({"Saboti"}, {"Vale": 5, "Endebess": 5}),
			[("Endebess", 5), ("Vale", 5)])

	def test_an_unrestricted_person_is_never_in_breach(self):
		"""None means no restriction. Reporting everything they touched as
		"outside" would put 362 of 458 users in a breach list and bury the 96
		rows that matter."""
		self.assertEqual(audit.worked_outside(None, {"Vale": 3, "Saboti": 9}), [])

	def test_touching_nothing_is_not_a_breach(self):
		self.assertEqual(audit.worked_outside({"Saboti"}, {}), [])
		self.assertEqual(audit.worked_outside({"Saboti"}, None), [])


class TestPermissionNobodyIsUsing(unittest.TestCase):
	def test_a_permitted_farm_never_touched_is_listed(self):
		self.assertEqual(
			audit.unused_permission({"Saboti", "Vale"}, {"Saboti": 4}),
			["Vale"])

	def test_all_used_is_empty(self):
		self.assertEqual(
			audit.unused_permission({"Saboti"}, {"Saboti": 4}), [])

	def test_an_unrestricted_person_has_no_unused_permission(self):
		self.assertEqual(audit.unused_permission(None, {"Saboti": 4}), [])

	def test_sorted_so_the_report_is_stable(self):
		self.assertEqual(
			audit.unused_permission({"Vale", "Endebess", "Saboti"}, {}),
			["Endebess", "Saboti", "Vale"])


class TestTheReportReadsAsADecision(unittest.TestCase):
	RESULT = {
		"days": 90,
		"carriers": [("Work Management Planner", "requested_by")],
		"restricted_users": 2,
		"in_breach": 1,
		"rows": [
			{"user": "breach@example.com", "permitted": ["Lokitela"],
			 "touched": ["Vale", "Lokitela"],
			 "touch_counts": {"Vale": 7, "Lokitela": 2},
			 "outside": [("Vale", 7)], "unused": []},
			{"user": "clean@example.com", "permitted": ["Saboti"],
			 "touched": ["Saboti"], "touch_counts": {"Saboti": 5},
			 "outside": [], "unused": []},
			{"user": "free@example.com", "permitted": None,
			 "touched": ["Endebess"], "touch_counts": {"Endebess": 1},
			 "outside": [], "unused": []},
		],
	}

	def setUp(self):
		self.text = audit.format_report(self.RESULT)

	def test_the_person_in_breach_is_named_with_the_farm_and_the_count(self):
		self.assertIn("breach@example.com", self.text)
		self.assertIn("Vale x7", self.text)

	def test_it_says_what_the_breach_means(self):
		"""The report must not read as an accusation. Either the permission is
		wrong or the work was, and the audit cannot tell which."""
		self.assertIn("is the permission wrong, or was the work?", self.text)

	def test_the_unaffected_are_shown_too(self):
		"""The reassuring half: enforcement changes nothing for these."""
		self.assertIn("clean@example.com", self.text)
		self.assertIn("unaffected by enforcement", self.text)

	def test_unrestricted_users_are_not_in_the_breach_section(self):
		breach_section = self.text.split("RESTRICTED AND WITHIN")[0]
		self.assertNotIn("free@example.com", breach_section)

	def test_it_names_where_the_evidence_came_from(self):
		self.assertIn("Work Management Planner", self.text)

	def test_it_states_the_window(self):
		self.assertIn("last 90 days", self.text)


class TestNothingHereWrites(unittest.TestCase):
	def test_the_module_has_no_write_calls(self):
		"""This runs against production data to inform a decision. It reads."""
		import inspect
		source = inspect.getsource(audit)
		for forbidden in ("frappe.db.set_value", "frappe.db.delete", ".save(",
				".insert(", ".submit(", "frappe.db.commit", "db_insert",
				"frappe.delete_doc", "UPDATE ", "DELETE ", "INSERT "):
			self.assertNotIn(forbidden, source,
				"the audit must not %s" % forbidden)


if __name__ == "__main__":
	unittest.main()
