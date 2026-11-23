# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""The app never overwrites a Workflow edited in the desk.

Workflows on live are maintained by hand and change often. Before this,
`build_workflows()` ran on every migrate and every Settings save and rewrote
any workflow that differed from what Settings generates -- which is to say,
every edit anybody made in the desk.

    fixtures      no Workflow, Workflow Transition, Workflow State or Workflow
                  Action Master; the names are created insert-only in code
    migrate       creates a missing workflow; an existing one is not cleared,
                  rewritten or re-saved, and `modified` does not move
    Settings save the same, plus a message when the save would change a workflow
    rebuild       only rebuild_workflows_from_settings(), System Manager only

    bench --site kentrout.local run-tests --app work_management \\
        --module work_management.tests.test_workflows_belong_to_the_site
"""

import glob
import json
import os
import unittest

import frappe

from work_management import approvals, hooks
from work_management.tests import pipeline

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW_DOCTYPES = {"Workflow", "Workflow Transition", "Workflow State",
	"Workflow Action Master", "Workflow Document State"}


def fixture_doctypes(fixtures):
	return {(f if isinstance(f, str) else f.get("dt") or f.get("doctype")) for f in fixtures}


class TestNoWorkflowFixtures(unittest.TestCase):
	"""No site needed."""

	def test_hooks_ship_no_workflow_fixture(self):
		self.assertEqual(fixture_doctypes(hooks.fixtures) & WORKFLOW_DOCTYPES, set())

	def test_no_fixture_file_carries_a_workflow(self):
		for path in glob.glob(os.path.join(APP, "fixtures", "*.json")):
			with open(path) as f:
				docs = json.load(f)
			found = {d.get("doctype") for d in docs} & WORKFLOW_DOCTYPES
			self.assertEqual(found, set(), path)

	def test_the_check_would_catch_one(self):
		"""The guard above is not vacuous: a Workflow fixture, in either spelling,
		is seen."""
		self.assertIn("Workflow", fixture_doctypes([{"dt": "Workflow"}]) & WORKFLOW_DOCTYPES)
		self.assertIn("Workflow", fixture_doctypes(["Workflow"]) & WORKFLOW_DOCTYPES)
		self.assertIn("Workflow State", fixture_doctypes(
			[{"dt": "Workflow State", "filters": []}]) & WORKFLOW_DOCTYPES)

	def test_the_names_are_still_created_somewhere(self):
		for name in ("CONFIRMED", "Pending Manager", "Rejected", "Paid"):
			self.assertIn(name, approvals.WORKFLOW_STATES)
		for name in ("Approve", "Reject", "Re-submit", "Manager Approve"):
			self.assertIn(name, approvals.WORKFLOW_ACTIONS)


class SiteCase(pipeline.SiteTestCase, unittest.TestCase):
	WF = approvals.CHAIN_ENDS["Work Management Actuals"]["workflow"]

	def hand_edit(self):
		"""What a System Manager does in the desk: add a transition, change a role."""
		wf = frappe.get_doc("Workflow", self.WF)
		wf.transitions[0].allowed = "HR User"
		wf.append("transitions", {"state": wf.transitions[0].state, "action": "Reject",
			"next_state": "Rejected", "allowed": "HR Manager", "allow_self_approval": 1})
		wf.save(ignore_permissions=True)
		frappe.db.sql("UPDATE `tabWorkflow` SET modified = '2026-01-02 03:04:05' WHERE name = %s",
			self.WF)
		return frappe.get_doc("Workflow", self.WF)

	def shape(self, wf):
		return [(t.state, t.action, t.next_state, t.allowed) for t in wf.transitions]


class TestMigrateLeavesTheEdit(SiteCase):
	def test_two_migrates_keep_the_edit_and_modified(self):
		before = self.hand_edit()
		approvals.after_migrate()
		approvals.after_migrate()
		after = frappe.get_doc("Workflow", self.WF)
		self.assertEqual(self.shape(after), self.shape(before))
		self.assertEqual(str(after.modified), "2026-01-02 03:04:05")
		self.assertIn(("HR User",), [(t.allowed,) for t in after.transitions])

	def test_a_missing_workflow_is_created(self):
		frappe.db.sql("DELETE FROM `tabWorkflow Transition` WHERE parent = %s", self.WF)
		frappe.db.sql("DELETE FROM `tabWorkflow Document State` WHERE parent = %s", self.WF)
		frappe.db.sql("DELETE FROM `tabWorkflow` WHERE name = %s", self.WF)
		approvals.after_migrate()
		self.assertTrue(frappe.db.exists("Workflow", self.WF))
		self.assertTrue(frappe.get_doc("Workflow", self.WF).transitions)

	def test_a_missing_name_master_is_created_and_an_existing_style_kept(self):
		frappe.db.set_value("Workflow State", "CONFIRMED", "style", "Primary", update_modified=False)
		frappe.db.sql("DELETE FROM `tabWorkflow Action Master` WHERE name = 'Mark Paid'")
		approvals.after_migrate()
		self.assertEqual(frappe.db.get_value("Workflow State", "CONFIRMED", "style"), "Primary")
		self.assertTrue(frappe.db.exists("Workflow Action Master", "Mark Paid"))


class TestSettingsSaveLeavesTheEdit(SiteCase):
	def test_a_save_does_not_touch_the_workflow(self):
		before = self.hand_edit()
		settings = frappe.get_doc("Work Management Settings")
		settings.save(ignore_permissions=True)
		after = frappe.get_doc("Workflow", self.WF)
		self.assertEqual(self.shape(after), self.shape(before))
		self.assertEqual(str(after.modified), "2026-01-02 03:04:05")

	def test_a_save_that_would_change_a_workflow_says_so_and_changes_nothing(self):
		before = frappe.get_doc("Workflow", self.WF)
		settings = frappe.get_doc("Work Management Settings")
		prev = frappe.copy_doc(settings)
		rows = [r for r in settings.approval_stages if r.document_type == "Work Management Actuals"
			and r.kind == "Approval"]
		self.assertTrue(rows, "needs an actuals approval step")
		frappe.message_log = []
		rows[0].role = "HR Manager"
		changes = approvals.tell_about_unapplied_changes(settings, previous=prev)
		self.assertTrue([c for c in changes if c["workflow"] == self.WF])
		self.assertTrue(frappe.message_log)
		self.assertEqual(self.shape(frappe.get_doc("Workflow", self.WF)), self.shape(before))

	def test_an_unchanged_save_is_quiet(self):
		self.hand_edit()
		settings = frappe.get_doc("Work Management Settings")
		frappe.message_log = []
		self.assertEqual(approvals.tell_about_unapplied_changes(settings,
			previous=frappe.copy_doc(settings)), [])


class TestTheRebuildButton(SiteCase):
	def test_preview_names_the_edit(self):
		self.hand_edit()
		mine = [c for c in approvals.workflow_changes() if c["workflow"] == self.WF][0]
		self.assertTrue(any("HR User" in x or "HR Manager" in x for x in mine["changes"]), mine)

	def test_only_a_system_manager_may_rebuild(self):
		self.hand_edit()
		user = frappe.db.get_value("User", {"name": ["not in", ["Administrator", "Guest"]],
			"enabled": 1}, "name")
		if not user or "System Manager" in frappe.get_roles(user):
			user = None
		if user is None:
			user = "wm-day-guard-nobody@example.com"
			if not frappe.db.exists("User", user):
				frappe.get_doc({"doctype": "User", "email": user, "first_name": "Nobody",
					"send_welcome_email": 0}).insert(ignore_permissions=True)
		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				approvals.rebuild_workflows_from_settings()
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(str(frappe.db.get_value("Workflow", self.WF, "modified")),
			"2026-01-02 03:04:05")

	def test_a_confirmed_rebuild_overwrites(self):
		self.hand_edit()
		out = approvals.rebuild_workflows_from_settings()
		self.assertIn(self.WF, out["rebuilt"])
		after = frappe.get_doc("Workflow", self.WF)
		self.assertNotIn("HR User", [t.allowed for t in after.transitions])
		self.assertEqual([c for c in approvals.workflow_changes() if c["workflow"] == self.WF], [])


class TestNothingElseRebuilds(unittest.TestCase):
	"""Source checks: every automatic caller is create-only."""

	def read(self, *parts):
		with open(os.path.join(APP, *parts)) as f:
			return f.read()

	def test_only_the_button_passes_overwrite(self):
		hits = []
		for path in glob.glob(os.path.join(APP, "**", "*.py"), recursive=True):
			if os.sep + "tests" + os.sep in path:
				continue
			with open(path) as f:
				if "overwrite=True" in f.read():
					hits.append(os.path.relpath(path, APP))
		self.assertEqual(hits, ["approvals.py"])
		src = self.read("approvals.py")
		at = src.index("def rebuild_workflows_from_settings(")
		self.assertIn("frappe.only_for(\"System Manager\")", src[at:at + 600])
		self.assertEqual(src.count("build_workflows(overwrite=True)"), 1)

	def test_the_desk_button_confirms_and_warns(self):
		js = self.read("work_management", "doctype", "work_management_settings",
			"work_management_settings.js")
		self.assertIn("Rebuild workflows from Settings", js)
		self.assertIn("frappe.confirm(", js)
		self.assertIn("overwrites every edit made to these workflows in the desk UI", js)
		self.assertIn('has_role("System Manager")', js)
