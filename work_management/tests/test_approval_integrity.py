"""Approval integrity (2026-11-12): two pairs of eyes with named stand-ins,
edits mid-approval, early close, the end of the chain, the desk path.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest work_management.tests.test_approval_integrity -v
"""

import importlib
import sys
import types
import unittest

from work_management.tests.test_amount_sanity import block
from work_management.tests.test_one_worker_one_day import Row, source
from work_management.tests.test_payroll_check import nested


def step_err(user, roles=(), standins=(), form=None):
	comments = []

	class D:
		def add_comment(self, kind, text):
			comments.append(text)

	fake = types.SimpleNamespace(
		session=types.SimpleNamespace(user=user),
		form_dict=dict(form or {}),
		get_roles=lambda: list(roles),
		get_doc=lambda dt, n: D(),
		db=types.SimpleNamespace(exists=lambda dt, n=None: True,
			get_all=lambda dt, filters=None, fields=None: [Row(s) for s in standins]))
	return nested("actuals", "wmg_step_err", {"frappe": fake}), comments


class TestTwoPairsOfEyes(unittest.TestCase):
	def test_somebody_else_passes(self):
		fn, _ = step_err("hr@x")
		self.assertEqual(fn("actuals_gm", "Lokitela", ["clerk@x", "fm@x"], "Work Management Actuals", "WMAC-1"), "")

	def test_the_same_person_is_refused_and_told_who_can(self):
		fn, _ = step_err("koskey@x", standins=[{"user": "peter@x", "farm": None}])
		msg = fn("actuals_gm", "Lokitela", ["clerk@x", "koskey@x"], "Work Management Actuals", "WMAC-1")
		self.assertIn("somebody else", msg)
		self.assertIn("peter@x", msg)

	def test_a_system_manager_needs_a_reason_and_it_is_logged(self):
		fn, comments = step_err("admin@x", roles=["System Manager"])
		self.assertTrue(fn("actuals_hr", None, ["admin@x"], "Work Management Actuals", "WMAC-1"))
		fn, comments = step_err("admin@x", roles=["System Manager"], form={"override_reason": "only approver on leave"})
		self.assertEqual(fn("actuals_hr", None, ["admin@x"], "Work Management Actuals", "WMAC-1"), "")
		self.assertIn("only approver on leave", comments[0])

	def test_every_approval_applies_it(self):
		for module, action, stage in (("actuals", "act_fm_approve", "actuals_fm"), ("actuals", "act_hr_approve", "actuals_hr"),
				("actuals", "act_gm_approve", "actuals_gm"), ("assigner", "a_fm_approve", "assigner_fm"),
				("assigner", "a_hr_approve", "assigner_hr"), ("assigner", "a_gm_approve", "assigner_gm"),
				("planner", "approve", "planner_fm")):
			b = block(module, action)
			with self.subTest(action=action):
				self.assertIn('wmg_step_err("' + stage + '"', b)
				self.assertIn('wmg_si("' + stage + '"', b)
				self.assertIn('out["error"] = wmg_se', b)

	def test_the_check_accepts_stand_ins(self):
		src = source("payment")
		self.assertIn('wmg_si("check_gm", None)', src)
		self.assertIn('wmg_si("check_hr", None)', src)


class TestEditingMidApproval(unittest.TestCase):
	def test_only_the_steps_approver_on_its_own_assignment(self):
		b = block("actuals", "act_submit")
		self.assertIn("That record belongs to another assignment", b)
		self.assertIn('ep_err = wmg_farm_err(ep_before.farm, "change this record")', b)
		self.assertIn("if not wmg_err and ep_err:", b)

	def test_a_change_in_pay_starts_the_approvals_again(self):
		b = block("actuals", "act_submit")
		self.assertIn('out["sent_back_to_fm"] = 1', b)
		self.assertIn('"fm_approved_by": None, "hr_approved_by": None', b)


class TestEarlyCloseAndTheEndOfTheChain(unittest.TestCase):
	def test_rejected_is_never_revived_and_drafts_need_a_tick(self):
		b = block("actuals", "act_close_confirm")
		self.assertIn('if ar.ws == "Rejected":', b)
		self.assertIn('frappe.form_dict.get("confirm_drafts")', b)

	def test_the_last_step_submits_the_record(self):
		self.assertIn('wmg_finalise(nm, STAGE_NEXT["actuals_hr_head"])', block("actuals", "act_hr_approve"))
		self.assertIn('wmg_finalise(nm, STAGE_NEXT["actuals_farm_manager"])', block("actuals", "act_fm_approve"))


class TestTheDeskPath(unittest.TestCase):
	def load(self, user, roles=()):
		fake = types.ModuleType("frappe")

		class Stop(Exception):
			pass

		def throw(msg, *a, **k):
			raise Stop(msg)

		fake.throw = throw
		fake._ = lambda s: s
		fake.session = types.SimpleNamespace(user=user)
		fake.get_roles = lambda: list(roles)
		fake.utils = types.SimpleNamespace(today=lambda: "2026-11-12")
		self.saved = sys.modules.get("frappe")
		sys.modules["frappe"] = fake
		import work_management.duplicate_guard as guard
		importlib.reload(guard)
		return guard, Stop

	def tearDown(self):
		if self.saved is not None:
			sys.modules["frappe"] = self.saved
		else:
			del sys.modules["frappe"]

	def doc(self, old, new, **kw):
		written = {}
		before = Row(workflow_state=old)
		d = Row(workflow_state=new, entered_by="clerk@x", owner="clerk@x", flags=Row(), **kw)
		d.get_doc_before_save = lambda: before
		d.get = lambda k, dflt=None: dict.get(d, k, dflt)
		d.meta = types.SimpleNamespace(get_field=lambda f: True)
		d.db_set = lambda f, v, update_modified=False: written.__setitem__(f, v)
		return d, written

	def test_the_enterer_cannot_approve_on_the_desk(self):
		guard, Stop = self.load("clerk@x")
		d, _ = self.doc("Pending Farm Manager", "Pending HR Head")
		with self.assertRaises(Stop):
			guard.desk_step_check(d)

	def test_a_desk_approval_records_who(self):
		guard, Stop = self.load("hro@x")
		d, written = self.doc("Pending HR Head", "Pending GM")
		guard.desk_step_check(d)
		guard.on_actuals_update(d)
		self.assertEqual(written.get("hr_approved_by"), "hro@x")


if __name__ == "__main__":
	unittest.main()


class TestTheAssignmentChainEndsWhereSettingsSay(unittest.TestCase):
	"""2026-11-13: live switched the assignment HR and GM steps off; the farm
	manager's approval must then finalise the assignment."""

	def test_fm_and_hr_steps_finalise_when_they_end_the_chain(self):
		self.assertIn('wmg_asg_finalise(nm, STAGE_NEXT["assigner_farm_manager"])', block("assigner", "a_fm_approve"))
		self.assertIn('wmg_asg_finalise(nm, STAGE_NEXT["assigner_hr_head"])', block("assigner", "a_hr_approve"))
