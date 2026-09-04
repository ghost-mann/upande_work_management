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

from work_management.tests.mirror import SERVER_SCRIPTS as MIRROR

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


class TestTheCapCannotHideYourOwnWork(TestTheMirrorIsCheckedOut):
	"""A cap may shorten the list. It may not decide what somebody can finish.

	Moving the cap off the fetch fixed the arithmetic and left the shape: 1,497
	Assigned assignments, 200 offered, 1,297 not. Sitting in that remainder on
	kaitet-group were 19 draft actuals belonging to six clerks -- 18 of them cut
	purely by the cap, at ranks 238 to 1,474. Their entries were intact and
	unreachable from the picker, which from a clerk's chair is the same complaint
	as before, for a different reason. Raising 200 to 500 would only move where
	the cliff falls.

	So the caller's own unfinished work is pinned ahead of the cap. It is the one
	class of row where "not shown" is never merely clutter: somebody typed it,
	means to come back to it, and has no other way in from this screen. Draft and
	Rejected only -- the two states work-actuals.js draws an "Edit" link for.

	This does not touch the two drops above it. An approver who closed a plan
	early meant it, and a plan already fully recorded is genuinely done; both stay
	dropped, and a draft stranded on one is reachable from My actuals -> Edit,
	which goes straight to the assignment by name.
	"""

	BLOCK = ("wm_actuals", 'elif action == "act_assigned":')

	def block(self):
		script, opens = self.BLOCK
		return block_of(source(script), opens)

	def test_it_asks_which_assignments_this_caller_has_started(self):
		block = self.block()
		self.assertIn("entered_by", block,
			"act_assigned never asks which rows are the caller's own")
		self.assertIn("frappe.session.user", block,
			"act_assigned asks about entered_by but not about who is asking")

	def test_only_the_resumable_states_are_pinned(self):
		"""Pinning a CONFIRMED entry would put finished work back in the picker."""
		block = self.block()
		guard = block[block.index("entered_by"):]
		self.assertIn("'Draft'", guard)
		self.assertIn("'Rejected'", guard)
		self.assertNotIn("'CONFIRMED'", guard[:guard.index("rows[:SHOWN]")])

	def test_the_pinning_happens_before_the_cap(self):
		"""After the drops, before the slice -- otherwise it pins nothing."""
		block = self.block()
		self.assertLess(block.index("entered_by"), block.index("rows[:SHOWN]"),
			"the caller's own rows are identified after the cap has already cut them")

	def test_the_cap_is_still_applied_afterwards(self):
		"""Pinning must not become a way to render every row."""
		block = self.block()
		self.assertIn("rows[:SHOWN]", block)
		self.assertLess(block.index("entered_by"), block.index("rows[:SHOWN]"))

	def test_your_own_draft_does_not_hide_its_own_assignment(self):
		"""The drop that actually stranded people, and the subtler half of this.

		`recorded` is confirmed PLUS pending, and pending counts Draft. So a clerk
		who enters a draft meeting the plan target trips `fulfilled_done` with their
		own unfinished entry, and the assignment leaves the picker -- taking the
		draft with it. 16 of the 19 stranded drafts on kaitet-group were this, not
		the cap; the plan target was met only by counting the very draft that could
		no longer be reached.

		Hiding a fully-recorded assignment is clutter control. An assignment the
		caller has unfinished work on is not clutter, so the drop has to ask whose
		work it is.
		"""
		block = self.block()
		guard = re.search(r'if a\["fulfilled_done"\][^\n]*', block)
		self.assertIsNotNone(guard, "the fulfilled-done drop has gone")
		self.assertIn("mine", guard.group(0),
			"the fulfilled-done drop discards the caller's own unfinished work: "
			+ guard.group(0).strip())

	def test_the_caller_is_known_before_the_rows_are_filtered(self):
		"""Pinning after the drop would rescue only the capped ones -- which is
		exactly the half-fix this test exists to stop coming back."""
		block = self.block()
		self.assertLess(block.index("entered_by"), block.index('if a["fulfilled_done"]'),
			"the caller's own rows are identified after the drop has already cut them")


if __name__ == "__main__":
	unittest.main()
