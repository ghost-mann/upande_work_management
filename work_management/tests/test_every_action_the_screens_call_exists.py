"""A screen must not call an action nothing serves.

The assigner's crew screen has offered to release workers for a while:
checkboxes down the roster, a date, a Confirm button, gated to FM/HR/GM. There
was no `a_release` action in the server script, so ticking somebody and
confirming answered

    {"error": "unknown action: a_release"}

on live. The control looked real and could not work -- the same shape of fault
as the On switch against each approval step, which looked usable and stranded
documents, and the row caps that showed 40 of 1,497 assignments.

Nothing could have caught it. The JS is not executed by any test, the server
script has no idea who calls it, and both halves are individually correct: the
screen sends a well-formed request and the script correctly reports an action it
does not know.

So this reads both sides. Every `action:"..."` any screen sends must be handled
by at least one mirror script -- not necessarily its own, because a screen may
reach another's (the planner and the three others fetch wm_dashboard's
`task_names`, and the planner fetches wm_rates' `rate_meta`).

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_every_action_the_screens_call_exists -v
"""

import glob
import os
import re
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(APP, "public", "js")
from work_management.tests.mirror import SERVER_SCRIPTS as MIRROR

#: `action:"a_release"` and `action: "a_release"`, single or double quoted.
CALLS = re.compile(r"""action\s*:\s*["']([a-zA-Z0-9_]+)["']""")

#: `action == "a_release"` on the server side.
HANDLES = re.compile(r"""action\s*==\s*["']([a-zA-Z0-9_]+)["']""")

#: Actions a screen builds by name rather than writing literally. Each needs a
#: reason, so this list cannot quietly become the place awkward cases go.
DYNAMIC = {
	# work-planner.js picks the approve/reject action for the stage in hand
}


def actions_called():
	"""{action: [screens that send it]}"""
	found = {}
	for path in sorted(glob.glob(os.path.join(JS, "*.js"))):
		with open(path) as handle:
			text = handle.read()
		for name in CALLS.findall(text):
			found.setdefault(name, []).append(os.path.basename(path))
	return found


def actions_served():
	"""Every action any mirror script handles."""
	served = set()
	for path in glob.glob(os.path.join(MIRROR, "*.py")):
		with open(path) as handle:
			served.update(HANDLES.findall(handle.read()))
	return served


class TestTheMirrorIsCheckedOut(unittest.TestCase):
	def setUp(self):
		if not os.path.isdir(MIRROR):
			self.skipTest("mirror not present")


class TestEveryActionCalledIsServed(TestTheMirrorIsCheckedOut):
	def test_no_screen_calls_an_action_nothing_handles(self):
		served = actions_served()
		orphans = []
		for name, screens in sorted(actions_called().items()):
			if name in served or name in DYNAMIC:
				continue
			orphans.append("%s -- sent by %s, handled by nothing"
				% (name, ", ".join(sorted(set(screens)))))
		self.assertEqual(orphans, [], "\n".join(
			["a screen sends an action no server script handles:"] + orphans))

	def test_the_release_action_in_particular(self):
		"""Named, because this is the one that was broken on live: the control
		existed, the action did not."""
		self.assertIn("a_release", actions_served())

	def test_the_check_can_actually_see_something(self):
		"""A regex that matched nothing would pass this file silently."""
		called = actions_called()
		self.assertGreater(len(called), 40,
			"only %d actions found across the screens -- the call pattern has "
			"probably stopped matching" % len(called))
		self.assertGreater(len(actions_served()), 40,
			"almost no server actions found -- the handler pattern has probably "
			"stopped matching")


class TestTheReleaseContractMatches(TestTheMirrorIsCheckedOut):
	"""Existing and served is not enough: it has to accept what the screen sends.

	The crew screen has always sent `employees` (comma-separated) and
	`release_date`. An action reading `employee` and `left_date` would exist, be
	served, and still fail on every call.
	"""

	def setUp(self):
		super().setUp()
		with open(os.path.join(MIRROR, "wm_assigner.py")) as handle:
			text = handle.read()
		at = text.index('elif action == "a_release":')
		nxt = re.search(r"^elif action ==", text[at + 30:], re.M)
		self.block = text[at:at + 30 + (nxt.start() if nxt else len(text))]

	def test_it_reads_the_arguments_the_screen_sends(self):
		for arg in ('"employees"', '"release_date"'):
			with self.subTest(arg=arg):
				self.assertIn(arg, self.block,
					"a_release does not read %s, which the crew screen sends" % arg)

	def test_it_returns_what_the_screen_reads_back(self):
		"""The screen prints `r.released_count` and `r.active_count`."""
		for key in ('"released_count"', '"active_count"'):
			with self.subTest(key=key):
				self.assertIn(key, self.block)

	def test_it_enforces_the_role_gate_itself(self):
		"""The screen hides the controls from everybody else. A gate that lives
		only in the browser is not a gate."""
		self.assertIn("Farm Manager", self.block)
		self.assertRegex(self.block, r"frappe\.get_roles")

	def test_it_only_releases_from_an_approved_assignment(self):
		self.assertIn("Assigned", self.block)

	def test_it_keeps_what_was_recorded(self):
		"""The whole premise: releasing must not touch the work already recorded.
		It reports it back rather than only promising."""
		self.assertIn("kept_rows", self.block)
		self.assertIn("Work Actuals Employee", self.block)


if __name__ == "__main__":
	unittest.main()
