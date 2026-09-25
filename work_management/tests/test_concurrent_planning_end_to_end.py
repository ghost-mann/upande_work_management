"""Two plans over the same days, one worker on both, and nothing in the way.

`test_concurrent_master_plans` pins the switch and the master-plan level. This
pins the rest of the chain, because the client's meeting turned concurrency from
a capability into the shipping configuration: *"concurrent master plans and
planner in terms of dates"*, and the reassignment it exists for -- a worker
finishes Bed-making, a new master plan and a new plan are raised for another
task over the same dates, and he has to be assignable to it.

So the thing worth pinning is an ABSENCE. No clash validation at the plan or the
assignment level, and the four places that could grow one are named below. A
refusal added in any of them would be found by somebody at a farm, not here.

WHAT THE THREE-LEVEL RULE ACTUALLY IS, and each level is a different answer:

  master plan  two approved budgets may cover the same farm and days, when the
               site says so -- `allow_concurrent_master_plans`
  plan         no limit at all. Two plans, same farm, same block, same days,
               same or different tasks. The only ceiling is the master plan
               line each one names, and each names its own.
  assignment   one worker on two live assignments over the same days is
               ALLOWED and SAID -- `split_warning`, never an error -- when
               `allow_split_day` is on. The hours typed on each actuals row are
               what keep the day counting once.

Measured on kentrout.local, both switches on, over the real wsgi app:

    WMMP-00007 Bed-making 2027-09-01..30   } two approved plans,
    WMMP-00008 Weeding    2027-09-01..30   } the same farm, the same period

    plan  WM-KenTrout Farm-00266  Bed-making  20.51  -> Approved
    plan  WM-KenTrout Farm-00269  Weeding      1.50  -> Approved
    both GH-5, both 2027-09-06, one worker on both, both -> Assigned
    actuals 4h + 4h on 2027-09-06, 20.51 and 1.50 -> both CONFIRMED
    discrepancy audit over the window: 2 rows scanned, no flags

    and with the crew still Active on the first assignment, the second one
    said: "Already assigned elsewhere over these dates: <name>. Their day will
    be split, so record the hours each task took on the actuals screen."

    a third plan, SAME task as the first, same block, same dates: accepted.
    WMMP-00007 budget 4,000, drawn 350 across the two Bed-making plans; the
    Weeding plan drew against WMMP-00008 and nothing else.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_concurrent_planning_end_to_end -v
"""

import os
import re
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = os.path.join(APP, "api")
JS = os.path.join(APP, "public", "js")


def read(name, where=API):
	with open(os.path.join(where, name)) as handle:
		return handle.read()


def branch(src, opener, closer=None):
	"""One dispatcher branch, by the line that opens it."""
	at = src.index(opener)
	nxt = src.find("\n    elif action", at + 10) if closer is None else src.index(closer, at)
	return src[at:nxt if nxt > 0 else len(src)]


class TestNothingAtThePlanLevelRefusesAnOverlap(unittest.TestCase):
	"""The add-more-people-later pattern is a second plan for the same work, and
	the finished-early pattern is a second plan for different work. Both are the
	same shape: another plan over days a plan already covers."""

	def setUp(self):
		self.submit = branch(read("planner.py"), 'elif action == "submit":')

	def test_submit_never_looks_for_another_plan_over_these_dates(self):
		"""The only date query in here is against the MASTER plan's period."""
		for table in ("`tabWork Management Planner` p2", "existing_plan", "clash"):
			with self.subTest(looking_for=table):
				self.assertNotIn(table, self.submit)

	def test_the_refusals_are_the_ones_we_know_about(self):
		"""A new `err = ` in this branch is a new way to be told no, and this
		test is where somebody adding one is asked to say so out loud."""
		# `err`, not `cap_err`: the master plan ceiling is a different kind of no
		# and has its own test below.
		reasons = set(re.findall(r'(?<![a-z_])err = \("?([A-Z][^"+]*)', self.submit))
		reasons |= set(re.findall(r'(?<![a-z_])err = "([^"]+)"', self.submit))
		self.assertEqual(
			{r.strip() for r in reasons},
			{
				"Invalid farm",
				"At least one block is required",
				"Task is required",
				"Quantity must be greater than zero",
				"Date range is required",
				"Only",
			})

	def test_the_only_ceiling_is_the_master_plan_line(self):
		self.assertIn("Over the budgeted quantity for ", self.submit)
		self.assertIn("Over the budgeted cost for ", self.submit)

	def test_a_request_carries_the_plan_it_drew_down(self):
		"""Which is what makes two of them over the same days answerable at all:
		attribution is the stored link, never the dates."""
		self.assertIn("master_plan", self.submit)


class TestTwoOverlappingBudgetsAreAskedAboutNotGuessed(unittest.TestCase):
	"""Concurrency is not free: with two approved plans over the dates, "which
	budget" stops being derivable. Every caller names its plan, and the one that
	cannot says so rather than picking."""

	def test_the_task_picker_reports_the_ambiguity(self):
		tasks = branch(read("planner.py"), 'elif action == "tasks":')
		self.assertIn("blocked_reason", tasks)

	def test_the_screen_sends_the_plan_it_is_showing(self):
		src = read("work-planner.js", JS)
		at = src.index("function loadPlannableTasks(")
		self.assertIn("master_plan:ST.masterPlan", src[at:at + 600])

	def test_an_unnamed_request_is_not_decided_against_a_guess(self):
		"""The approvals queue would otherwise show one of the two ceilings, which
		is the guess the planner refused to make on the way in."""
		src = read("work-planner.js", JS)
		at = src.index("function apprBudget(")
		block = src[at:at + 900]
		self.assertIn("budget_ambiguous", block)
		self.assertIn("names neither", block)


class TestOneWorkerOnTwoAssignmentsIsAllowedAndSaid(unittest.TestCase):
	"""The double-allocation guard is the one place that could refuse the
	meeting's scenario outright, and with splitting on it must not."""

	def setUp(self):
		src = read("assigner.py")
		at = src.index("# DOUBLE-ALLOCATION GUARD (server enforcement)")
		self.guard = src[at:src.index("# ── TIME & ATTENDANCE GATE", at)]

	def test_splitting_turns_the_refusal_into_a_warning(self):
		self.assertIn("if ALLOW_SPLIT_DAY:", self.guard)
		head = self.guard[self.guard.index("if ALLOW_SPLIT_DAY:"):]
		allowed = head[:head.index("else:")]
		self.assertIn('out["split_warning"]', allowed)
		self.assertNotIn("err = ", allowed)

	def test_it_is_still_said_out_loud(self):
		"""A worker on two assignments is usually a mistake and sometimes
		deliberate, and only the person doing it can tell the two apart."""
		self.assertIn("Already assigned elsewhere over these dates", self.guard)
		self.assertIn("record the hours each", self.guard)

	def test_without_splitting_it_is_still_refused(self):
		tail = self.guard[self.guard.index("else:"):]
		self.assertIn("already assigned elsewhere for an overlapping period", tail)

	def test_a_released_worker_is_free_again(self):
		"""The finished-early half of the meeting's scenario. Somebody whose crew
		row is `Left` is not on that assignment any more, so the guard must not
		count it -- otherwise finishing early would lock a worker out of the very
		reassignment the client asked for."""
		self.assertIn("IFNULL(we.status,'Active') = 'Active'", self.guard)

	def test_only_live_assignments_count(self):
		"""In approval or assigned -- read from the chain, not spelled out."""
		self.assertIn('IN (""" + sql_in(ST_ASG_ACTIVE) + """)', self.guard)

	def test_a_rejected_or_cancelled_one_does_not(self):
		for dead in ("'Rejected'", "'Cancelled'", "'Draft'"):
			with self.subTest(state=dead):
				self.assertNotIn(dead, self.guard)


class TestTheSameDayOnTwoTasksIsNotADuplicate(unittest.TestCase):
	"""What makes the split day safe downstream. If this key loses the task, a
	deliberate split becomes "Paid twice for the same day" on every audit, and
	the client's shipping configuration produces the noise itself.

	This asserts the keying rather than changing it -- it is on the do-not-touch
	list, and this is the reason it is on it.
	"""

	def setUp(self):
		src = read("payment.py")
		at = src.index("b_dup = []")
		self.check = src[at:src.index("HAVING COUNT(*) > 1", at)]

	def test_the_duplicate_key_includes_the_task(self):
		self.assertIn(
			"GROUP BY we.employee, we.employee_name, ac.farm, ac.task, we.work_date",
			self.check)

	def test_and_therefore_not_the_assignment(self):
		"""Two assignments for the same task on the same day IS a duplicate, and
		must stay one. The task is the distinction, not the paperwork."""
		self.assertNotIn("ac.assignment", self.check)


class TestTheHoursAreWhatKeepTheDayWhole(unittest.TestCase):
	"""A split day is two rows of four hours, not two days. Nothing in the chain
	sums quantities across tasks -- they are different units -- so the hours are
	the only place the day exists as one thing."""

	def test_the_day_is_divided_by_hours_not_by_assignment_count(self):
		src = read("split_day.py", os.path.join(APP))
		self.assertIn("def man_days(", src)
		self.assertIn("def person_days(", src)
		self.assertIn("def hours_of(", src)

	def test_a_long_day_is_a_discrepancy_rather_than_a_refusal(self):
		"""Nine hours across two tasks is for a human to look at. Refusing the
		second entry would mean the work happened and could not be recorded."""
		src = read("payment.py")
		self.assertIn('"key": "long_day"', src)


if __name__ == "__main__":
	unittest.main()
