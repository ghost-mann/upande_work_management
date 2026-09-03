"""Who the actuals grid calls a task worker, and who decides it.

The screen used to decide by itself: `employment_type === "Task Worker"`. The
server had already stopped doing that -- Settings names the payable group, and
it may name it by employment type, by designation, or by category -- so on any
site that used one of the other two the two halves disagreed. Every worker read
as salaried in the browser: their work went unpriced, they were tagged
"salaried", and swap and release disappeared from every row, while payment,
reading Settings, went on paying them.

kentrout.local is such a site. All 77 Employees have employment_type unset and
task workers are named by designation, so the grid offered no release button on
any row of any assignment -- which is how this was found.

The fix is that the answer travels with the row. These tests hold the two
halves together: the server must send it, and the screen must read it rather
than deciding again.
"""

import os
import re
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREEN = os.path.join(APP, "public", "js", "work-actuals.js")
API = os.path.join(APP, "api", "actuals.py")

FLAG = "is_task_worker"


def screen():
	with open(SCREEN) as handle:
		return handle.read()


def api():
	with open(API) as handle:
		return handle.read()


class TestTheScreenReadsRatherThanDecides(unittest.TestCase):
	def setUp(self):
		self.src = screen()
		at = self.src.index("function isTaskWorker(")
		self.body = self.src[at:self.src.index("\n", at)]

	def test_the_test_reads_the_flag(self):
		self.assertIn(FLAG, self.body)

	def test_it_no_longer_decides_from_employment_type(self):
		"""The whole bug in one line: a field the server stopped trusting."""
		self.assertNotIn("employment_type", self.body)
		self.assertNotIn("Task Worker", self.body)

	def test_no_caller_passes_a_field_instead_of_the_row(self):
		"""isTaskWorker(w.employment_type) type-checks and is always wrong now."""
		for call in re.findall(r"isTaskWorker\(([^)]*)\)", self.src):
			if call.startswith("row"):
				continue
			self.assertNotIn(".", call,
				"isTaskWorker takes the row, not one of its fields: got %r" % call)

	def test_the_release_button_is_gated_on_it(self):
		"""It is the gate this was reported through, so name it."""
		self.assertRegex(self.src, r"var perm=!isTaskWorker\(w\);")
		self.assertRegex(self.src, r"var canSub = !perm && !isLeft && !locked;")
		self.assertIn("relbtn", self.src)


class TestTheServerSendsIt(unittest.TestCase):
	def setUp(self):
		self.src = api()

	def test_the_roster_carries_it(self):
		self.assertRegex(self.src, r'w\["%s"\]\s*=' % FLAG)

	def test_the_day_panel_carries_it(self):
		"""The day panel lists people who have since left the roster, so the
		roster's answer cannot speak for them -- it needs its own."""
		self.assertRegex(self.src, r'"%s":\s*r\.tw' % FLAG)

	def test_both_answer_from_settings(self):
		"""TW_MATCH is the settings-driven test payment uses. Anything else here
		would put the disagreement back, one layer down."""
		self.assertRegex(self.src, r'IN %\(names\)s AND """ \+ TW_MATCH')
		self.assertRegex(self.src, r'CASE WHEN """ \+ TW_MATCH \+ """ THEN 1 ELSE 0 END tw')

	def test_the_match_is_sql_not_a_bound_parameter(self):
		"""TW_MATCH is a fragment of SQL. Passed as a parameter it would be
		quoted into a string and the CASE would be constant -- caught in review,
		kept here because it costs one line."""
		day_query = self.src[self.src.index("dayw[k]") - 2000:self.src.index("dayw[k]")]
		self.assertNotIn("CASE WHEN %s THEN", day_query)
