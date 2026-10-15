"""A server action nobody can reach is not a feature.

The v16 payment screen shipped `pay_issues`, `pay_audit` and the whole
`allow_day_range` / `days` / `max_span_days` machinery in api/payment.py --
ported faithfully from the mirror, tested, and completely unreachable. There was
no Issues tab and no Audit tab in www/work-payment.html, so `initAudit()` sat in
the JS as dead code and `pay_issues` had no client at all; `payWindow()` never
sent `days`, so a site that ticked "Also allow sending a chosen range of days"
got pay weeks anyway and a hint that said so.

That is the drift these tests are for. The mirror's copies of the screens are
the live ones and had all three; the app's were behind, in the one direction
check_ported.py cannot see -- it compares the ported Python, not the JS beside
it and not the markup the JS needs.

So: every action api/payment.py answers has a caller, every id the ported code
asks for exists, and the four screens' JS is byte-identical between app and
mirror -- that last one except on a forked branch, where the app's copy is the
live one and the byte-compare skips by design (docs/ALTURA_FORK.md).

The HTML deliberately is NOT compared -- the app's is jinja-templated for the
configurable taxonomy where the mirror hardcodes Kaitet's words -- so parity is
asserted on the JS only.
"""

import os
import re
import unittest

from work_management.tests import mirror

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
JS = os.path.join(APP, "public", "js")
WWW = os.path.join(APP, "www")


def read(path):
	with open(path) as handle:
		return handle.read()


SCREENS = ("work-planner", "work-assigner", "work-actuals", "work-payment")


class TestTheAppAndMirrorScreensAgree(unittest.TestCase):
	"""The mirror's JS is what runs live. A screen only in one is a screen
	whose fixes land on half the users."""

	def test_every_screen_matches_the_mirror_byte_for_byte(self):
		# On a forked branch public/js/ IS the live screen -- there is no mirror
		# copy downstream of it, so byte-identity is not a property to hold.
		# Gated on the fork declaration, not on the checkout: see tests/mirror.py.
		if mirror.forked():
			self.skipTest(mirror.FORK_SKIP)
		if not mirror.present(mirror.WEB_PAGES):
			self.skipTest("mirror not checked out at " + mirror.ROOT)
		for screen in SCREENS:
			with self.subTest(screen=screen):
				theirs = os.path.join(mirror.WEB_PAGES, screen + ".js")
				if not os.path.exists(theirs):
					self.skipTest(screen + " not in the mirror")
				self.assertEqual(read(theirs), read(os.path.join(JS, screen + ".js")),
					screen + ".js differs between the app and the mirror")


class TestEveryPaymentActionHasACaller(unittest.TestCase):
	"""api/payment.py answering an action no screen asks for is either a tool
	somebody runs by hand, or work that was ported and then stranded.

	The difference has to be written down, because from the code they look
	identical -- which is how `pay_issues` and `pay_audit` passed for tools for
	as long as they did. Everything not on the list below is expected to have a
	caller in work-payment.js; adding an action means wiring it up or saying
	here why it needs no UI."""

	# Run by hand against /api/method/wm_payment?action=..., never from a screen.
	# Each is either HYGIENE (repairs data in place), AUDIT (answers a question
	# for a reviewer), or a bulk operation that exists to avoid a round trip per
	# document. Three of them are documented in docs/DEVELOPER_GUIDE.md and
	# pay_recalc_wages is exercised by tests/test_rates.py.
	CONSOLE_ONLY = {
		"pay_absent_conflicts",   # AUDIT: money recorded on a day marked ABSENT
		"pay_bulk_review",
		"pay_confirmed",
		"pay_fix_orphan_refs",    # HYGIENE
		"pay_purge_queue",        # empties the accounts queue in one pass
		"pay_recalc_wages",
		"pay_round_amounts",      # HYGIENE: float artifacts like 338.99999999999994
		"pay_worker_review",
	}

	def actions(self):
		src = read(os.path.join(APP, "api", "payment.py"))
		return sorted(set(re.findall(r'action == "(pay_[a-z_]+)"', src)))

	def test_there_are_actions_to_check(self):
		self.assertGreater(len(self.actions()), 5)

	def test_the_allowlist_names_only_actions_that_exist(self):
		"""A stale name on the list silently excuses a real screen action."""
		gone = sorted(self.CONSOLE_ONLY - set(self.actions()))
		self.assertEqual(gone, [], "no longer in api/payment.py: " + ", ".join(gone))

	def test_the_screen_calls_every_action_that_is_not_a_hand_run_tool(self):
		screen = read(os.path.join(JS, "work-payment.js"))
		stranded = [a for a in self.actions()
			if a not in self.CONSOLE_ONLY and ('"%s"' % a) not in screen]
		self.assertEqual(stranded, [],
			"api/payment.py answers these and work-payment.js never asks, so "
			"nobody can reach them: " + ", ".join(stranded))


class TestThePaymentScreenServesItsTabs(unittest.TestCase):
	"""Each tab needs three things that were added in three different places:
	a button, a panel, and a line in showTab. Two of the six had none of them."""

	TABS = ("build", "accounts", "issues", "mine", "audit", "insights")

	def setUp(self):
		self.html = read(os.path.join(WWW, "work-payment.html"))
		self.js = read(os.path.join(JS, "work-payment.js"))

	def test_every_tab_has_a_button(self):
		for tab in self.TABS:
			with self.subTest(tab=tab):
				self.assertIn('data-tab="%s"' % tab, self.html)

	def test_every_tab_has_a_panel(self):
		for tab in self.TABS:
			with self.subTest(tab=tab):
				self.assertIn('id="p-%s"' % tab, self.html)

	def test_every_tab_is_dispatched(self):
		block = self.js[self.js.index("function showTab("):][:1200]
		for tab in self.TABS:
			with self.subTest(tab=tab):
				self.assertIn('name==="%s"' % tab, block)

	def test_the_audit_entry_point_is_reachable(self):
		"""initAudit() existed and nothing called it."""
		self.assertIn("initAudit()", self.js[self.js.index("function showTab("):][:1200])


class TestEveryTabShowsItsOwnPanel(unittest.TestCase):
	"""Dispatched is not the same as shown. Issues and Audit each had a button,
	a panel and a showTab line -- the three things the class above checks -- and
	clicking either one left a blank screen: showTab gave the "on" class to a
	hand-kept list of four panels, theirs not among them, and `.panel` is
	display:none without it. loadIssues() ran and filled a div nobody could see.

	So this runs the real showTab() under node against the real tab buttons and
	panel ids, and asks which panel is visible after each click."""

	def setUp(self):
		self.html = read(os.path.join(WWW, "work-payment.html"))
		self.js = read(os.path.join(JS, "work-payment.js"))
		bar = self.html[self.html.index('id="pay-tabs"'):]
		bar = bar[:bar.index("</div>")]
		self.tabs = re.findall(r'data-tab="([a-z]+)"', bar)
		self.panels = re.findall(r'id="(p-[a-z]+)"', self.html)

	def show_tab_source(self):
		at = self.js.index("  function showTab(")
		return self.js[at:self.js.index("\n  function ", at + 10)]

	def test_the_tab_bar_was_found(self):
		self.assertGreaterEqual(len(self.tabs), 6, self.tabs)

	def test_every_tab_button_has_a_panel(self):
		for tab in self.tabs:
			with self.subTest(tab=tab):
				self.assertIn("p-" + tab, self.panels)

	def test_no_hand_kept_list_of_panels(self):
		"""The list is what drifted; the buttons are the list."""
		self.assertNotRegex(self.show_tab_source(), r'\[\s*"build"\s*,')

	def test_clicking_each_tab_shows_exactly_its_panel(self):
		import json
		import shutil
		import subprocess

		node = shutil.which("node") or shutil.which("nodejs")
		if not node:
			self.skipTest("node is not installed")
		script = """
var TABS=%s, PANELS=%s, made={};
PANELS.forEach(function(id){ made[id]={on:false, classList:{toggle:function(c,v){ made[id].on=!!v; }}}; });
function el(id){ return made[id]||null; }
var document={querySelectorAll:function(){ return TABS.map(function(t){
  return {getAttribute:function(){ return t; }, setAttribute:function(){}}; }); }};
var ST={paysByFeed:1};
function noop(){}
var loadPayable=noop, feedWeek=noop, loadAccounts=noop, loadIssues=noop, loadMine=noop,
    initAudit=noop, initInsights=noop, feedPeriod=noop;
%s
var out={};
TABS.forEach(function(t){ showTab(t); out[t]=PANELS.filter(function(id){ return made[id].on; }); });
console.log(JSON.stringify(out));
""" % (json.dumps(self.tabs), json.dumps(self.panels), self.show_tab_source())
		res = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
		self.assertEqual(res.returncode, 0, res.stderr)
		shown = json.loads(res.stdout)
		for tab in self.tabs:
			with self.subTest(tab=tab):
				self.assertEqual(shown[tab], ["p-" + tab])


class TestTheIssuesTabNeverRendersBlank(unittest.TestCase):
	"""Nothing to show is a sentence; a failed call is an error. Neither is an
	empty panel."""

	def setUp(self):
		js = read(os.path.join(JS, "work-payment.js"))
		at = js.index("  function loadIssues(")
		self.load = js[at:js.index("\n  function ", at + 10)]
		at = js.index("  function renderIssues(")
		self.render = js[at:js.index("\n  function ", at + 10)]

	def test_an_empty_answer_says_no_issues(self):
		self.assertIn("<b>No issues</b>", self.render)

	def test_a_refusal_is_shown(self):
		self.assertIn("if(d.error){", self.load)
		self.assertIn('class="err"', self.load)

	def test_a_failed_request_is_shown(self):
		self.assertIn(".catch(", self.load)
		self.assertIn("Could not load issues", self.load)


class TestSendingAChosenRangeReachesTheServer(unittest.TestCase):
	"""The Setting, the hint and the parameter are three separate things, and
	the screen had none of them wired."""

	def setUp(self):
		self.js = read(os.path.join(JS, "work-payment.js"))
		self.html = read(os.path.join(WWW, "work-payment.html"))
		self.api = read(os.path.join(APP, "api", "payment.py"))

	def test_the_server_still_reads_the_days_parameter(self):
		self.assertIn('form_dict.get("days")', self.api)

	def test_the_screen_sends_it(self):
		window = self.js[self.js.index("function payWindow("):][:400]
		self.assertIn("days:sendSpanDays()", window)
		self.assertIn('days:(win.days||"")', self.js)

	def test_the_screen_learns_whether_settings_allows_it(self):
		self.assertIn("allow_day_range", self.js)
		self.assertIn("max_span_days", self.js)

	def test_the_hint_can_be_rewritten_rather_than_lying(self):
		"""It read "Sending still creates one payment per pay week" always."""
		self.assertIn('id="pw-range-hint"', self.html)
		self.assertIn('el("pw-range-hint")', self.js)


class TestTheScreenAsksForNoElementItHasNot(unittest.TestCase):
	"""A tab whose panel was never added fails silently: el() returns null and
	the handler throws into a console nobody is reading."""

	NEW = ("is-apply", "is-reset", "is-from", "is-to", "issues-body", "iss-kpis",
		"iss-farmchips", "iss-paydate", "tab-iss-cnt", "ik-considered", "ik-clear",
		"ik-blocked", "ik-blocked-amt", "pw-range-hint", "au-from", "au-to",
		"au-apply", "au-reset", "au-print", "au-xlsx", "au-v-summary", "au-v-detail",
		"au-v-workers", "au-v-disc", "audit-body", "au-farmchips", "au-kpis")

	def test_the_two_recovered_tabs_have_all_their_markup(self):
		html = read(os.path.join(WWW, "work-payment.html"))
		absent = [i for i in self.NEW if ('id="%s"' % i) not in html]
		self.assertEqual(absent, [],
			"work-payment.html is missing: " + ", ".join(absent))


if __name__ == "__main__":
	unittest.main()
