"""Adding a worker to work already approved.

Swap and release were the only two verbs the crew had. Swap needs somebody to
take the leaver's place; release says they have gone. Neither says "this person
worked and is not on the list", which is what a clerk discovers while typing
the day's quantities -- and the actuals grid only offers the assignment's own
roster, so there was no way to record it.

WHY THE HEAD COUNT ONLY WARNS

`people_per_day` reads like a limit and is not a spending control. The spending
control is the plan's quantity, and wm_actuals refuses to pass it server-side --
"Exceeds plan target. Target is ...". Pay is quantity x rate, so total pay is
capped however many people share the work; an extra body means the same
budgeted work divided further, not more money.

That matters because of the shape of the real data: 1,316 of 1,497 approved
assignments on v16 sit EXACTLY at their people_per_day, and reading it as peak
concurrent crew barely helps -- still 1,316, because closing a plan releases the
whole crew at the end rather than mid-period. Refusing on the cap would block
the feature on 88% of assignments while protecting nothing.

WHAT IT DOES REFUSE

The three from substitution, each for a reason that is not about budget:
already on this roster (a mistake), not a task worker under current Settings
(their work could never be paid), and active elsewhere over these dates --
which warns instead when a split day is allowed, matching the assign screen.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_adding_crew -v
"""

import os
import re
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(APP, "public", "js")
MIRROR = "/home/austin/vscodeProjects/kaitet-work-management/server_scripts"


def script(name):
	with open(os.path.join(MIRROR, name + ".py")) as handle:
		return handle.read()


def screen(name):
	with open(os.path.join(JS, name + ".js")) as handle:
		return handle.read()


def action_block(text, action):
	at = text.index('elif action == "%s":' % action)
	nxt = re.search(r"^elif action ==", text[at + 30:], re.M)
	return text[at:at + 30 + (nxt.start() if nxt else len(text))]


class TestTheMirrorIsCheckedOut(unittest.TestCase):
	def setUp(self):
		if not os.path.isdir(MIRROR):
			self.skipTest("mirror not present")
		self.assigner = script("wm_assigner")


class TestTheActionExists(TestTheMirrorIsCheckedOut):
	def test_the_assigner_serves_it(self):
		self.assertIn('elif action == "a_add_crew":', self.assigner)

	def test_it_is_a_write_on_both_screens(self):
		"""A write not in the screen's `writes` map goes out as a GET with no
		CSRF token, and frappe refuses it."""
		for name in ("work-assigner", "work-actuals"):
			with self.subTest(screen=name):
				text = screen(name)
				at = text.index("var writes")
				self.assertIn("a_add_crew", text[at:at + 400],
					"%s does not treat a_add_crew as a write" % name)

	def test_both_screens_call_it(self):
		for name in ("work-assigner", "work-actuals"):
			with self.subTest(screen=name):
				self.assertIn('action:"a_add_crew"', screen(name))


class TestWhatItRefuses(TestTheMirrorIsCheckedOut):
	def setUp(self):
		super().setUp()
		self.block = action_block(self.assigner, "a_add_crew")

	def test_only_an_approved_assignment(self):
		self.assertIn("Assigned", self.block)

	def test_somebody_already_on_the_roster(self):
		self.assertRegex(self.block, r"(?i)already on th")

	def test_somebody_who_is_not_a_task_worker(self):
		"""Their work could never be paid through this system, so adding them
		would be recording work nobody will ever settle."""
		self.assertIn("TW_MATCH", self.block)
		self.assertRegex(self.block, r"(?i)task worker")

	def test_the_role_gate_is_enforced_here_not_only_in_the_browser(self):
		"""Release's gate lived only in the JS until today. A gate in the browser
		is not a gate."""
		self.assertRegex(self.block, r"frappe\.get_roles")
		self.assertIn("Farm Manager", self.block)
		self.assertIn("HOD HR", self.block)
		self.assertIn("General Manager", self.block)


class TestWhatItOnlyWarnsAbout(TestTheMirrorIsCheckedOut):
	def setUp(self):
		super().setUp()
		self.block = action_block(self.assigner, "a_add_crew")

	def test_the_head_count_warns_rather_than_refusing(self):
		"""See the module docstring: the quantity cap is the spending control,
		and 1,316 of 1,497 assignments sit exactly at people_per_day."""
		self.assertIn("cap_warning", self.block)
		self.assertNotRegex(self.block, r'err = \("?Too many workers')

	def test_it_still_says_what_the_plan_budgeted(self):
		"""Warning silently would be no better than not checking."""
		self.assertIn("planned_people", self.block)

	def test_being_busy_elsewhere_follows_the_split_day_switch(self):
		self.assertIn("ALLOW_SPLIT_DAY", self.block)

	def test_it_reports_what_it_did(self):
		for key in ("added", "active_count", "variance"):
			with self.subTest(key=key):
				self.assertIn('"%s"' % key, self.block)


class TestTheJoiningDateBoundsTheirWork(TestTheMirrorIsCheckedOut):
	"""The mirror of left_date. Work recorded before somebody joined is as
	doubtful as work recorded after somebody left, and the actuals screen
	already warns about the second."""

	def test_the_action_records_a_start_date(self):
		self.assertIn("start_date", action_block(self.assigner, "a_add_crew"))

	def test_the_actuals_screen_warns_about_work_before_it(self):
		text = script("wm_actuals")
		self.assertIn("joined_warning", text)

	def test_it_warns_rather_than_refusing(self):
		"""Same reasoning as the release warning: a clerk may be entering a day
		that genuinely predates the join, or correcting one."""
		text = script("wm_actuals")
		at = text.index("joined_warning")
		self.assertNotRegex(text[max(0, at - 600):at], r'out\["error"\]')


class TestTheTwoThingsFixedOnTheWay(TestTheMirrorIsCheckedOut):
	def test_the_worker_picker_honours_the_split_day_switch(self):
		"""a_employees excludes anyone already assigned over the dates. With a
		split day permitted that is no longer an exclusion, or the picker will
		hide exactly the people the switch was turned on to allow."""
		self.assertIn("ALLOW_SPLIT_DAY", action_block(self.assigner, "a_employees"))

	def test_act_detail_answers_rather_than_crashing(self):
		"""It raised `TypeError: 'NoneType' object does not support item
		assignment` on a missing or wrong assignment -- a 500 where an error
		message belongs. The add flow leans on this endpoint."""
		block = action_block(script("wm_actuals"), "act_detail")
		at = block.index("a = frappe.db.get_value")
		# the lookup spans several lines, so the guard is not within a few
		# characters of it -- what matters is that it comes before the first
		# assignment into `a`, which is what raised
		first_write = block.index('a["', at)
		self.assertIn("if not a:", block[at:first_write],
			"nothing guards the None before the first a[...] assignment")


if __name__ == "__main__":
	unittest.main()
