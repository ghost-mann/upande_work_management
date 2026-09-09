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
from work_management.tests.mirror import ROOT as MIRROR
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
		if not os.path.exists(PORT):
			self.skipTest("mirror not present")
		with open(PORT) as handle:
			text = handle.read()
		self.assertRegex(text, r"%s = _cfg\[\"%s\"\]" % (CONST, KEY),
			"port_app.py must assign %s from get_config()" % CONST)

	def test_the_port_strips_the_mirror_literal(self):
		"""Otherwise the mirror's own value would sit beside the header's and win,
		pinning every site to whatever the mirror happens to say."""
		if not os.path.exists(PORT):
			self.skipTest("mirror not present")
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


class TestEveryHeadroomCallerNamesItsPlan(unittest.TestCase):
	"""headroom stopped guessing, so its callers have to say which plan.

	It used to take whichever approved plan started latest -- exact while a farm
	held one budget per period, and a silent wrong answer once it can hold two.
	It reports `ambiguous` now instead of choosing.

	Which broke the master plan screen, and this is the regression itself:
	openMasterPlan(name) reads a plan, then asks headroom about THAT plan's own
	period -- and did not name it. Where one period sits wholly inside another,
	both contain the range, headroom rightly refuses to choose, and the screen
	got no activities at all:

	    Plan A  2026-10-01 .. 2026-10-31   approved
	    Plan C  2026-10-10 .. 2026-10-20   approved, inside A

	    opening C without naming it -> master_plan=None, activities=0
	    opening C naming it         -> master_plan='WMMP-00016', activities=1

	With no activities every Progress and Left cell reads zero, which looks like
	work nobody has started rather than a screen that could not tell which budget
	it was being asked about. Reproduced on kaitet.local before fixing.
	"""

	JS = os.path.join(APP, "public", "js")

	def planner_js(self):
		with open(os.path.join(self.JS, "work-planner.js")) as handle:
			return handle.read()

	def test_headroom_is_only_called_from_one_place(self):
		"""If it grows a second caller, the assertion below has to cover it."""
		self.assertEqual(self.planner_js().count('action:"headroom"'), 1)

	def test_that_caller_names_the_plan(self):
		text = self.planner_js()
		at = text.index('action:"headroom"')
		window = text[at:at + 260]
		self.assertIn("master_plan:", window,
			"headroom is asked about a plan's own period without naming the plan, "
			"so two overlapping approved plans make it answer `ambiguous` and the "
			"screen shows zeros")

	def test_it_names_the_plan_it_was_asked_to_open(self):
		"""`name` is openMasterPlan's own argument. Passing p.name would work too;
		passing the farm's newest would be the bug again."""
		text = self.planner_js()
		at = text.index('action:"headroom"')
		self.assertRegex(text[at:at + 260], r"master_plan\s*:\s*(name|p\.name)\b")

	def test_the_server_still_refuses_to_guess(self):
		"""The fix is in the caller. If headroom went back to picking the latest,
		the screen would look right and be wrong again."""
		if not os.path.isdir(MIRROR):
			self.skipTest("mirror not present")
		text = script()
		at = text.index('elif action == "headroom"')
		nxt = re.search(r"^elif action ==", text[at + 30:], re.M)
		block = text[at:at + 30 + (nxt.start() if nxt else len(text))]
		code = "\n".join(line.split("#")[0] for line in block.splitlines())
		self.assertNotRegex(code, r"ORDER BY period_from DESC\s+LIMIT 1")
		self.assertIn("ambiguous", code)


# --------------------------------------------------------------------------
# The drawdown itself: which requests each plan is charged for.
# --------------------------------------------------------------------------

import sqlite3

from work_management.master_plan import attributed_to_plan, unattributed_to_plan

PLANS = "`tabWork Management Master Plan`"
REQUESTS = "`tabWork Management Planner`"

SUM = ("SELECT COALESCE(SUM(p.quantity),0) q, COALESCE(SUM(p.total_cost),0) c "
	"FROM " + REQUESTS + " p "
	"WHERE p.farm = %(f)s AND IFNULL(p.workflow_state,'') != 'Rejected' AND ")


def sqlite_query(text):
	"""%(name)s is MySQLdb's placeholder; sqlite3 spells the same thing :name."""
	return re.sub(r"%\((\w+)\)s", r":\1", text)


class Ledger:
	"""Two tables and the four rules, run for real against sqlite3.

	The rest of this suite is pure and needs no site, and this stays that way:
	the attribution rule IS a SQL string, so the only honest test of it executes
	it. sqlite3 takes MySQL's backtick quoting and IFNULL unchanged, and the rule
	uses nothing else -- a correlated NOT EXISTS and four comparisons. The same
	four cases were also measured against the site's MariaDB before this was
	written; this is what keeps them measured on every run.
	"""

	def __init__(self):
		self.db = sqlite3.connect(":memory:")
		self.db.execute("CREATE TABLE " + PLANS + " (name TEXT, farm TEXT, "
			"period_from TEXT, period_to TEXT, workflow_state TEXT)")
		self.db.execute("CREATE TABLE " + REQUESTS + " (name TEXT, farm TEXT, "
			"task TEXT, master_plan TEXT, from_date TEXT, to_date TEXT, "
			"quantity REAL, total_cost REAL, workflow_state TEXT)")

	def plan(self, name, farm, period_from, period_to, state="Approved"):
		self.db.execute("INSERT INTO " + PLANS + " VALUES (?,?,?,?,?)",
			(name, farm, period_from, period_to, state))
		return name

	def request(self, name, farm, from_date, to_date, quantity, master_plan=None,
			state="Approved", task="T1", cost=None):
		self.db.execute("INSERT INTO " + REQUESTS + " VALUES (?,?,?,?,?,?,?,?,?)",
			(name, farm, task, master_plan, from_date, to_date, quantity,
			 cost if cost is not None else quantity * 10, state))
		return name

	def charged(self, plan, farm="F"):
		return self._sum(attributed_to_plan("p"), plan, farm)

	def unattributed(self, plan, farm="F"):
		return self._sum(unattributed_to_plan("p"), plan, farm)

	def _sum(self, rule, plan, farm):
		row = self.db.execute(sqlite_query(SUM + rule), {
			"f": farm, "plan": plan,
			"pfrom": self.period(plan)[0], "pto": self.period(plan)[1],
		}).fetchone()
		return row[0]

	def period(self, plan):
		return self.db.execute("SELECT period_from, period_to FROM " + PLANS
			+ " WHERE name = ?", (plan,)).fetchone()


def overlapping():
	"""The shape of the defect: two approved plans, one farm, sharing 11-04..07."""
	led = Ledger()
	led.plan("A", "F", "2026-11-02", "2026-11-07")
	led.plan("B", "F", "2026-11-04", "2026-11-09")
	return led


class TestTwoPlansTwoRequests(unittest.TestCase):
	"""Scenario 3d, which is where this was measured. Two overlapping approved
	plans and one request naming each, for 6 and 9. Both plans read 15."""

	def setUp(self):
		self.led = overlapping()
		self.led.request("R1", "F", "2026-11-05", "2026-11-05", 6, master_plan="A")
		self.led.request("R2", "F", "2026-11-05", "2026-11-05", 9, master_plan="B")

	def test_each_plan_is_charged_its_own_request(self):
		self.assertEqual(self.led.charged("A"), 6)
		self.assertEqual(self.led.charged("B"), 9)

	def test_neither_is_charged_the_sum(self):
		"""The regression itself: 15 on both, every plan charged every plan's
		requests, and headroom persisting that figure onto the Activity rows."""
		self.assertNotEqual(self.led.charged("A"), 15)
		self.assertNotEqual(self.led.charged("B"), 15)

	def test_a_row_naming_b_never_counts_against_a(self):
		self.led.request("R3", "F", "2026-11-05", "2026-11-05", 100, master_plan="B")
		self.assertEqual(self.led.charged("A"), 6)
		self.assertEqual(self.led.charged("B"), 109)

	def test_the_link_wins_over_the_dates(self):
		"""A request naming a plan is charged to it even where the dates fall
		outside: the link is what the requester chose."""
		self.led.request("R4", "F", "2026-12-01", "2026-12-02", 5, master_plan="A")
		self.assertEqual(self.led.charged("A"), 11)

	def test_a_rejected_request_is_still_the_caller_s_filter(self):
		"""The rule does not restate it, so the caller's WHERE has to carry it --
		which is what the harness above reproduces."""
		self.led.request("R5", "F", "2026-11-05", "2026-11-05", 50,
			master_plan="A", state="Rejected")
		self.assertEqual(self.led.charged("A"), 6)

	def test_another_farm_s_request_is_not_this_farm_s(self):
		self.led.request("R6", "G", "2026-11-05", "2026-11-05", 50, master_plan="A")
		self.assertEqual(self.led.charged("A"), 6)


class TestTheLegacyRowsWithNoLink(unittest.TestCase):
	"""Every request raised before the field existed carries no link, and dates
	are all it has. 664 of them on live at the time, 5 of them unlinked."""

	def setUp(self):
		self.led = overlapping()

	def test_one_containing_plan_still_counts(self):
		"""This is what keeps pre-backfill rows working, and it is the reason the
		fallback exists at all."""
		self.led.request("R1", "F", "2026-11-02", "2026-11-03", 7)
		self.assertEqual(self.led.charged("A"), 7)
		self.assertEqual(self.led.charged("B"), 0)

	def test_two_containing_plans_count_against_neither(self):
		"""Synthetic: the site has 5 unlinked requests and all 5 have ZERO
		containing approved plans, so this case cannot be observed there."""
		self.led.request("R1", "F", "2026-11-05", "2026-11-05", 4)
		self.assertEqual(self.led.charged("A"), 0)
		self.assertEqual(self.led.charged("B"), 0)

	def test_the_ambiguous_row_is_surfaced_rather_than_dropped(self):
		"""Real committed work whose budget nobody can name. Charging it to both
		is the bug; charging it to one is the guess; dropping it silently leaves
		the plan looking healthier than it is."""
		self.led.request("R1", "F", "2026-11-05", "2026-11-05", 4)
		self.assertEqual(self.led.unattributed("A"), 4)
		self.assertEqual(self.led.unattributed("B"), 4)

	def test_the_remainder_is_never_folded_back_in(self):
		"""Charged and unattributed are disjoint. If a row could land in both,
		the double-charge would be back by another route."""
		self.led.request("R1", "F", "2026-11-05", "2026-11-05", 4)
		self.led.request("R2", "F", "2026-11-02", "2026-11-03", 7)
		self.led.request("R3", "F", "2026-11-05", "2026-11-05", 6, master_plan="A")
		self.assertEqual(self.led.charged("A"), 13)
		self.assertEqual(self.led.unattributed("A"), 4)

	def test_a_linked_row_is_never_unattributed(self):
		"""It has an answer. Only the ones with no link can be ambiguous."""
		self.led.request("R1", "F", "2026-11-05", "2026-11-05", 4, master_plan="A")
		self.assertEqual(self.led.unattributed("A"), 0)
		self.assertEqual(self.led.unattributed("B"), 0)

	def test_an_empty_string_link_reads_as_no_link(self):
		"""Frappe writes '' as often as NULL for an unset Link."""
		self.led.request("R1", "F", "2026-11-02", "2026-11-03", 7, master_plan="")
		self.assertEqual(self.led.charged("A"), 7)

	def test_only_an_APPROVED_other_plan_makes_it_ambiguous(self):
		"""A plan still in Pending GM budgets nothing yet. Counting it would make
		a row unattributable because of a plan that may never be approved."""
		self.led.plan("C", "F", "2026-11-01", "2026-11-30", state="Pending GM")
		self.led.request("R1", "F", "2026-11-02", "2026-11-03", 7)
		self.assertEqual(self.led.charged("A"), 7)
		self.assertEqual(self.led.unattributed("A"), 0)

	def test_another_farm_s_plan_does_not_make_it_ambiguous(self):
		self.led.plan("D", "G", "2026-11-01", "2026-11-30")
		self.led.request("R1", "F", "2026-11-02", "2026-11-03", 7)
		self.assertEqual(self.led.charged("A"), 7)

	def test_a_plan_that_merely_overlaps_does_not_make_it_ambiguous(self):
		"""Containment, not overlap: B starts on the 4th and cannot hold a
		request that starts on the 2nd."""
		self.led.request("R1", "F", "2026-11-02", "2026-11-05", 7)
		self.assertEqual(self.led.charged("A"), 7)
		self.assertEqual(self.led.unattributed("A"), 0)


class TestTheMoneyMovesWithTheQuantity(unittest.TestCase):
	def test_cost_is_attributed_the_same_way(self):
		"""planned_cost is what the budget cap's money ceiling reads, and a rate
		change can blow that without the quantity moving at all."""
		led = overlapping()
		led.request("R1", "F", "2026-11-05", "2026-11-05", 6, master_plan="A", cost=800)
		led.request("R2", "F", "2026-11-05", "2026-11-05", 9, master_plan="B", cost=1200)
		row = led.db.execute(sqlite_query(SUM + attributed_to_plan("p")),
			{"f": "F", "plan": "A", "pfrom": "2026-11-02", "pto": "2026-11-07"}).fetchone()
		self.assertEqual(row[1], 800)


class TestEveryDrawdownAsksTheSameQuestion(unittest.TestCase):
	"""The rule is only as good as the number of places that use it.

	The defect was not that the rule was wrong -- api/dashboard.py had it right
	and was the reference. The defect was that six other queries summed the same
	table by dates alone, so fixing one left five wrong and nothing said which.
	"""

	MODULES = ("masterplan.py", "planner.py", "dashboard.py")
	API = os.path.join(APP, "api")

	def drawdowns(self, module):
		"""Every frappe.db.sql() call that sums planner quantities.

		Whole calls, not the SQL literals inside them: the rule is concatenated in
		from master_plan.py, so half of each query's text is a function call, and a
		test that read only the string literals would see a WHERE clause with no
		attribution in it and be right for the wrong reason.

		Cut at `as_dict`, which every one of these passes, so the window is the
		call and not the paragraph after it.
		"""
		with open(os.path.join(self.API, module)) as handle:
			src = handle.read()
		found = []
		for chunk in src.split("frappe.db.sql(")[1:]:
			call = chunk[:chunk.index("as_dict")] if "as_dict" in chunk[:2000] else chunk[:1600]
			if "tabWork Management Planner" not in call:
				continue
			if not re.search(r"SUM\(\s*\w*\.?(quantity|total_cost)", call):
				continue
			found.append((module, call))
		return found

	def all_drawdowns(self):
		out = []
		for module in self.MODULES:
			out.extend(self.drawdowns(module))
		return out

	def attributed(self, call):
		return ("attributed_to_plan" in call or "unattributed_to_plan" in call
			or "master_plan" in call)

	def by_period(self, call):
		"""Scoped to a master plan's period. `\bpfrom\b` and not `pfrom`: the
		dashboard has a `ppfrom` that is a dashboard date range and no plan."""
		return bool(re.search(r"\bpfrom\b|period_from", call))

	def test_there_are_drawdowns_to_check(self):
		"""A matcher that matches nothing passes every assertion below."""
		charged = [c for _, c in self.all_drawdowns() if self.attributed(c)]
		self.assertGreaterEqual(len(charged), 6,
			"found %d attributed drawdown queries; the matcher has probably rotted"
			% len(charged))

	def test_none_of_them_matches_on_dates_alone(self):
		"""A planner sum scoped to a plan's period and nothing else IS the bug:
		with two plans over that period it returns both plans' requests."""
		for module, call in self.all_drawdowns():
			if not self.by_period(call):
				continue
			with self.subTest(module=module, sql=" ".join(call.split())[:70]):
				self.assertTrue(self.attributed(call),
					"this sums planner quantities over a plan's period without "
					"asking which master plan they were drawn against, so two "
					"overlapping plans are each charged the other's requests")


class TestTheCapNamesThePlanItRefusedFor(unittest.TestCase):
	"""'12 left of 20' with two plans in force is unanswerable: the reader
	cannot tell whose budget refused them, and pre-fix the figure belonged to
	neither plan -- it was the sum across both."""

	def source(self):
		with open(os.path.join(APP, "api", "planner.py")) as handle:
			return handle.read()

	def refusals(self):
		src = self.source()
		return [src[at:at + 420] for at in
			(m.start() for m in re.finditer(r'"Over the budgeted ', src))]

	def test_the_refusals_are_still_there(self):
		"""Two per ceiling-checking action -- one for the quantity ceiling and one
		for the cost ceiling -- and a raise is checked against the same two."""
		self.assertGreaterEqual(len(self.refusals()), 2)

	def test_each_names_the_master_plan(self):
		"""Whichever action refuses, and however it holds the plan."""
		for text in self.refusals():
			with self.subTest(refusal=" ".join(text.split())[:60]):
				self.assertTrue("cm.name" in text or "rt.master_plan" in text,
					"the refusal quotes a remaining figure without saying which "
					"plan it belongs to")

	def test_the_figure_it_quotes_comes_from_the_attributed_sum(self):
		"""cap_rq is cap_line.work_qty minus cap_used.q, and cap_used has to be
		this plan's own consumption or the number in the message is the sum
		across every overlapping plan -- which is the over-refusal itself."""
		src = self.source()
		at = src.index("cap_used = frappe.db.sql(")
		block = src[at:at + 900]
		self.assertIn("attributed_to_plan", block,
			"the cap sums by dates, so its figure is every overlapping plan's "
			"consumption and the message quotes a number belonging to no plan")
		self.assertIn('"plan": cm.name', block,
			"cm is the plan resolved for this request; charging any other plan "
			"here would put the cap and the stored link out of step")
