"""A farm may hold two approved budgets over the same days, when a site says so.

Raising an overlapping master plan already worked -- save reports a
`clash_warning` and writes the plan. Approving one did not: both GM paths
refused, because one budget in force per farm per day was what made "which
ceiling does this request draw against" answerable at all.

The request answers it itself now. It carries the plan it drew down, the planner
lists every approved plan covering the dates, and where two match and none is
named it returns the candidates so the screen can ask rather than guess --
`resolve_master_plan()`, which is unit-tested next door.

So the refusal is a site's decision rather than an invariant, and this is the
switch. Off by default: a site that has always run one budget per period keeps
doing so, and no approval already in flight changes meaning underneath anyone.

The clash is still REPORTED when the switch is on. Raising the same plan twice
by mistake looks identical to raising a deliberate second one, and the approver
is the last person who can cheaply tell them apart.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_concurrent_master_plans -v
"""

import json
import os
import re
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(APP, "work_management", "doctype",
	"work_management_settings", "work_management_settings.json")
MIRROR = "/home/austin/vscodeProjects/kaitet-work-management"
SCRIPT = os.path.join(MIRROR, "server_scripts", "wm_masterplan.py")
PORT = os.path.join(MIRROR, "port_app.py")

FIELD = "allow_concurrent_master_plans"
CONST = "ALLOW_CONCURRENT_PLANS"
KEY = "allow_concurrent_master_plans"


def settings_doc():
	with open(SETTINGS) as handle:
		return json.load(handle)


def script():
	with open(SCRIPT) as handle:
		return handle.read()


class TestTheSwitchExists(unittest.TestCase):
	def setUp(self):
		self.fields = {f["fieldname"]: f for f in settings_doc().get("fields", [])}

	def test_settings_carries_the_field(self):
		self.assertIn(FIELD, self.fields)

	def test_it_is_a_checkbox(self):
		self.assertEqual(self.fields[FIELD]["fieldtype"], "Check")

	def test_it_is_off_by_default(self):
		"""On would change what approval means on every existing site, silently."""
		self.assertIn(str(self.fields[FIELD].get("default") or "0"), ("0", "None"))

	def test_it_is_in_the_field_order(self):
		"""A field absent from field_order exists in the table and not on the form."""
		self.assertIn(FIELD, settings_doc().get("field_order", []))

	def test_its_label_says_what_it_does(self):
		label = self.fields[FIELD].get("label") or ""
		self.assertTrue(label, "the field needs a label; the fieldname is not the UI")
		self.assertRegex(label.lower(), r"more than one|concurrent|two",
			"the label should say a farm may hold more than one plan at a time")


class TestItReachesTheScreens(unittest.TestCase):
	"""Settings the screens cannot read are decoration."""

	def test_get_config_carries_it(self):
		from work_management.api import config
		import inspect

		self.assertIn(KEY, inspect.getsource(config))

	def test_the_port_rebuilds_it_from_config(self):
		with open(PORT) as handle:
			text = handle.read()
		self.assertRegex(text, r"%s = _cfg\[\"%s\"\]" % (CONST, KEY),
			"port_app.py must assign %s from get_config()" % CONST)

	def test_the_port_strips_the_mirror_literal(self):
		"""Otherwise the mirror's own value would sit beside the header's and win,
		pinning every site to whatever the mirror happens to say."""
		with open(PORT) as handle:
			text = handle.read()
		self.assertIn('"%s ="' % CONST, text)

	def test_the_mirror_defines_it_at_module_level(self):
		# re.M matters: the assignment is at column zero of a line, not the start
		# of the file, and assertRegex does not apply MULTILINE for you.
		if not os.path.isdir(MIRROR):
			self.skipTest("mirror not present")
		self.assertIsNotNone(re.search(r"^%s\s*=" % CONST, script(), re.M),
			"the mirror must define %s at module level" % CONST)

	def test_it_is_defined_before_it_is_used(self):
		"""A Server Script is module level top to bottom; a name read above its
		assignment is a NameError on every request. This has happened here."""
		if not os.path.isdir(MIRROR):
			self.skipTest("mirror not present")
		lines = script().splitlines()
		defined = next(i for i, l in enumerate(lines) if re.match(r"^%s\s*=" % CONST, l))
		used = [i for i, l in enumerate(lines)
			if i != defined and CONST in l.split("#")[0]]
		self.assertTrue(used, "%s is defined and never read" % CONST)
		self.assertGreater(min(used), defined,
			"%s is read on line %d and defined on line %d"
			% (CONST, min(used) + 1, defined + 1))


class TestApprovalHonoursIt(unittest.TestCase):
	def setUp(self):
		if not os.path.isdir(MIRROR):
			self.skipTest("mirror not present")
		self.text = script()

	def test_both_approve_paths_are_guarded(self):
		"""Two of them: the single GM approve, and the bulk one. Fixing one and
		leaving the other is how a switch half-works."""
		refusals = [m.start() for m in re.finditer(
			r"An approved master plan already covers|overlaps approved ", self.text)]
		self.assertEqual(len(refusals), 2,
			"expected the two overlap refusals; found %d" % len(refusals))
		for at in refusals:
			window = self.text[max(0, at - 1200):at]
			with self.subTest(at=at):
				self.assertIn(CONST, window,
					"an overlap refusal that does not consult %s" % CONST)

	def test_the_clash_is_still_reported_when_allowed(self):
		"""Allowed is not the same as unmentioned."""
		self.assertRegex(self.text, r"clash_(warning|allowed|note)",
			"nothing reports the clash once the refusal is lifted")


class TestHeadroomStopsGuessing(unittest.TestCase):
	"""With two approved plans, `ORDER BY period_from DESC LIMIT 1` shows one
	budget and hides the other, without saying which it picked."""

	def setUp(self):
		if not os.path.isdir(MIRROR):
			self.skipTest("mirror not present")
		self.text = script()
		at = self.text.index('elif action == "headroom"')
		nxt = re.search(r"^elif action ==", self.text[at + 30:], re.M)
		block = self.text[at:at + 30 + (nxt.start() if nxt else len(self.text))]
		# code only. The comment above the query quotes the old
		# `ORDER BY ... LIMIT 1` to explain why it went, and a test that cannot
		# tell an explanation from the thing it explains is worse than no test.
		self.block = "\n".join(line.split("#")[0] for line in block.splitlines())

	def test_it_no_longer_takes_the_first_by_date(self):
		self.assertNotRegex(self.block, r"ORDER BY period_from DESC\s+LIMIT 1",
			"headroom still takes whichever plan starts later")

	def test_it_accepts_a_named_plan(self):
		self.assertIn("master_plan", self.block,
			"headroom cannot be told which budget to show")

	def test_it_reports_ambiguity_rather_than_choosing(self):
		self.assertRegex(self.block, r"ambiguous",
			"headroom must hand back the candidates when it cannot tell, the way "
			"the planner's task list does")


class TestTheResolutionRuleIsSharedNotRestated(unittest.TestCase):
	"""The rule already exists and is unit-tested. Two copies of it drift."""

	def test_the_pure_helper_still_answers_the_two_cases(self):
		from work_management.master_plan import resolve_master_plan

		self.assertEqual(resolve_master_plan("", ["WMMP-1"]), ("WMMP-1", None))
		name, reason = resolve_master_plan("", ["WMMP-1", "WMMP-2"])
		self.assertIsNone(name)
		self.assertTrue(reason)


if __name__ == "__main__":
	unittest.main()
