"""The GM can turn a close down, take one back, and see every rejection.

Closing a plan early had one verb for the GM: "Approve & close". A request he
disagreed with had nowhere to go -- it sat in his queue with the plan stuck at
"Close Requested", and a plan he had closed by mistake could not be opened
again. And the Rejected tab read `act_my`, so the GM, who does most of the
rejecting, could not see a single rejected actual that was not his own.

WHAT REOPENING DOES NOT UNDO

A close does three things (see act_close_confirm): it force-confirms every open
actual, marks the plan Closed, and releases the crew. Reopening undoes only the
second. The confirmed actuals may already be in a payment run, so taking them
back could unpay or double-pay somebody; and a released worker may be on
another assignment by now. The clerk re-adds whoever is still needed with Add
crew. That was the agreed design, so a reopen that reached into either table
is a regression, not an improvement.

WHY COMMENTS AND NOT FIELDS

Who turned a close down, who reopened, who rejected an actual: each is a
history, and a plan can be requested, refused and requested again. A timeline
comment keeps every round; a field keeps the last. It also needs no schema
change on a live site. An actual's rejection is written as a "Workflow" comment
reading "Rejected" -- the same row Frappe's own workflow writes when somebody
rejects from the desk -- so one query answers "rejected by" for both routes.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_the_gm_can_undo_a_close -v
"""

import os
import re
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
	with open(os.path.join(APP, *parts)) as handle:
		return handle.read()


API = read("api", "actuals.py")
JS = read("public", "js", "work-actuals.js")


def action_block(action):
	at = API.index('elif action == "%s":' % action)
	nxt = re.search(r"^\s*elif action ==", API[at + 30:], re.M)
	return API[at:at + 30 + (nxt.start() if nxt else len(API))]


def gm_gated(block):
	return ('"General Manager" in crl' in block) and ('"System Manager" in crl' in block)


class TestRejectingACloseRequest(unittest.TestCase):
	def setUp(self):
		self.block = action_block("act_close_reject")

	def test_only_the_gm_may(self):
		self.assertTrue(gm_gated(self.block))
		self.assertIn("if not err and not is_gm", self.block)

	def test_a_reason_is_required(self):
		self.assertRegex(self.block, r"if not reason:\s*\n\s*err =")

	def test_only_a_pending_request_can_be_turned_down(self):
		self.assertIn('!= "Close Requested"', self.block)

	def test_the_plan_goes_back_to_open_and_the_request_is_cleared(self):
		for field in ("custom_close_state", "custom_close_requested_by",
				"custom_close_request_date", "custom_close_reason"):
			with self.subTest(field=field):
				self.assertRegex(self.block,
					r'set_value\("Work Management Planner", plan, "%s", (""|None)' % field)

	def test_the_refusal_is_on_the_plans_timeline(self):
		self.assertRegex(self.block, r'add_comment\("Info",\s*"Close request')

	def test_it_touches_neither_actuals_nor_crew(self):
		self.assertNotIn('set_value("Work Management Actuals"', self.block)
		self.assertNotIn("Work Assignment Employee", self.block)


class TestTheRequesterSeesTheRefusal(unittest.TestCase):
	def test_close_roles_returns_the_last_refusal(self):
		block = action_block("act_close_roles")
		self.assertIn('out["last_close_rejection"]', block)
		self.assertIn("Close request", block)

	def test_the_close_box_shows_it(self):
		self.assertIn("d.last_close_rejection", JS)


class TestReopeningAClosedPlan(unittest.TestCase):
	def setUp(self):
		self.block = action_block("act_reopen")

	def test_only_the_gm_may(self):
		self.assertTrue(gm_gated(self.block))
		self.assertIn("if not err and not is_gm", self.block)

	def test_a_reason_is_required(self):
		self.assertRegex(self.block, r"if not reason:\s*\n\s*err =")

	def test_only_an_early_close_reopens(self):
		"""Completed means the target was met; there is nothing to reopen."""
		self.assertIn('!= "Closed"', self.block)

	def test_the_plan_goes_back_to_open(self):
		for field in ("custom_close_state", "custom_closed_by", "custom_closed_date"):
			with self.subTest(field=field):
				self.assertRegex(self.block,
					r'set_value\("Work Management Planner", plan, "%s", (""|None)' % field)

	def test_the_reopen_is_on_the_plans_timeline(self):
		self.assertRegex(self.block, r'add_comment\("Info",\s*"Reopened')

	def test_confirmed_actuals_and_released_workers_are_left_alone(self):
		"""See the module docstring: pay may already have gone out."""
		self.assertNotIn('set_value("Work Management Actuals"', self.block)
		self.assertNotIn("Work Assignment Employee", self.block)


class TestTheClosedPlansList(unittest.TestCase):
	def setUp(self):
		self.block = action_block("act_closed_list")

	def test_only_the_gm_sees_it(self):
		self.assertTrue(gm_gated(self.block))
		self.assertIn('out["not_gm"] = 1', self.block)

	def test_it_lists_early_closes_only(self):
		self.assertIn('"custom_close_state": "Closed"', self.block)


class TestRejectedActuals(unittest.TestCase):
	def setUp(self):
		self.block = action_block("act_rejected")

	def test_the_gm_sees_every_rejection(self):
		self.assertTrue(gm_gated(self.block))
		self.assertIn('{"workflow_state": "Rejected"}', self.block)

	def test_everybody_else_still_sees_only_their_own(self):
		self.assertRegex(self.block, r'flt\["entered_by"\] = frappe\.session\.user')

	def test_it_says_who_entered_and_who_rejected(self):
		self.assertIn('"entered_by"', self.block)
		self.assertIn('"rejected_by"', self.block)
		self.assertIn("comment_type = 'Workflow'", self.block)

	def test_the_tab_reads_it(self):
		at = JS.index("function loadRejected")
		self.assertIn('action:"act_rejected"', JS[at:at + 600])

	def test_the_gm_gets_no_edit_link_on_somebody_elses(self):
		"""Fixing and resubmitting stays with the clerk who entered it."""
		at = JS.index("function loadRejected")
		self.assertIn("r.entered_by===me", JS[at:at + 4000])


class TestRejectingAnActualRecordsWho(unittest.TestCase):
	def test_the_rejection_is_a_workflow_comment(self):
		"""The row Frappe's own workflow writes, so desk rejections and screen
		rejections answer the same query."""
		self.assertIn('add_comment("Workflow", "Rejected")', action_block("act_reject"))


class TestTheScreenWiring(unittest.TestCase):
	def test_every_new_write_carries_a_csrf_token(self):
		at = JS.index("var writes")
		writes = JS[at:at + 400]
		for action in ("act_close_reject", "act_reopen"):
			with self.subTest(action=action):
				self.assertIn(action, writes)

	def test_the_close_queue_has_a_reject_button(self):
		at = JS.index("function loadCloseRequests")
		self.assertIn("data-clrej", JS[at:at + 5000])

	def test_the_gm_has_a_closed_plans_queue(self):
		at = JS.index("function apprQueues")
		self.assertIn('key:"closed"', JS[at:at + 800])
		self.assertIn('action:"act_closed_list"', JS)
		self.assertIn("data-reopen", JS)


if __name__ == "__main__":
	unittest.main()
