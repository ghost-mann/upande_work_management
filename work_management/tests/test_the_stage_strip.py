"""The pipeline strip: five stages, four hand-offs, one scope.

A glance view of where work is: Master Plan -> Planned Tasks -> Worker
Assignment -> Actual Done -> Paid Work, with the number waiting at each hand-off
on the rail between.

Two decisions are worth writing down, because both were nearly made the other
way.

SCOPE. The counts come from `charts`, not `dash`. `dash` takes no parameters at
all -- its state_counts() is a bare GROUP BY over each table -- so a strip fed
from there could not follow a filter, and the strip sits directly beneath the
farm and date controls of the card it lives in. A number under a filter that
ignores the filter is a lie the reader has no way to spot.

LABELS. The endpoint sends keys and counts; the screen supplies the words. This
is the same split that "What the numbers are doing" got wrong for months -- it
shipped `ac.task` in a field called `label`, and the chart printed
TASK-2026-00103 because the server had already claimed to have resolved it.
Identity server-side, wording client-side.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_the_stage_strip -v
"""

import inspect
import os
import re
import unittest

JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public", "js")

STAGES = ("master_plan", "planned", "assigned", "actual", "paid")
HANDOFFS = ("to_planned", "to_assigned", "to_actual", "to_paid")


def endpoint():
	from work_management.api import dashboard

	return inspect.getsource(dashboard.wm_dashboard)


def charts_block():
	"""The charts action only -- so a match in `dash` cannot satisfy these."""
	text = endpoint()
	start = text.index('elif action == "charts"')
	rest = text[start + 1:]
	nxt = re.search(r"\n    elif action == ", rest)
	return text[start:start + 1 + nxt.start()] if nxt else text[start:]


def screen():
	with open(os.path.join(JS, "work-management-dashboard.js")) as handle:
		return handle.read()


class TestTheEndpointServesTheStages(unittest.TestCase):
	def setUp(self):
		self.block = charts_block()

	def test_every_stage_is_counted(self):
		for key in STAGES:
			with self.subTest(stage=key):
				self.assertIn('"' + key + '"', self.block)

	def test_every_hand_off_is_counted(self):
		"""The dots are the point -- without them the strip says how much passed
		but never where it is stuck."""
		for key in HANDOFFS:
			with self.subTest(handoff=key):
				self.assertIn('"' + key + '"', self.block)

	def test_it_is_served_from_charts_not_dash(self):
		self.assertIn('out["stages"]', self.block)
		self.assertIn('out["stage_waiting"]', self.block)

	def test_the_counts_respect_the_cards_filters(self):
		"""cfarm/cfrom/cto are what the farm and date controls above it send."""
		strip = self.block[self.block.index("stage_count"):]
		for token in ("cfarm", "cfrom", "cto"):
			with self.subTest(token=token):
				self.assertIn(token, strip)

	def test_the_window_is_an_overlap_not_a_single_column(self):
		"""Each stage is its own doctype with its own dates. A plan running
		31 Aug - 4 Sep belongs to any window touching those days, so comparing
		one column would drop work that straddles the edge."""
		strip = self.block[self.block.index("stage_count"):]
		self.assertIn(">=", strip)
		self.assertIn("<=", strip)

	def test_the_endpoint_sends_no_wording(self):
		"""Keys and counts only -- the screen says what they are called."""
		strip = self.block[self.block.index('out["stages"]'):][:600]
		for word in ("Master Plan", "Worker Assignment", "Paid Work"):
			with self.subTest(word=word):
				self.assertNotIn(word, strip)


class TestTheScreenDrawsIt(unittest.TestCase):
	def setUp(self):
		self.src = screen()

	def test_it_names_all_five_stages(self):
		for word in ("Master Plan", "Planned Tasks", "Worker Assignment",
		             "Actual Done", "Paid Work"):
			with self.subTest(label=word):
				self.assertIn(word, self.src)

	def test_it_reads_the_counts_rather_than_recomputing(self):
		self.assertIn("stages", self.src)
		self.assertIn("stage_waiting", self.src)

	def test_it_survives_an_endpoint_that_says_nothing(self):
		"""Every other section on this screen opens on a slow or failed call."""
		strip = self.src[self.src.index("function stageStrip"):][:900]
		self.assertRegex(strip, r"\|\|\s*\{\}")


if __name__ == "__main__":
	unittest.main()
