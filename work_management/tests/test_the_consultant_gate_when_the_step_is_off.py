# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""A switched-off consultant step means the gate is satisfied, not unmet.

Every master plan activity carries `consultant_state`, default `Pending`, and
the only things that move it are the consultant's own actions. Switch
`masterplan_consultant` off and nothing ever does -- so:

  * `gm_approve` counts lines marked OK, finds none, and refuses with "Every
    activity was rejected, so there is nothing to approve" about a plan on which
    nothing was rejected;
  * a plan approved from the desk instead reaches `Approved` with every line
    `Pending`, and the planner's `budgets` then counts 0 activities, the task
    picker is empty, and `headroom` finds nothing to draw against.

Altura hit both on 2026-09-22; twenty rows were repaired by hand in System
Console. This pins the rule that replaces the hand repair, and the patch that
applies it to rows already on a site.

No site needed for the pure half::

    PYTHONPATH=. ~/frappe-bench3/env/bin/python -m unittest \\
        work_management.tests.test_the_consultant_gate_when_the_step_is_off -v
"""

import os
import re
import unittest

from work_management import approvals, consultant

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = os.path.join(APP, "api")


def read(path):
	with open(path, encoding="utf-8") as handle:
		return handle.read()


class FakeRow:
	def __init__(self, state="Pending"):
		self.consultant_state = state


class FakePlan:
	"""Just enough document for the validate hook: `.get("activities")`."""

	def __init__(self, states):
		self.rows = [FakeRow(s) for s in states]

	def get(self, fieldname):
		return self.rows if fieldname == "activities" else None


class GateOff:
	"""Run a block with the consultant step reporting as switched off."""

	def __init__(self, on):
		self.on = on

	def __enter__(self):
		self.saved = consultant.is_on
		consultant.is_on = lambda settings=None: self.on
		return self

	def __exit__(self, *exc):
		consultant.is_on = self.saved
		return False


class TestTheStepIsReadThroughApprovals(unittest.TestCase):
	"""One answer to "is this step enabled", shared with the workflow generator
	and the screens. Two answers is how a screen and a workflow part company,
	which is the fault this whole change exists to fix."""

	def test_the_step_it_guards_is_a_real_catalogue_step(self):
		self.assertIn(consultant.STAGE, {stage.key for stage in approvals.CATALOGUE})

	def test_it_asks_approvals_rather_than_reading_settings_itself(self):
		source = read(os.path.join(os.path.dirname(API), "consultant.py"))
		self.assertIn("approvals.by_key", source)
		self.assertIn("approvals.is_enabled", source)
		self.assertNotIn("get_single_value", source)

	def test_it_resolves_settings_before_asking_twice(self):
		"""`stage_rows()` tells "you did not say" from "there is no
		configuration" with its own sentinel, so a literal None means NO ROWS --
		and a step with no row reads as ENABLED. Passing None straight through
		therefore answered "the consultant step is on" on a site that had
		switched it off, which is the exact fault this module exists to fix,
		inverted. Caught on kentrout.local while verifying, 2026-09-22.
		"""
		source = read(os.path.join(os.path.dirname(API), "consultant.py"))
		at = source.index("def is_on(")
		body = source[at:source.index("\ndef ", at + 10)]
		self.assertIn("_settings_or_none()", body)
		self.assertNotIn("approvals.stage_rows(settings)\n\tif settings is None", body)
		# and the resolution happens before either call that needs it
		self.assertLess(body.index("settings = settings if settings is not None"),
			body.index("approvals.by_key("))


class TestSettlingADocument(unittest.TestCase):
	def test_pending_lines_are_settled_when_the_step_is_off(self):
		plan = FakePlan(["Pending", "Pending"])
		with GateOff(False):
			self.assertEqual(consultant.settle_doc(plan), 2)
		self.assertEqual([r.consultant_state for r in plan.rows], ["OK", "OK"])

	def test_nothing_happens_when_the_step_is_on(self):
		"""A Pending line is then a line waiting for somebody, which is exactly
		what it should say. Settling it would clear a review nobody has done."""
		plan = FakePlan(["Pending", "Pending"])
		with GateOff(True):
			self.assertEqual(consultant.settle_doc(plan), 0)
		self.assertEqual([r.consultant_state for r in plan.rows], ["Pending", "Pending"])

	def test_a_decided_line_is_never_overwritten(self):
		"""Switching the step off afterwards must not undo decisions somebody
		made while it was on -- a rejection especially."""
		plan = FakePlan(["Rejected", "Edit work", "OK", "Pending"])
		with GateOff(False):
			self.assertEqual(consultant.settle_doc(plan), 1)
		self.assertEqual([r.consultant_state for r in plan.rows],
			["Rejected", "Edit work", "OK", "OK"])

	def test_an_empty_state_counts_as_pending(self):
		"""A row written before the field had a default reads as empty, and an
		empty gate is an unmet one to every query that filters on 'OK'."""
		plan = FakePlan([None, ""])
		with GateOff(False):
			self.assertEqual(consultant.settle_doc(plan), 2)
		self.assertEqual([r.consultant_state for r in plan.rows], ["OK", "OK"])

	def test_it_is_idempotent(self):
		plan = FakePlan(["Pending"])
		with GateOff(False):
			self.assertEqual(consultant.settle_doc(plan), 1)
			self.assertEqual(consultant.settle_doc(plan), 0)

	def test_a_plan_with_no_lines_is_not_an_error(self):
		with GateOff(False):
			self.assertEqual(consultant.settle_doc(FakePlan([])), 0)


class TestItIsAppliedAtEveryWayIn(unittest.TestCase):
	"""One rule, applied where the rows are written -- not a condition every
	reader of consultant_state has to remember."""

	def test_the_desk_form_is_covered_by_a_validate_hook(self):
		"""The desk form is what a site works around a broken screen with, and
		it is what Altura was actually using."""
		hooks = read(os.path.join(os.path.dirname(API), "hooks.py"))
		self.assertIn('"Work Management Master Plan": {', hooks)
		self.assertIn('"validate": "work_management.consultant.settle_doc"', hooks)

	def test_the_actions_that_write_past_the_document_settle_explicitly(self):
		"""The master plan screen writes with frappe.db.set_value throughout, so
		no document is built and no hook fires."""
		source = read(os.path.join(API, "masterplan.py"))
		for action in ("submit_for_review", "gm_approve", "plans_bulk"):
			with self.subTest(action=action):
				at = source.index('elif action == "%s":' % action)
				nxt = source.find("\n    elif action", at + 10)
				self.assertIn("consultant.settle_and_note(",
					source[at:nxt if nxt > 0 else len(source)])

	def test_the_count_that_refused_now_runs_after_settling(self):
		"""Order matters: settling after the count leaves the refusal in place
		and merely repairs the rows for next time."""
		source = read(os.path.join(API, "masterplan.py"))
		at = source.index('elif action == "gm_approve":')
		branch = source[at:source.index("\n    elif action", at + 10)]
		self.assertLess(branch.index("consultant.settle_and_note("),
			branch.index("consultant_state = 'OK'"))

	def test_nobody_is_credited_with_a_decision_they_did_not_make(self):
		source = read(os.path.join(os.path.dirname(API), "consultant.py"))
		at = source.index("def settle(")
		body = source[at:source.index("\ndef ", at + 10)]
		self.assertNotIn("consultant_by", body,
			"stamping a name puts a decision in the trail that no person made")


class TestThePatchRepairsWhatIsAlreadyThere(unittest.TestCase):
	PATCH = os.path.join(os.path.dirname(API), "patches", "v1_0",
		"settle_activities_with_no_consultant_step.py")

	def test_it_is_registered(self):
		listed = read(os.path.join(os.path.dirname(API), "patches.txt"))
		self.assertIn(
			"work_management.patches.v1_0.settle_activities_with_no_consultant_step",
			listed)

	def test_it_no_ops_where_the_step_is_on(self):
		source = read(self.PATCH)
		self.assertIn("if consultant.is_on():", source)
		self.assertIn("return", source)

	def test_it_shares_the_rule_rather_than_restating_it(self):
		"""The hand repair and the code drifting apart is how a site ends up with
		two definitions of a settled line."""
		source = read(self.PATCH)
		self.assertIn("consultant.settle_and_note(", source)
		self.assertNotIn("set_value", source)

	def test_it_only_touches_pending_rows(self):
		source = read(os.path.join(os.path.dirname(API), "consultant.py"))
		self.assertIn('"consultant_state": PENDING', source)


if __name__ == "__main__":
	unittest.main()
