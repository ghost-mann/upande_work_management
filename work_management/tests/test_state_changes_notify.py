"""Every workflow transition the screens make sends its Notification, once.

Live Altura has thirteen Notifications on these four doctypes, all "Value
Change" on `workflow_state`. Frappe only evaluates those during an ordinary
save, never on insert, and the screens move documents with
`frappe.db.set_value` -- so an assignment created Assigned, a plan approved or
rejected, and every actuals and master plan step sent nothing. The one that did
fire was a plan going Draft -> Pending Approval, because that is a save.

work_management/notify.py fills the gap for the column writes and stays out of
the way of the save, so each transition sends exactly one email per matching
Notification -- never none, never two.

    bench --site kentrout.local run-tests --app work_management \\
        --module work_management.tests.test_state_changes_notify
"""

import os
import re
import unittest

import frappe

from work_management.tests import pipeline
from work_management.tests.pipeline import call

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MP = "Work Management Master Plan"
PL = "Work Management Planner"
ASG = "Work Management Assigner"
ACT = "Work Management Actuals"

#: what live has: doctype -> (author field, the states it announces)
LIVE = {
	PL: ("requested_by", ("Pending Approval", "Approved", "Rejected")),
	ASG: ("assigned_by", ("Pending Manager", "Assigned", "Rejected")),
	MP: ("raised_by", ("Pending Manager", "Approved", "Rejected")),
	ACT: ("entered_by", ("Pending Approval", "Pending Manager", "CONFIRMED", "Rejected")),
}


def read(*parts):
	with open(os.path.join(APP, *parts)) as handle:
		return handle.read()


class TestEveryColumnWriteIsAnnounced(unittest.TestCase):
	"""A static guard, so the next direct write cannot quietly skip it."""

	MODULES = ("planner.py", "assigner.py", "actuals.py", "masterplan.py")
	DOCTYPES = (MP, PL, ASG, ACT, "ASG_DT", "ACT_DT")

	def writes(self, src):
		"""Line numbers of every set_value that writes workflow_state on one of
		the four doctypes (single-line, two-line and dict forms)."""
		lines = src.split("\n")
		found = []
		for i, line in enumerate(lines):
			if "frappe.db.set_value(" not in line:
				continue
			window = " ".join(lines[i:i + 3])
			if '"workflow_state"' not in window:
				continue
			if not any(('"%s"' % d if " " in d else d) in line for d in self.DOCTYPES):
				continue
			found.append(i)
		return lines, found

	def test_each_write_is_followed_by_a_notification(self):
		for module in self.MODULES:
			lines, found = self.writes(read("api", module))
			self.assertTrue(found, module)
			for k, i in enumerate(found):
				with self.subTest(module=module, line=i + 1):
					# Before the next state write, and within the branch: some writes
					# are followed by the approval stamps and a comment first. Bounded
					# by the next write so one call cannot be counted for two.
					end = min(found[k + 1] if k + 1 < len(found) else len(lines), i + 45)
					self.assertIn("notify.notify_state_change(", "\n".join(lines[i:end]))

	def test_the_planner_submit_is_a_save_and_is_not_announced_twice(self):
		src = read("api", "planner.py")
		at = src.index('d.workflow_state = STAGE_NEXT["planner_submit"]; d.save(ignore_permissions=True)')
		self.assertNotIn("notify.notify_state_change", src[at:at + 400])

	def test_the_rescue_patch_announces_nothing(self):
		"""A rename of states is not news to anybody."""
		src = read("patches", "v1_0", "rescue_documents_in_renamed_states.py")
		self.assertNotIn("notify", src)

	def test_no_shipped_template_calls_utils_get_fullname(self):
		"""frappe.utils.get_fullname is not in Jinja's safe utils; a template that
		calls it raises "'NoneType' object is not callable". None ship today --
		this keeps it that way."""
		for root, _dirs, files in os.walk(APP):
			for name in files:
				if name.endswith((".json", ".html", ".md")):
					with self.subTest(file=name):
						with open(os.path.join(root, name), errors="ignore") as handle:
							self.assertNotIn("frappe.utils.get_fullname(", handle.read())


class TestOneEmailPerTransition(pipeline.SiteTestCase, unittest.TestCase):
	"""The live Notifications, recreated for the test, and every transition
	driven through the endpoints the screens call."""

	def setUp(self):
		super().setUp()
		self.settings(att_block_absent=0, att_block_leave=0, att_block_noscan_actuals=0,
			att_block_off=0, block_self_approval=0)
		frappe.db.delete("Email Queue")
		# Without a default outgoing account Frappe will not queue mail at all
		# (OutgoingEmailError); live has one, kentrout.local does not.
		if not frappe.db.exists("Email Account", {"enable_outgoing": 1, "default_outgoing": 1}):
			frappe.get_doc({
				"doctype": "Email Account",
				"email_account_name": "WM test outgoing",
				"email_id": "wm-outgoing@example.com",
				"enable_outgoing": 1,
				"default_outgoing": 1,
				"smtp_server": "localhost",
				"smtp_port": 25,
				"no_smtp_authentication": 1,
			}).insert(ignore_permissions=True)
			frappe.local.outgoing_email_account = {}
		for doctype, (field, states) in LIVE.items():
			for state in states:
				frappe.get_doc({
					"doctype": "Notification",
					"name": "WM test " + doctype[16:] + " " + state,
					"subject": "{{ doc.name }} is now " + state,
					"document_type": doctype,
					"event": "Value Change",
					"value_changed": "workflow_state",
					"channel": "Email",
					"condition_type": "Python",
					"condition": 'doc.workflow_state == "%s"' % state,
					# the template the live fix settled on: frappe.get_fullname is safe
					"message": "{{ frappe.get_fullname(doc.owner) }}: {{ doc.name }} is " + state,
					"recipients": [{"receiver_by_document_field": field}],
					"enabled": 1,
				}).insert(ignore_permissions=True)
		frappe.client_cache.delete_value(["notifications::" + d for d in LIVE])
		# Recipients come from the author fields, and Frappe drops any that is not
		# an email address -- "Administrator" included. So the work is done by a
		# user who has one, as it is on a live site.
		user = frappe.get_doc({"doctype": "User", "email": self.USER, "first_name": "Notify",
			"send_welcome_email": 0, "user_type": "System User"}).insert(ignore_permissions=True)
		user.add_roles("System Manager", "Production Manager", "Production Section Head", "HR Officer")
		self.p = pipeline.Pipeline(user=self.USER)

	USER = "wm-notify-test@example.com"

	def sent(self, doctype, name):
		return frappe.db.count("Email Queue", {"reference_doctype": doctype, "reference_name": name})

	def step(self, doctype, get_name, fn, expect_state):
		"""Run one transition and assert it sent exactly one email."""
		before = self.sent(doctype, get_name()) if get_name() else 0
		fn()
		name = get_name()
		self.assertEqual(self.p.state(doctype, name), expect_state)
		self.assertEqual(self.sent(doctype, name) - before, 1,
			"%s %s -> %s sent %d" % (doctype, name, expect_state, self.sent(doctype, name) - before))

	def test_master_plan(self):
		p = self.p
		p.master_plan(submit=False)
		self.assertEqual(self.sent(MP, p.mp), 0)  # a draft announces nothing
		self.step(MP, lambda: p.mp, lambda: call(p.ep.mp, self.USER, action="submit_for_review", name=p.mp), "Pending Manager")
		self.step(MP, lambda: p.mp, lambda: call(p.ep.mp, self.USER, action="reject", name=p.mp), "Rejected")
		self.step(MP, lambda: p.mp, lambda: call(p.ep.mp, self.USER, action="submit_for_review", name=p.mp), "Pending Manager")
		self.step(MP, lambda: p.mp, lambda: call(p.ep.mp, self.USER, action="gm_approve", name=p.mp), "Approved")

	def test_planner(self):
		p = self.p
		p.master_plan()
		# Draft -> Pending Approval is a save: it fires natively, and only natively
		self.step(PL, lambda: getattr(p, "pl", None), lambda: p.plan(approve=False), "Pending Approval")
		self.step(PL, lambda: p.pl, lambda: call(p.ep.pl, self.USER, action="reject", name=p.pl), "Rejected")
		self.step(PL, lambda: p.pl, lambda: call(p.ep.pl, self.USER, action="submit", plan=p.pl, farm=p.farm,
			blocks=p.block, task=p.task, quantity=12, from_date=p.from_date, to_date=p.to_date,
			master_plan=p.mp, submit_now=1), "Pending Approval")
		self.step(PL, lambda: p.pl, p.approve_plan, "Approved")

	def test_assigner(self):
		p = self.p
		p.master_plan()
		p.plan()
		self.step(ASG, lambda: getattr(p, "asg", None), lambda: p.assignment(approve=False), "Pending Manager")
		self.step(ASG, lambda: p.asg, lambda: call(p.ep.asg, self.USER, action="a_reject", name=p.asg), "Rejected")
		self.step(ASG, lambda: p.asg, lambda: call(p.ep.asg, self.USER, action="a_submit", assignment=p.asg,
			planner=p.pl, employees=",".join(p.workers), submit_now=1, att_override=1), "Pending Manager")
		self.step(ASG, lambda: p.asg, lambda: call(p.ep.asg, self.USER, action="a_approve", name=p.asg,
			stage="assigner_farm_manager"), "Assigned")

	def test_assigner_created_assigned(self):
		"""With the manager step off, an assignment is inserted and written straight
		to Assigned -- the live WMA-01295 case, which never fired."""
		p = self.p
		p.master_plan()
		p.plan()
		rows = frappe.get_all("Work Management Approval Stage",
			filters={"parent": "Work Management Settings", "stage": "assigner_farm_manager"}, pluck="name")
		for row in rows:
			frappe.db.set_value("Work Management Approval Stage", row, "enabled", 0)
		frappe.clear_cache(doctype="Work Management Settings")
		self.step(ASG, lambda: getattr(p, "asg", None), lambda: p.assignment(approve=False), "Assigned")

	def test_actuals(self):
		p = self.p
		p.master_plan()
		p.plan()
		p.assignment()
		self.step(ACT, lambda: getattr(p, "act", None), lambda: p.actuals(submit=True), "Pending Approval")
		self.step(ACT, lambda: p.act, lambda: call(p.ep.act, self.USER, action="act_reject", name=p.act, reason="x"), "Rejected")
		self.step(ACT, lambda: p.act, lambda: p.actuals(submit=True), "Pending Approval")
		self.step(ACT, lambda: p.act, lambda: call(p.ep.act, self.USER, action="act_approve", name=p.act,
			stage="actuals_farm_manager"), "Pending Manager")
		self.step(ACT, lambda: p.act, lambda: call(p.ep.act, self.USER, action="act_approve", name=p.act,
			stage="actuals_hr_head"), "CONFIRMED")

	def test_a_notification_that_fails_does_not_undo_the_approval(self):
		p = self.p
		p.master_plan()
		p.plan(approve=False)
		frappe.db.set_value("Notification", "WM test Planner Approved", "message",
			"{{ frappe.utils.get_fullname(doc.owner) }}")
		out = p.approve_plan()
		self.assertFalse(out.get("error"), out)
		self.assertEqual(self.p.state(PL, p.pl), "Approved")
		self.assertEqual(self.sent(PL, p.pl), 1)  # only the Pending Approval one

	def test_without_a_matching_notification_nothing_is_sent(self):
		frappe.db.set_value("Notification", {"document_type": MP}, "enabled", 0)
		self.p.master_plan()
		self.assertEqual(self.sent(MP, self.p.mp), 0)
