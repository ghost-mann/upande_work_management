"""Who may read the Worker Task Day report, decided by this site's own chain.

The client asked for the general manager to be able to read it. The obvious
implementation -- adding "General Manager" to the report's `roles` in its JSON --
is the exact thing `test_no_shipped_roles` exists to prevent: that name is one of
the five Kaitet job titles removed from this app precisely so installing it
creates nobody's hierarchy but your own. A Report's `roles` rows are Links to
Role, so a name the site has not got breaks the import rather than degrading, and
a company that calls the job "Operations Director" gets nothing from it anyway.

So it is read from configuration. Every role the chain names for an APPROVAL step
is granted the report -- those are the people who sign this pipeline's work off,
whoever they are here -- and the submit steps are deliberately not swept in,
because raising work is not overseeing it.

Measured on kentrout.local: a plain `bench migrate` printed

    Work Management: Accounts Manager, Farm Manager, General Manager, HOD HR,
    System Manager may now read 'Worker Task Day'

which is exactly this site's configured approval roles, General Manager among
them, without the app naming any of them.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_report_access_follows_the_chain -v
"""

import json
import os
import unittest

from work_management import approvals, report_access

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT_JSON = os.path.join(HERE, "work_management", "report", "worker_task_day",
	"worker_task_day.json")


def read(path):
	with open(path) as handle:
		return handle.read()


class Row(dict):
	def __getattr__(self, name):
		return self.get(name)


class Settings(dict):
	def __init__(self, rows):
		super().__init__(approval_stages=rows)

	def get(self, key, default=None):
		return dict.get(self, key, default)


def chain_of(*specs):
	"""Settings rows for a made-up chain: (key, kind, role, enabled)."""
	rows = []
	for i, (key, kind, role, enabled) in enumerate(specs, start=1):
		rows.append(Row({
			"stage": key, "stage_label": key, "idx": i,
			"document_type": "Work Management Planner", "kind": kind,
			"state": "Pending " + key, "action": "Approve",
			"role": role, "enabled": enabled,
		}))
	return Settings(rows)


class TestWhichRolesCount(unittest.TestCase):
	def test_approval_steps_are_swept_in(self):
		settings = chain_of(("a", "Approval", "Philip Role", 1))
		self.assertEqual(report_access.oversight_roles(settings), ["Philip Role"])

	def test_submit_steps_are_not(self):
		"""Raising work is not overseeing it."""
		settings = chain_of(("s", "Submit", "Daniel Role", 1),
			("a", "Approval", "Philip Role", 1))
		self.assertEqual(report_access.oversight_roles(settings), ["Philip Role"])

	def test_a_switched_off_step_still_counts(self):
		"""A step off today may be on next month, and losing report access when
		somebody toggles a setting is the kind of surprise blamed on the report."""
		settings = chain_of(("a", "Approval", "Philip Role", 0))
		self.assertEqual(report_access.oversight_roles(settings), ["Philip Role"])

	def test_a_step_with_no_role_contributes_nothing(self):
		settings = chain_of(("a", "Approval", None, 1))
		self.assertEqual(report_access.oversight_roles(settings), [])

	def test_duplicates_collapse(self):
		settings = chain_of(("a", "Approval", "Philip Role", 1),
			("b", "Approval", "Philip Role", 1))
		self.assertEqual(report_access.oversight_roles(settings), ["Philip Role"])

	def test_the_result_is_sorted(self):
		settings = chain_of(("a", "Approval", "Zed", 1), ("b", "Approval", "Alice", 1))
		self.assertEqual(report_access.oversight_roles(settings), ["Alice", "Zed"])

	def test_it_reads_the_site_by_default(self):
		"""effective_chain() distinguishes "you did not say" from "there is no
		configuration": passing settings=None resolves against the SHIPPED
		catalogue and never reads Settings. Getting that backwards made this
		grant System Manager on every site and nothing else, silently."""
		self.assertIsNot(report_access._SITE, None)
		src = read(os.path.join(HERE, "report_access.py"))
		self.assertIn("approvals.effective_chain() if settings is _SITE", src)

	def test_the_shipped_chain_gives_system_manager(self):
		"""Which is what a fresh install should get: the app names nobody."""
		self.assertEqual(report_access.oversight_roles(None), ["System Manager"])


class TestTheAppStillNamesNobody(unittest.TestCase):
	KAITET = {"Farm Manager", "General Manager", "HOD HR", "HR Clerk",
		"Production Section Head"}

	def test_the_report_json_names_no_invented_job_title(self):
		roles = {r["role"] for r in json.loads(read(REPORT_JSON))["roles"]}
		self.assertEqual(roles & self.KAITET, set())

	def test_the_granting_code_names_none_either(self):
		src = read(os.path.join(HERE, "report_access.py"))
		for role in self.KAITET:
			with self.subTest(role=role):
				# the docstring may explain WHY the name is avoided; the code
				# must not contain it as a value
				code = "\n".join(line for line in src.splitlines()
					if not line.strip().startswith("#"))
				code = code.split('"""')[0] + '"""'.join(code.split('"""')[2:])
				self.assertNotIn('"%s"' % role, code)

	def test_the_shipped_roles_are_ones_frappe_or_hr_provides(self):
		roles = {r["role"] for r in json.loads(read(REPORT_JSON))["roles"]}
		self.assertEqual(roles, {"HR User", "HR Manager", "System Manager"})


class TestTheGrantIsSafe(unittest.TestCase):
	def setUp(self):
		self.src = read(os.path.join(HERE, "report_access.py"))

	def test_it_never_removes_anything(self):
		"""The three shipped roles keep the report whatever the chain says."""
		self.assertNotIn("frappe.db.delete", self.src)
		self.assertNotIn('set("roles"', self.src)

	def test_it_skips_a_role_the_site_has_not_got(self):
		self.assertIn('if not frappe.db.exists("Role", role):', self.src)

	def test_it_is_idempotent(self):
		self.assertIn("if role in already:", self.src)

	def test_it_writes_the_rows_directly(self):
		"""Saving a standard Report with developer_mode on re-exports its JSON
		into the app -- rewriting `creation`, adding whatever fields the running
		Frappe version has, and committing one site's grants into everybody's
		copy. This is a permission grant, not an edit to the definition."""
		self.assertIn('frappe.new_doc("Has Role")', self.src)
		# the docstring explains why doc.save() is avoided, so look at code only
		code = self.src.split('"""')
		code = "".join(code[i] for i in range(0, len(code), 2))
		self.assertNotIn("doc.save(", code)
		self.assertNotIn(".save(ignore_permissions", code)

	def test_it_runs_on_every_migrate(self):
		hooks = read(os.path.join(HERE, "hooks.py"))
		self.assertIn("work_management.report_access.after_migrate", hooks)

	def test_it_runs_after_the_chain_is_settled(self):
		"""approvals.after_migrate is what seeds and saves the chain this reads."""
		hooks = read(os.path.join(HERE, "hooks.py"))
		self.assertLess(hooks.index("work_management.approvals.after_migrate"),
			hooks.index("work_management.report_access.after_migrate"))

	def test_a_missing_report_is_not_an_error(self):
		self.assertIn('if not frappe.db.exists("Report", report):', self.src)


class TestTheRunbookWasRewritten(unittest.TestCase):
	"""The 2026-09-08 draft described a different chain. Leaving it in place
	would have somebody configure Altura from it."""

	def setUp(self):
		self.doc = read(os.path.join(os.path.dirname(HERE), "docs",
			"ALTURA_APPROVAL_CHAINS.md"))

	def test_it_says_it_supersedes_the_draft(self):
		self.assertIn("supersedes", self.doc)

	def test_the_four_people_are_named(self):
		for who in ("Olger", "Daniel", "Philip", "Yvonne"):
			with self.subTest(who=who):
				self.assertIn(who, self.doc)

	def test_the_emails_are_placeholders_rather_than_guesses(self):
		"""The draft carried an unconfirmed personal gmail for Olger. It is named
		once, in the warning about what the draft got wrong -- never in the table
		somebody configures from."""
		self.assertIn("to confirm on Altura", self.doc)
		# the table rows themselves, not the warning note under them
		rows = [l for l in self.doc.splitlines()
			if l.startswith("| **") and "confirm" in l]
		self.assertEqual(len(rows), 4)
		for line in rows:
			with self.subTest(row=line[:28]):
				self.assertNotIn("@", line)
		self.assertEqual(self.doc.count("nyabisi20@gmail.com"), 1)
		at = self.doc.index("nyabisi20@gmail.com")
		self.assertIn("never confirmed", self.doc[at:at + 200])

	def test_each_chain_names_its_steps_and_switches(self):
		for key in ("planner_farm_approval", "planner_hr_approval",
				"assigner_farm_manager", "assigner_hr_head", "assigner_gm",
				"actuals_farm_manager", "actuals_hr_head", "actuals_gm"):
			with self.subTest(key=key):
				self.assertIn(key, self.doc)

	def test_the_queue_drain_warning_survives(self):
		self.assertIn("cannot be switched off while", self.doc)

	def test_the_label_renames_are_listed(self):
		self.assertIn("stage_label", self.doc)

	def test_the_master_plan_assumption_is_withdrawn_not_carried(self):
		self.assertIn("assumption is withdrawn", self.doc)
		self.assertIn("Ask before applying", self.doc)

	def test_payment_covers_both_modes(self):
		self.assertIn("Payroll feed mode", self.doc)
		self.assertIn("Accounts release mode", self.doc)

	def test_nothing_was_executed(self):
		self.assertIn("No part of this has been executed on any site", self.doc)


if __name__ == "__main__":
	unittest.main()
