"""Installing this app must not create another organisation's job titles.

It shipped five Roles as fixtures -- Farm Manager, General Manager, HOD HR, HR
Clerk, Production Section Head -- so installing at any company created Kaitet's
hierarchy on their site. Not sloppiness: the fifteen shipped steps defaulted to
those names, and a Workflow Transition's role is a Link, so the role had to exist
for the generated workflow to save.

The fix is at the other end. A shipped step defaults to a role Frappe guarantees,
so the app creates nothing and a new company maps the steps onto its own roles.
The cost is deliberate: a fresh install has every approval sitting with System
Manager until somebody configures it, which is visible and safe -- unlike
arriving pre-configured for a company you have never heard of.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_no_shipped_roles -v
"""

import json
import os
import unittest

from work_management import approvals

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KAITET_ROLES = {"Farm Manager", "General Manager", "HOD HR", "HR Clerk",
                "Production Section Head"}


class TestTheAppCreatesNoRoles(unittest.TestCase):
	def test_there_is_no_role_fixture(self):
		self.assertFalse(
			os.path.exists(os.path.join(HERE, "fixtures", "role.json")),
			"installing the app would create these roles on any site",
		)

	def test_hooks_does_not_ship_roles(self):
		from work_management import hooks

		for entry in getattr(hooks, "fixtures", None) or []:
			self.assertNotEqual(entry.get("dt"), "Role", entry)

	def test_no_shipped_step_defaults_to_a_job_title_the_app_invented(self):
		"""A default naming a role nothing creates would break the workflow save."""
		defaults = {stage.role for stage in approvals.CATALOGUE if stage.role}
		self.assertEqual(defaults & KAITET_ROLES, set())

	def test_every_shipped_step_defaults_to_a_role_frappe_guarantees(self):
		"""The role has to exist: Workflow Transition.allowed is a Link to Role."""
		for stage in approvals.CATALOGUE:
			self.assertEqual(stage.role, "System Manager", stage.key)

	def test_an_existing_site_keeps_the_role_it_configured(self):
		"""seed_stages() must not overwrite a chosen role with the new default,
		or every deployment's approvals would move to System Manager on migrate."""
		source = open(os.path.join(HERE, "approvals.py")).read()
		block = source[source.index("def seed_stages"):]
		block = block[:block.index("\ndef ")]
		self.assertIn("previous.role if previous and previous.role else stage.role", block)
