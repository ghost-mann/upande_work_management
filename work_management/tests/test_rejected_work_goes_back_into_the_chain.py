"""A rejected document can be fixed, saved, and sent back -- on all four chains.

Live, resubmitting a rejected Actuals failed with

    Workflow State transition not allowed from Rejected to Draft

because saving a rejected entry wrote `Draft` and saved, and the generated
workflows have no Rejected -> Draft transition. Planner and Assigner did the
same on a draft save. The Master Plan screen never did: it keeps Rejected while
the plan is edited and moves it on at submit, which is the workflow's own
Re-submit transition. All four now work that way.

And whoever resubmits is stamped on the document, so that with "Block
self-approval" on they cannot approve the work they just sent back.

    bench --site kentrout.local run-tests --app work_management \\
        --module work_management.tests.test_rejected_work_goes_back_into_the_chain
"""

import json
import unittest

import frappe

from work_management.tests import pipeline
from work_management.tests.pipeline import call

MP = "Work Management Master Plan"
PL = "Work Management Planner"
ASG = "Work Management Assigner"
ACT = "Work Management Actuals"


class TestRejectEditSaveSubmit(pipeline.SiteTestCase, unittest.TestCase):
	"""reject -> edit -> save as draft -> submit, through each screen's endpoints."""

	def setUp(self):
		super().setUp()
		self.settings(att_block_absent=0, att_block_leave=0, att_block_noscan_actuals=0,
			att_block_off=0, block_self_approval=0)
		self.p = pipeline.Pipeline()

	def assertState(self, doctype, name, state):
		self.assertEqual(self.p.state(doctype, name), state)

	def test_master_plan(self):
		p = self.p
		p.master_plan(submit=True, approve=False)
		self.assertState(MP, p.mp, "Pending Manager")
		self.assertFalse(call(p.ep.mp, action="reject", name=p.mp).get("error"))
		self.assertState(MP, p.mp, "Rejected")
		out = call(p.ep.mp, action="save", name=p.mp, farm=p.farm, plan_name="Fixed",
			period_from=frappe.utils.add_days(p.from_date, -1), period_to=frappe.utils.add_days(p.to_date, 30),
			activities=[{"task": p.task, "work_qty": 900, "man_days": 40, "days": 30}])
		self.assertFalse(out.get("error"), out)
		self.assertState(MP, p.mp, "Rejected")
		self.assertFalse(call(p.ep.mp, action="submit_for_review", name=p.mp).get("error"))
		self.assertState(MP, p.mp, "Pending Manager")
		self.assertEqual(frappe.db.get_value(MP, p.mp, "resubmitted_by"), "Administrator")

	def test_planner(self):
		p = self.p
		p.master_plan()
		p.plan(submit=True, approve=False)
		self.assertState(PL, p.pl, "Pending Approval")
		self.assertFalse(call(p.ep.pl, action="reject", name=p.pl, reason="wrong block").get("error"))
		self.assertState(PL, p.pl, "Rejected")
		edit = dict(action="submit", plan=p.pl, farm=p.farm, blocks=p.block, task=p.task,
			quantity=14, from_date=p.from_date, to_date=p.to_date, master_plan=p.mp)
		out = call(p.ep.pl, submit_now=0, **edit)
		self.assertFalse(out.get("error"), out)
		self.assertState(PL, p.pl, "Rejected")
		self.assertEqual(frappe.db.get_value(PL, p.pl, "quantity"), 14)
		out = call(p.ep.pl, submit_now=1, **edit)
		self.assertFalse(out.get("error"), out)
		self.assertState(PL, p.pl, "Pending Approval")
		self.assertEqual(frappe.db.get_value(PL, p.pl, "resubmitted_by"), "Administrator")

	def test_assigner(self):
		p = self.p
		p.master_plan()
		p.plan()
		p.assignment(submit=True, approve=False)
		self.assertState(ASG, p.asg, "Pending Manager")
		self.assertFalse(call(p.ep.asg, action="a_reject", name=p.asg, reason="wrong crew").get("error"))
		self.assertState(ASG, p.asg, "Rejected")
		edit = dict(action="a_submit", assignment=p.asg, planner=p.pl,
			employees=p.workers[0], att_override=1)
		out = call(p.ep.asg, submit_now=0, **edit)
		self.assertFalse(out.get("error"), out)
		self.assertState(ASG, p.asg, "Rejected")
		out = call(p.ep.asg, submit_now=1, **edit)
		self.assertFalse(out.get("error"), out)
		self.assertState(ASG, p.asg, "Pending Manager")
		self.assertEqual(frappe.db.get_value(ASG, p.asg, "resubmitted_by"), "Administrator")

	def test_actuals(self):
		p = self.p
		p.master_plan()
		p.plan()
		p.assignment()
		p.actuals(submit=True)
		self.assertState(ACT, p.act, "Pending Approval")
		self.assertFalse(call(p.ep.act, action="act_reject", name=p.act, reason="wrong qty").get("error"))
		self.assertState(ACT, p.act, "Rejected")
		p.actuals(submit=False)
		self.assertState(ACT, p.act, "Rejected")
		p.actuals(submit=True)
		self.assertState(ACT, p.act, "Pending Approval")
		self.assertEqual(frappe.db.get_value(ACT, p.act, "resubmitted_by"), "Administrator")

	def test_a_first_submission_records_no_resubmitter(self):
		p = self.p
		p.master_plan()
		p.plan()
		p.assignment()
		p.actuals(submit=True)
		self.assertFalse(frappe.db.get_value(ACT, p.act, "resubmitted_by"))


class TestSelfApproval(pipeline.SiteTestCase, unittest.TestCase):
	"""With the switch on, the author and the last resubmitter are refused;
	anybody else is not. With it off, nothing changes."""

	OTHER = "wm-self-approval-test@example.com"

	def setUp(self):
		super().setUp()
		self.settings(att_block_absent=0, att_block_leave=0, att_block_noscan_actuals=0, att_block_off=0)
		user = frappe.get_doc({"doctype": "User", "email": self.OTHER, "first_name": "Other",
			"send_welcome_email": 0, "user_type": "System User"}).insert(ignore_permissions=True)
		user.add_roles("System Manager", "Production Manager", "Production Section Head", "HR Officer")
		self.p = pipeline.Pipeline()
		self.p.master_plan()
		self.p.plan()
		self.p.assignment()
		self.p.actuals(submit=True)

	def approve(self, user):
		return call(self.p.ep.act, user, action="act_approve", name=self.p.act, stage="actuals_farm_manager")

	def test_off_by_default(self):
		self.assertEqual(frappe.db.get_single_value("Work Management Settings", "block_self_approval"), 0)

	def test_off_the_author_may_approve(self):
		self.settings(block_self_approval=0)
		self.assertFalse(self.approve("Administrator").get("error"))

	def test_on_the_author_is_refused(self):
		self.settings(block_self_approval=1)
		out = self.approve("Administrator")
		self.assertIn("You raised this work record", out.get("error") or "")
		self.assertEqual(self.p.state(ACT, self.p.act), "Pending Approval")

	def test_on_somebody_else_may_approve(self):
		self.settings(block_self_approval=1)
		self.assertFalse(self.approve(self.OTHER).get("error"))
		self.assertEqual(self.p.state(ACT, self.p.act), "Pending Manager")

	def test_on_the_resubmitter_is_refused(self):
		self.settings(block_self_approval=1)
		self.assertFalse(call(self.p.ep.act, action="act_reject", name=self.p.act, reason="x").get("error"))
		# somebody other than the author fixes it and sends it back
		self.p.user = self.OTHER
		self.p.actuals(submit=True, edit_doc=None)
		self.assertEqual(frappe.db.get_value(ACT, self.p.act, "resubmitted_by"), self.OTHER)
		out = self.approve(self.OTHER)
		self.assertIn("You resubmitted this work record", out.get("error") or "")
		# and the original author is still the author
		self.assertIn("You raised", self.approve("Administrator").get("error") or "")

	def test_on_bulk_approval_refuses_the_same_way(self):
		self.settings(block_self_approval=1)
		out = call(self.p.ep.act, action="act_approve_bulk", names=json.dumps([self.p.act]),
			stage="actuals_farm_manager")
		self.assertEqual(out.get("ok"), [])
		self.assertIn("You raised this work record", out["failed"][0]["why"])

	def test_on_every_chain_refuses_its_author(self):
		self.settings(block_self_approval=1)
		p = pipeline.Pipeline()
		p.master_plan(submit=True, approve=False)
		self.assertIn("You raised", call(p.ep.mp, action="gm_approve", name=p.mp).get("error") or "")
		bulk = call(p.ep.mp, action="plans_bulk", op="approve", names=json.dumps([p.mp]))
		self.assertIn("You raised", bulk["failed"][0]["why"])
		self.assertFalse(call(p.ep.mp, self.OTHER, action="gm_approve", name=p.mp).get("error"))
		p.plan(submit=True, approve=False)
		self.assertIn("You raised", p.approve_plan().get("error") or "")
		self.assertFalse(call(p.ep.pl, self.OTHER, action="approve", name=p.pl,
			stage="planner_farm_approval").get("error"))
		p.assignment(submit=True, approve=False)
		self.assertIn("You raised", call(p.ep.asg, action="a_approve", name=p.asg,
			stage="assigner_farm_manager").get("error") or "")


class TestTheListsShowThePeriodWorked(pipeline.SiteTestCase, unittest.TestCase):
	"""Work done 7-8 Sep, keyed 23 Sep, was listed as 23 Sep and paid as such.
	My Actuals and the approval queues now carry the first and last day worked."""

	def setUp(self):
		super().setUp()
		self.settings(att_block_absent=0, att_block_leave=0, att_block_noscan_actuals=0, att_block_off=0)
		self.p = pipeline.Pipeline()
		self.p.master_plan()
		self.p.plan()
		self.p.assignment()
		self.p.actuals(submit=True)

	def row(self, rows):
		return [r for r in rows if r["name"] == self.p.act][0]

	def test_my_actuals(self):
		r = self.row(call(self.p.ep.act, action="act_my")["actuals"])
		self.assertEqual((r["work_from"], r["work_to"]), (self.p.days()[0], self.p.days()[-1]))

	def test_the_approval_queue(self):
		r = self.row(call(self.p.ep.act, action="act_pending", stage="actuals_farm_manager")["pending"])
		self.assertEqual((r["work_from"], r["work_to"]), (self.p.days()[0], self.p.days()[-1]))

	def test_the_screen_heads_the_column_with_it(self):
		import os

		with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
				"public", "js", "work-actuals.js")) as handle:
			js = handle.read()
		self.assertEqual(js.count("<th>Period worked</th>"), 3)
		self.assertNotIn("<td>'+esc(isodate(r.entry_date)", js)
