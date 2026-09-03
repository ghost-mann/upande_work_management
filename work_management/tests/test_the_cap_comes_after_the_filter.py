"""A row cap belongs after the filtering, not on the fetch.

Both work screens fetched a fixed 200 rows and *then* threw most of them away,
so the cap was spent on rows nobody was ever shown.

On the live site that meant:

    actuals screen    1,497 Assigned assignments -> 200 fetched -> 45 dropped as
                      closed early, 115 as already fully recorded -> 40 offered.
                      The other 1,297 were never read, and the 1,232 actuals
                      documents hanging off them could not be reached at all --
                      which is how three weeks of migrated work looked missing.

    assigner picker   of the 200 newest approved plans, 182 were already tied to
                      a live assignment, so 18 were offered, while 114 genuinely
                      unassigned plans sat outside the window unassignable.

Ordering made it sharper: both fetch `approval_date desc`, so migrating three
weeks of older work moved the window from 20 August to 26 August and displaced
130 assignments people were still working on. Nothing was lost -- it just could
not be seen, which from a farm manager's chair is the same thing.

The assigner picker also carried a worse one. `assigned` builds the map of which
plans are already taken, and it was capped at 500 against 1,543 live
assignments -- with no order_by, an arbitrary 500. A plan missing from that map
reads as free, so the same plan could be assigned twice; 1,022 were exposed to
that. A query used for membership has to be complete, and a cap on it is not a
display choice.

So: fetch, filter, *then* cap. This reads the mirror sources and asserts it,
because the app's ported copies are generated and a cap here is a runtime
behaviour no unit test on them would notice.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_the_cap_comes_after_the_filter -v
"""

import os
import re
import unittest

MIRROR = "/home/austin/vscodeProjects/kaitet-work-management/server_scripts"

# The two blocks that had the fault: script, the action guard that opens the
# block, and the fetch whose rows are filtered afterwards.
BLOCKS = (
	("wm_actuals", 'elif action == "act_assigned":', "Work Management Assigner"),
	("wm_assigner", 'elif action == "a_approved_planners":', "Work Management Planner"),
)

# Queries built to answer "is this one taken / present", where a cap does not
# trim a display, it invents wrong answers.
MEMBERSHIP = (
	("wm_assigner", 'elif action == "a_approved_planners":', "Work Management Assigner"),
)


def source(script):
	with open(os.path.join(MIRROR, script + ".py")) as handle:
		return handle.read()


def block_of(text, opens):
	"""The action block starting at `opens` and ending at the next one.

	Server Script actions are a flat if/elif chain at column zero, so the next
	`elif action ==` at column zero is the end of this one."""
	start = text.index(opens)
	nxt = re.search(r"^elif action ==", text[start + len(opens):], re.M)
	end = start + len(opens) + (nxt.start() if nxt else len(text))
	return text[start:end]


def fetch_call(block, doctype):
	"""The get_all call against `doctype` in this block, whole, brackets balanced."""
	needle = 'get_all("%s"' % doctype
	at = block.index(needle)
	depth, i = 0, at
	while i < len(block):
		if block[i] == "(":
			depth += 1
		elif block[i] == ")":
			depth -= 1
			if depth == 0:
				return block[at:i + 1]
		i += 1
	raise AssertionError("unbalanced call for %s" % doctype)


class TestTheMirrorIsCheckedOut(unittest.TestCase):
	def setUp(self):
		if not os.path.isdir(MIRROR):
			self.skipTest("mirror not present")


class TestTheFetchIsNotCapped(TestTheMirrorIsCheckedOut):
	def test_the_filtered_fetch_carries_no_limit(self):
		"""Rows this fetch returns are dropped further down, so a cap here is
		spent on rows nobody sees."""
		for script, opens, doctype in BLOCKS:
			block = block_of(source(script), opens)
			call = fetch_call(block, doctype)
			with self.subTest(script=script, doctype=doctype):
				self.assertNotRegex(call, r"\blimit\s*=\s*\d+",
					"%s fetches %s with a row cap and filters afterwards -- the cap "
					"belongs after the filter" % (script, doctype))
				self.assertNotRegex(call, r"\blimit_page_length\s*=\s*[1-9]",
					"%s caps the %s fetch by page length" % (script, doctype))

	def test_the_membership_query_is_complete(self):
		"""A map of what is already taken must cover everything, or the things
		it misses read as available."""
		for script, opens, doctype in MEMBERSHIP:
			block = block_of(source(script), opens)
			call = fetch_call(block, doctype)
			with self.subTest(script=script, doctype=doctype):
				self.assertNotRegex(call, r"\blimit\s*=\s*\d+",
					"%s builds its already-taken map from a capped query, so a plan "
					"beyond the cap reads as free and can be assigned twice" % script)


class TestTheCapStillExists(TestTheMirrorIsCheckedOut):
	"""Removing the cap outright is the other way to get this wrong: the screens
	would render every row. The budget must survive, just later."""

	def test_each_block_declares_how_many_it_shows(self):
		# re.M matters: the assignment is indented inside the block, not at the
		# start of the string assertRegex would otherwise anchor to.
		declares = re.compile(r"^\s+SHOWN\s*=\s*\d+", re.M)
		for script, opens, _ in BLOCKS:
			block = block_of(source(script), opens)
			with self.subTest(script=script):
				self.assertIsNotNone(declares.search(block), "%s declares no SHOWN" % script)

	def test_the_cap_is_applied_to_the_filtered_rows(self):
		for script, opens, _ in BLOCKS:
			block = block_of(source(script), opens)
			with self.subTest(script=script):
				self.assertIn("rows[:SHOWN]", block,
					"%s never applies SHOWN to the rows that survived the filter" % script)

	def test_the_cap_comes_after_the_last_row_is_dropped(self):
		"""Order within the block, which is the whole point: every `continue`
		that discards a row must run before the slice."""
		for script, opens, _ in BLOCKS:
			block = block_of(source(script), opens)
			slice_at = block.index("rows[:SHOWN]")
			drops = [m.start() for m in re.finditer(r"^\s+continue$", block, re.M)]
			with self.subTest(script=script):
				self.assertTrue(drops, "%s drops no rows; has the filter gone?" % script)
				self.assertLess(max(drops), slice_at,
					"%s slices to SHOWN before it has finished discarding rows" % script)

	def test_the_rows_are_appended_before_they_are_capped(self):
		for script, opens, _ in BLOCKS:
			block = block_of(source(script), opens)
			with self.subTest(script=script):
				self.assertLess(block.index("rows.append("), block.index("rows[:SHOWN]"))


if __name__ == "__main__":
	unittest.main()
