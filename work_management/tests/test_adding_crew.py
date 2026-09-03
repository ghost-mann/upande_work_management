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


class TestThePickerIsAPicker(unittest.TestCase):
	"""Not a browser prompt.

	The first version of both controls asked for their input with
	`window.prompt`: for add, a numbered list of names and "type the worker id";
	for release, a date typed as free text. Both worked and neither was usable --
	the eligible pool is the farm's whole workforce, 229 on the assignment this
	was built against, and a typed date has no picker and no validation, so a
	slip becomes a silent bad date.

	Both are modals now, in the same card the substitute and early-close modals
	already use, so there is one dialog shape on this screen rather than three.
	"""

	def setUp(self):
		self.js = screen("work-actuals")
		with open(os.path.join(APP, "www", "work-actuals.html")) as handle:
			self.html = handle.read()

	def test_no_prompt_is_left_on_the_screen(self):
		self.assertNotIn("window.prompt", self.js,
			"a browser prompt is still doing the work of a form")

	def test_both_modals_exist_in_the_page(self):
		for node in ("ac-addmodal", "ac-relmodal"):
			with self.subTest(node=node):
				self.assertIn('id="%s"' % node, self.html)

	def test_they_reuse_the_established_card(self):
		"""Three dialogs on one screen should not be three shapes."""
		for node in ("ac-addmodal", "ac-relmodal"):
			at = self.html.index('id="%s"' % node)
			window = self.html[at:at + 1600]
			with self.subTest(node=node):
				for part in ("submodal-card", "submodal-head", "submodal-body", "submodal-foot"):
					self.assertIn(part, window)

	def test_the_add_picker_can_be_searched(self):
		"""229 candidates is too many to scroll blind."""
		self.assertIn('id="ac-add-q"', self.html)
		self.assertIn("renderAddList", self.js)
		self.assertRegex(self.js, r'el\("ac-add-q"\)\.oninput\s*=\s*renderAddList')

	def test_the_dates_are_date_inputs_bounded_by_the_assignment(self):
		for node in ("ac-add-date", "ac-rel-date"):
			with self.subTest(node=node):
				self.assertRegex(self.html, r'<input type="date" id="%s"' % node)
		# and bounded, so a date outside the window cannot be picked at all
		self.assertRegex(self.js, r'el\("ac-add-date"\)\.min\s*=')
		self.assertRegex(self.js, r'\.min\s*=\s*a\.from_date')

	def test_confirm_stays_disabled_until_there_is_something_to_confirm(self):
		for node in ("ac-add-go", "ac-rel-go"):
			with self.subTest(node=node):
				at = self.html.index('id="%s"' % node)
				self.assertIn("disabled", self.html[at:at + 120])

	def test_the_busy_are_shown_as_busy_rather_than_hidden(self):
		"""With a split day allowed they are pickable, and the reader should know
		what they are picking."""
		self.assertIn("also on ", self.js)
		self.assertIn("addtag", self.html)

	def test_both_are_wired_at_boot(self):
		"""Defined and never called is the easiest way to ship a dead dialog."""
		for fn in ("wireAddModal();", "wireRelModal();"):
			with self.subTest(fn=fn):
				self.assertIn(fn, self.js)

	def test_they_can_be_dismissed(self):
		for node in ("ac-add-x", "ac-add-cancel", "ac-rel-x", "ac-rel-cancel"):
			with self.subTest(node=node):
				self.assertIn('id="%s"' % node, self.html)


class TestTheGridStillRendersBeforeAnythingIsAppendedToIt(unittest.TestCase):
	"""The add bar broke the grid, and no test could have noticed.

	Adding the bar meant inserting code between `box.innerHTML=h;` and the input
	wiring that follows it -- and the edit replaced that line instead of keeping
	it. The whole worker grid stopped rendering: `h` was built and thrown away,
	and the bar was appended to whatever the container held from before.

	Nothing caught it. No test executes this JS, `node --check` only parses, and
	the served file was verifiably present and current -- which is exactly what I
	checked and reported. It took someone opening the screen.

	So this asserts the shape instead: the container is filled before anything is
	appended to it, and there is exactly one place doing the filling.
	"""

	def setUp(self):
		self.js = screen("work-actuals")

	def grid_function(self):
		at = self.js.index("ac-addbar")
		start = self.js.rindex("function ", 0, at)
		end = self.js.index('box.querySelectorAll("input[data-emp]")', at)
		return self.js[start:end]

	def test_the_container_is_filled(self):
		block = self.grid_function()
		self.assertIn("box.innerHTML=h;", block,
			"the grid html is built and never written to the page")

	def test_it_is_filled_before_the_bar_is_appended(self):
		"""Appending first and assigning innerHTML afterwards would silently
		wipe the bar out again."""
		block = self.grid_function()
		self.assertLess(block.index("box.innerHTML=h;"), block.index("box.appendChild(addbar)"))

	def test_the_html_that_was_built_is_the_html_that_is_written(self):
		"""`h` accumulates the whole table; anything else assigned here would
		mean part of it was dropped."""
		block = self.grid_function()
		self.assertRegex(block, r"box\.innerHTML\s*=\s*h\s*;")

	def test_the_add_bar_is_a_sibling_of_the_grid_not_inside_the_table(self):
		"""It changes who the grid is about, which is a different kind of action
		from typing in a cell -- and a div inside a table renders unpredictably."""
		block = self.grid_function()
		self.assertIn('addbar.className = "ac-addbar"', block)
		self.assertNotRegex(block, r"h\s*\+=\s*'<div class=\"ac-addbar\"")
