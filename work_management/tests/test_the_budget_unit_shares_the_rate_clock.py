"""A budget line's unit must come from the same clock as its rate.

`save` built each master plan activity from two reads that ran on different
clocks:

    row.rate  <- `tabWork Task Rate`, the row whose window covers the plan's
                 own period_from -- as the rate WAS
    row.uom   <- Task.custom_uom -- as the unit IS

That is coherent only while a task's unit never changes. It changes here: on
2026-09-09 Kaitet converted a batch of piece-rate tasks to hourly, closing the
old rate row on 09-08 and opening `Hour @ 48.375` on 09-09.

    TASK-2026-00159  Loading crates   2026-05-22..09-08  2.67    /Crate
                                      2026-09-09..       48.375  /Hour

A plan whose period predates the switch then stores the OLD rate against the
NEW unit, and the quantity -- typed in the new unit -- is multiplied by a price
per crate. WMMP-00011 (31 Aug - 4 Sep, raised 10 Sep, backdated across the
switch) booked:

    456 hours x 2.67/Crate  =     1,217.52   instead of   22,059.00
    880 hours x 1.935/Kg    =     1,702.80   instead of   42,570.00
  1,328 hours x 2.58/Tree   =     3,426.24   instead of   64,242.00

and, the same fault running the other way, 144 hours x 193.50/Nos = 27,864.00
where the work is worth 6,966.00. Across the site this was 13 rows on 4 plans,
KES 195,425.11 net understated -- and WMMP-00040 (Vale) booking 387/Day against
312 *hours* for 120,744.00 against a true 15,093.00.

Pay never sees this: wages come off the planner, which reads `Task.custom_rate`
and `Task.custom_uom` together, both live (wm_planner: `tinfo`). Only the
budget could hold the mismatched pair. What it costs is the budget -- and then
the planner's own cap, which prices at the live rate and compares against a
line costed at the old one, so `Loading crates` refuses every request past
about 25 of its 456 budgeted hours.

`tabWork Task Rate` carries its own `uom`, written by whoever set the rate. So
the fix is not a second dated lookup but one read: take the unit from the row
the rate came from. One row, one clock, and the pair cannot drift apart again.

This reads the mirror source, because the app's copy is generated and the fault
is which column a query selects -- something no unit test on the ported module
would notice.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_the_budget_unit_shares_the_rate_clock -v
"""

import os
import re
import unittest

from work_management.tests import mirror
from work_management.tests.mirror import SERVER_SCRIPTS as MIRROR

SCRIPT = "wm_masterplan"

# The save path: where a plan's activity rows are built and frozen.
OPENS = 'elif action == "save":'


def source(script):
	with open(os.path.join(MIRROR, script + ".py")) as handle:
		return handle.read()


def block_of(text, opens):
	"""The action block starting at `opens` and ending at the next one."""
	start = text.index(opens)
	nxt = re.search(r"^elif action ==", text[start + len(opens):], re.M)
	end = start + len(opens) + (nxt.start() if nxt else len(text))
	return text[start:end]


def rate_query(block):
	"""The `tabWork Task Rate` SELECT in this block, from SELECT to FROM."""
	at = block.index("tabWork Task Rate")
	head = block.rindex("SELECT", 0, at)
	return block[head:at]


class TestTheMirrorIsCheckedOut(unittest.TestCase):
	def setUp(self):
		if not mirror.present():
			self.skipTest("mirror not present")


class TestTheBudgetUnitSharesTheRateClock(TestTheMirrorIsCheckedOut):
	def test_the_rate_row_is_asked_for_its_unit(self):
		"""The dated rate lookup must select `uom` beside `rate` -- that column
		is the only unit that belongs to the same moment as the price."""
		block = block_of(source(SCRIPT), OPENS)
		select = rate_query(block)
		self.assertRegex(select, r"\buom\b",
			"the master plan's dated rate lookup selects a rate without its "
			"unit, so the unit has to come from somewhere else and the two "
			"drift apart across a unit change")

	def test_the_stored_unit_does_not_come_from_the_live_task(self):
		"""`row.uom` must not be read off Task.custom_uom: that is today's
		unit, and the rate beside it is the rate as of the plan's period."""
		block = block_of(source(SCRIPT), OPENS)
		assign = re.search(r"^\s*row\.uom\s*=\s*(.+)$", block, re.M)
		self.assertIsNotNone(assign, "the save path no longer assigns row.uom")
		self.assertNotIn("custom_uom", assign.group(1),
			"row.uom is stamped from the live Task while row.rate is the rate "
			"in force at period_from -- a task whose unit changed after the "
			"period stores an old price against a new unit")

	def test_the_live_unit_survives_only_where_the_live_rate_does(self):
		"""With no dated rate row the code already falls back to
		Task.custom_rate; the unit must fall back in the same branch and
		nowhere else, or the fallback pair drifts instead."""
		block = block_of(source(SCRIPT), OPENS)
		self.assertEqual(block.count("custom_uom"), block.count("custom_rate"),
			"custom_uom and custom_rate are read a different number of times "
			"in the save path -- the live unit and the live rate are one "
			"fallback and belong together")


class TestThePickerShowsThePairThatLands(TestTheMirrorIsCheckedOut):
	"""`pickable_tasks` is what the plan form shows before a save: its comment
	promises "the number shown here is the number that lands". It had the same
	split -- the dated rate beside the live unit -- so Granular fertilizer
	application showed 48.375 (the Hour rate) against `kgs`, and 200 kgs
	previewed at 9,675.00."""

	OPENS = 'elif action == "pickable_tasks":'

	def test_the_rate_row_is_asked_for_its_unit(self):
		select = rate_query(block_of(source(SCRIPT), self.OPENS))
		self.assertRegex(select, r"\buom\b",
			"the picker's dated rate lookup selects a rate without its unit")

	def test_the_shown_unit_does_not_come_from_the_live_task(self):
		block = block_of(source(SCRIPT), self.OPENS)
		assign = re.search(r'"uom":\s*([^,}]+)', block)
		self.assertIsNotNone(assign, "the picker no longer sends a uom")
		self.assertNotIn("custom_uom", assign.group(1),
			"the picker shows the live Task unit beside the rate in force on "
			"period_from")


class TestTheDriftCheckComparesOnePair(TestTheMirrorIsCheckedOut):
	"""`get` reports rate drift by comparing the budget line with the rate in
	force today. Its unit must be today's rate row's unit too, or a line saved
	with the row's unit is reported as a unit change it never had."""

	OPENS = 'elif action == "get":'

	def test_the_live_rate_row_is_asked_for_its_unit(self):
		select = rate_query(block_of(source(SCRIPT), self.OPENS))
		self.assertRegex(select, r"\buom\b",
			"the drift check reads today's rate without today's unit")

	def test_the_live_unit_is_not_read_off_the_task(self):
		block = block_of(source(SCRIPT), self.OPENS)
		self.assertNotIn("custom_uom", block,
			"the drift check compares against Task.custom_uom, not the unit "
			"of the rate row it compares against")


if __name__ == "__main__":
	unittest.main()
