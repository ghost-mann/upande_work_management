"""No screen writes an approval state by name.

This is the guard on the substitution, and it is here because this codebase has
already been bitten by exactly this shape of change: the same query appeared at
four indentations, a pattern replacement caught three of them, and the fourth was
found only by a test that checked every site rather than the ones somebody
remembered. The chain substitution has the same hazard at a larger scale.

A state written by name is a state that ignores the configuration. So every write
of `workflow_state` in the four screens that advance a chain must go through
`STAGE_NEXT` or `STAGE_STATE`, with three deliberate exceptions:

  the reject states     Rejected and Cancelled. Rejecting is not a step and
                        cannot be switched off, and it is how a document parked
                        in a retired step gets out of it.
  the draft state       Draft. Where a document sits before it enters the chain,
                        and where an edit returns it.
  the terminal states   Approved, Assigned, CONFIRMED, Paid. Not steps either --
                        `CHAIN_ENDS` fixes them, and switching a step off changes
                        which step *reaches* the terminal, never what it is. The
                        one literal terminal write left is the GM's early close,
                        an explicit override straight to the end.

The exceptions are named rather than pattern-matched, so widening them is a
deliberate act with a reason attached.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_no_hardcoded_chain -v
"""

import os
import re
import unittest

from work_management import approvals

MIRROR = "/home/austin/vscodeProjects/kaitet-work-management/server_scripts"

# The screens that advance a chain. wm_payment is not among them: its only step
# is Payment: Accounts, which is required and so can never be switched off, and
# converting it would be risk without capability.
ADVANCING = ("wm_planner", "wm_assigner", "wm_actuals", "wm_masterplan")

REJECT_STATES = {ends["reject"] for ends in approvals.CHAIN_ENDS.values()}
TERMINAL_STATES = {ends["terminal"][0] for ends in approvals.CHAIN_ENDS.values()}
DRAFT_STATES = {"Draft"}
ALLOWED_LITERALS = REJECT_STATES | TERMINAL_STATES | DRAFT_STATES

# Every state the shipped chain knows. Used to tell a write from a field list:
# `["workflow_state", "farm"]` and `set_value(dt, n, "workflow_state", "Pending GM")`
# look alike to a regex, and `farm` is not a state while `Pending GM` is. Checking
# against the catalogue is what separates them, and it is the right check anyway --
# a missed chain literal is by definition one of these names.
KNOWN_STATES = (
	{stage.state for stage in approvals.CATALOGUE if stage.state}
	| REJECT_STATES | TERMINAL_STATES | DRAFT_STATES
)
# What must never be written by name: the states somebody waits in.
FORBIDDEN_LITERALS = KNOWN_STATES - ALLOWED_LITERALS

# `frappe.db.set_value(dt, name, "workflow_state", <value>)` and the dict form
# `{"workflow_state": <value>}`, capturing the value written.
WRITES = re.compile(r'"workflow_state"\s*[,:]\s*("(?P<literal>[^"]*)"|(?P<expr>STAGE_[A-Z_]+\[[^\]]+\]))')


def source(slug):
	with open(os.path.join(MIRROR, slug + ".py")) as handle:
		return handle.read()


def literal_writes(text):
	"""State names written by name, excluding the allowed exceptions."""
	out = []
	for match in WRITES.finditer(text):
		literal = match.group("literal")
		if literal is None:
			continue
		if literal in FORBIDDEN_LITERALS:
			out.append(literal)
	return out


class TestTheMirrorIsCheckedOut(unittest.TestCase):
	def test_every_advancing_screen_is_there(self):
		if not os.path.isdir(MIRROR):
			self.skipTest("mirror not present")
		for slug in ADVANCING:
			self.assertTrue(os.path.exists(os.path.join(MIRROR, slug + ".py")), slug)


class TestNoScreenNamesAChainState(unittest.TestCase):
	def setUp(self):
		if not os.path.isdir(MIRROR):
			self.skipTest("mirror not present")

	def test_no_literal_chain_state_is_written(self):
		offenders = []
		for slug in ADVANCING:
			for literal in literal_writes(source(slug)):
				offenders.append("%s writes workflow_state = %r by name" % (slug, literal))
		self.assertEqual(offenders, [], "\n".join(offenders))

	def test_each_screen_does_write_through_the_chain(self):
		"""The other direction: a screen with no STAGE_NEXT write has not been
		converted at all, and would pass the test above by doing nothing."""
		for slug in ADVANCING:
			with self.subTest(script=slug):
				self.assertIn("STAGE_NEXT[", source(slug))

	def test_each_screen_guards_on_the_configured_state(self):
		for slug in ADVANCING:
			with self.subTest(script=slug):
				self.assertIn("STAGE_STATE[", source(slug))

	def test_each_screen_refuses_a_step_that_is_off(self):
		for slug in ADVANCING:
			with self.subTest(script=slug):
				self.assertIn("STAGE_ON[", source(slug))


class TestTheStageKeysAreReal(unittest.TestCase):
	"""A typo in a stage key would read as None from the map and write a null
	state -- silently, since Python is happy to look up a missing key with
	`.get` semantics elsewhere in these files."""

	KEY = re.compile(r'STAGE_(?:NEXT|STATE|ON)\["([a-z_]+)"\]')

	def setUp(self):
		if not os.path.isdir(MIRROR):
			self.skipTest("mirror not present")
		self.shipped = {stage.key for stage in approvals.CATALOGUE}

	def test_every_key_referenced_is_a_shipped_step(self):
		for slug in ADVANCING:
			for key in set(self.KEY.findall(source(slug))):
				with self.subTest(script=slug, key=key):
					self.assertIn(key, self.shipped)

	def test_every_key_referenced_is_in_that_scripts_own_fallback(self):
		"""The fallback is what live runs on. A key referenced but missing from it
		would be a KeyError on the live site and nowhere else -- the same shape as
		the NameError that took the Master Plan screen down."""
		for slug in ADVANCING:
			text = source(slug)
			fallback = text[text.index("STAGE_ROWS = ["):text.index("STAGE_STATE = {}")]
			for key in set(self.KEY.findall(text)):
				with self.subTest(script=slug, key=key):
					self.assertIn('"%s"' % key, fallback)


class TestTheReadFiltersStillCoverEveryState(unittest.TestCase):
	"""Read filters keep naming states literally, and that is deliberate.

	They already name every state the shipped chain has, so they are the permissive
	superset the design calls for: switching a step off leaves its state listed and
	simply matching nothing. Converting a hundred and fifty SQL sites would have
	been risk without behaviour.

	That holds only while the filters are a superset. This test is what makes the
	decision safe -- add a step with a new state and it fails here, pointing at the
	filters that need it.
	"""

	def setUp(self):
		if not os.path.isdir(MIRROR):
			self.skipTest("mirror not present")

	def test_every_configured_state_appears_in_its_screens_filters(self):
		screens = {
			"wm_planner": "Work Management Planner",
			"wm_assigner": "Work Management Assigner",
			"wm_actuals": "Work Management Actuals",
			"wm_masterplan": "Work Management Master Plan",
		}
		missing = []
		for slug, doctype in screens.items():
			text = source(slug)
			states = approvals.pipeline_states(settings=None, document_type=doctype)
			for state in states["all"]:
				if state and ('"%s"' % state) not in text and ("'%s'" % state) not in text:
					missing.append("%s never mentions %r" % (slug, state))
		self.assertEqual(missing, [], "\n".join(missing))


if __name__ == "__main__":
	unittest.main()
