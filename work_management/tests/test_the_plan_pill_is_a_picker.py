"""The master-plan chips on New Request are a picker, and clicking one works.

When the chosen dates fall outside every approved plan, the banner lists each
plan as a chip and says *"Pick one to plan inside it"*. Clicking did nothing
visible.

**The chip was already a button and the handler already ran.** What it called
did not do the job. `boundDatesToPlan()` CLAMPED: it put the plan's period on
the date pickers as min/max, then pulled whichever edge hung outside back to it.
That is right while the request straddles the plan and useless when the request
sits wholly AFTER it -- `from` is not below `period_from`, so it stays; `to` is
pulled back to `period_to` and then pushed forward again to meet `from`. Both
dates end up outside the window they were supposed to move into. Measured
against WMMP-00001 (7-13 Sep), which is the screenshot:

    clicked with    20-26 Sep   ->   20-20 Sep   still outside
    clicked with     1-7 Aug    ->    7-7 Sep    one day, the span thrown away
    clicked with   10-30 Sep    ->   10-13 Sep   correct, and why it looked fine

And it was worse than a no-op: the next `renderPeriodBar` recomputes which plans
COVER the dates, finds none, and clears the plan the person just chose. The
click undid itself.

`planInside()` populates instead. Dates already wholly inside are left exactly
as they are -- a week chosen inside a month-long plan is the request, not an
accident, and that is the entire behaviour when the chip is only being used to
say WHICH of two overlapping plans a valid request draws on. Anything else moves
into the window, opening at today where the plan is still running and at
`period_from` where it is not. Planning in the past is legal, so a finished plan
opens at its own start rather than being refused -- verified on kentrout.local:
WMMP-00002, period ended 2026-09-13, today 2026-09-15, `tasks` returns
`blocked_reason: None` and one activity.

Measured end to end on kentrout.local:

    one plan 7-13 Sep, dates 20-26 Sep  -> "No approved master plan covers
                                            2026-09-20 to 2026-09-26", 0 tasks
    after the click (7-13 Sep, WMMP)    -> blocked None, 1 task, submit stores
                                           master_plan = WMMP-00002
    two plans over 5-9 Oct, neither named -> "more than one approved master plan
                                              ... WMMP-00003, WMMP-00004"
    clicking either                       -> blocked None, submit stores the
                                             one that was clicked

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_the_plan_pill_is_a_picker -v
"""

import os
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREEN = os.path.join(APP, "public", "js", "work-planner.js")
MARKUP = os.path.join(APP, "www", "work-planner.html")


def read(path):
	with open(path) as handle:
		return handle.read()


def js_function(src, name):
	"""One JS function body, declaration to the next one at column 2.

	Scoped, like the bulk-approval tests, rather than searching the whole file:
	a screen this size will satisfy almost any loose assertion somewhere.
	"""
	at = src.index("  function %s(" % name)
	nxt = src.find("\n  function ", at + 10)
	return src[at:nxt if nxt > 0 else len(src)]


def plan_inside(from_date, to_date, period_from, period_to, today):
	"""The rule the chip applies, in Python, so the cases can be asserted.

	Mirrors `planInside()` in work-planner.js the way `suggest()` in
	test_the_crew_is_computed mirrors the server's crew arithmetic: the JS is
	the implementation, this is the specification, and the tests below tie the
	two together.

	The clamp half of it is `clamp_into_plan()` in test_planner_period, which
	owns that rule and its cases. This adds one branch: where the request does
	not overlap the plan at all there is nothing to clamp onto, and both edges
	have to be placed rather than pulled.
	"""
	if not period_from or not period_to:
		return from_date, to_date
	if not from_date or not to_date:
		return period_from, period_to
	if from_date > period_to or to_date < period_from:
		start = today if (today <= period_to and today > period_from) else period_from
		return start, period_to
	frm = max(from_date, period_from)
	to = min(to_date, period_to)
	return frm, max(to, frm)


class TestTheRuleItself(unittest.TestCase):
	PLAN = ("2026-09-07", "2026-09-13")
	TODAY = "2026-09-15"

	def click(self, frm, to, plan=None, today=None):
		pf, pt = plan or self.PLAN
		return plan_inside(frm, to, pf, pt, today or self.TODAY)

	def test_dates_after_the_window_move_into_it(self):
		"""The screenshot, and the whole bug: this used to answer 20-20 Sep."""
		self.assertEqual(self.click("2026-09-20", "2026-09-26"),
			("2026-09-07", "2026-09-13"))

	def test_dates_before_the_window_move_into_it(self):
		"""The clamp collapsed this to a single day and kept no span at all."""
		self.assertEqual(self.click("2026-08-01", "2026-08-07"),
			("2026-09-07", "2026-09-13"))

	def test_dates_straddling_an_edge_keep_the_part_that_is_valid(self):
		"""Not replaced by the whole period. Clamping is the better answer where
		there is something to clamp onto, and it is its own earlier fix -- see
		test_planner_period, which owns that rule."""
		self.assertEqual(self.click("2026-09-10", "2026-09-30"),
			("2026-09-10", "2026-09-13"))
		self.assertEqual(self.click("2026-09-01", "2026-09-10"),
			("2026-09-07", "2026-09-10"))

	def test_a_range_swallowing_the_whole_plan_becomes_the_plan(self):
		self.assertEqual(self.click("2026-08-01", "2026-10-31"),
			("2026-09-07", "2026-09-13"))

	def test_a_week_already_inside_is_left_exactly_as_it_is(self):
		"""So clicking a chip only to say WHICH plan does not rewrite the
		request somebody has already described."""
		self.assertEqual(self.click("2026-09-08", "2026-09-11"),
			("2026-09-08", "2026-09-11"))

	def test_empty_pickers_take_the_whole_period(self):
		self.assertEqual(self.click("", ""), ("2026-09-07", "2026-09-13"))

	def test_a_running_plan_opens_at_today(self):
		"""Planning the rest of a period is the common case."""
		self.assertEqual(
			self.click("2020-01-01", "2020-01-02", plan=("2026-09-01", "2026-09-30")),
			("2026-09-15", "2026-09-30"))

	def test_a_future_plan_opens_at_its_start(self):
		self.assertEqual(
			self.click("2020-01-01", "2020-01-02", plan=("2026-11-01", "2026-11-30")),
			("2026-11-01", "2026-11-30"))

	def test_a_finished_plan_opens_at_its_start_rather_than_refusing(self):
		"""Backdated catch-up plans exist and are legal. Dragging one forward to
		today would put it outside its own budget, which is the failure this
		whole fix is about."""
		self.assertEqual(
			self.click("2020-01-01", "2020-01-02", plan=("2026-08-01", "2026-08-31")),
			("2026-08-01", "2026-08-31"))

	def test_the_edges_are_inclusive(self):
		for plan, want in ((("2026-09-01", "2026-09-15"), "2026-09-15"),
				(("2026-09-15", "2026-09-30"), "2026-09-15"),
				(("2026-09-15", "2026-09-15"), "2026-09-15")):
			with self.subTest(plan=plan):
				self.assertEqual(self.click("2020-01-01", "2020-01-02", plan=plan)[0], want)

	def test_it_never_answers_nothing(self):
		"""Every path sets both dates. A picker that sometimes leaves a box empty
		is the same kind of dead as the one this replaces."""
		for frm, to in (("", ""), ("2026-09-20", "2026-09-26"), ("2026-09-08", "2026-09-11")):
			with self.subTest(dates=(frm, to)):
				got = self.click(frm, to)
				self.assertTrue(all(got))


class TestTheScreenImplementsThatRule(unittest.TestCase):
	def setUp(self):
		self.fn = js_function(read(SCREEN), "planInside")

	def test_it_sets_both_dates(self):
		self.assertIn('f.value = ', self.fn)
		self.assertIn('t.value = pt;', self.fn)

	def test_the_placing_branch_is_reached_only_with_no_overlap(self):
		self.assertIn("if(f.value>pt || t.value<pf){", self.fn)

	def test_today_is_only_used_while_the_plan_is_running(self):
		self.assertIn("(now<=pt && now>pf) ? now : pf", self.fn)

	def test_the_clamp_is_kept_for_everything_that_overlaps(self):
		"""Deleting these three lines would pass every test in this file and
		silently undo the fix test_planner_period exists for."""
		for kept in ("if(f.value < pf) f.value=pf;",
				"if(t.value > pt) t.value=pt;",
				"if(t.value < f.value) t.value=f.value;"):
			with self.subTest(kept=kept):
				self.assertIn(kept, self.fn)

	def test_it_still_bounds_the_pickers(self):
		"""min/max on the inputs: the picker itself will not stray outside."""
		self.assertIn("e.min=pf; e.max=pt;", self.fn)

	def test_the_name_it_replaces_is_gone(self):
		self.assertNotIn("boundDatesToPlan", read(SCREEN))


class TestTheChipIsAControl(unittest.TestCase):
	def setUp(self):
		self.fn = js_function(read(SCREEN), "renderPeriodBar")

	def test_it_is_a_button_not_a_div_with_a_cursor(self):
		self.assertIn('<button type="button" class="bud', self.fn)

	def test_it_says_which_plan_over_which_days_and_how_much_is_in_it(self):
		for part in ("data-bn=", "period_from", "period_to", "activities"):
			with self.subTest(part=part):
				self.assertIn(part, self.fn)

	def test_the_chosen_one_is_announced_to_a_screen_reader(self):
		self.assertIn('aria-pressed="true"', self.fn)
		self.assertIn('aria-pressed="false"', self.fn)

	def test_every_chip_is_wired(self):
		self.assertIn('bar.querySelectorAll("[data-bf]").forEach', self.fn)


class TestTheHandlerDoesAllThreeThings(unittest.TestCase):
	"""Select, populate, re-check. Any two of the three still reads as broken."""

	def setUp(self):
		fn = js_function(read(SCREEN), "renderPeriodBar")
		at = fn.index('bar.querySelectorAll("[data-bf]")')
		self.handler = fn[at:]

	def test_it_selects_the_plan(self):
		self.assertIn('ST.masterPlan = x.getAttribute("data-bn")', self.handler)

	def test_it_sets_the_dates(self):
		self.assertIn('planInside(x.getAttribute("data-bf"), x.getAttribute("data-bt"))',
			self.handler)

	def test_it_re_runs_the_eligibility_check(self):
		"""Which reloads the task list, clears "nothing can be planned", and
		re-renders the banner -- so the banner going is what says it worked."""
		self.assertIn("loadPlannableTasks()", self.handler)

	def test_and_refreshes_the_live_estimate(self):
		for call in ("syncSlider()", "recalc()"):
			with self.subTest(call=call):
				self.assertIn(call, self.handler)

	def test_the_selection_travels_with_the_request(self):
		src = read(SCREEN)
		at = src.index('action:"submit"')
		self.assertIn("master_plan:ST.masterPlan", src[at:at + 700])


class TestWhatWasChosenIsShown(unittest.TestCase):
	def setUp(self):
		self.fn = js_function(read(SCREEN), "renderPeriodBar")

	def test_the_chosen_plan_is_named_on_screen(self):
		self.assertIn('Planning inside <b>', self.fn)
		self.assertIn("planSpan(chosen.period_from, chosen.period_to)", self.fn)

	def test_the_screens_own_choice_outranks_the_server_s_answer(self):
		"""In the ambiguous state the server answers `master_plan: null` on
		purpose -- it will not guess between two -- so reading only the response
		leaves the chip the person just clicked looking unclicked."""
		self.assertIn("var chosenName = ST.masterPlan || active", self.fn)

	def test_there_is_a_way_to_put_it_back(self):
		self.assertIn('btn.textContent="Clear"', self.fn)
		self.assertIn('btn.onclick=function(){ ST.masterPlan=""; loadPlannableTasks(); }',
			self.fn)

	def test_clearing_is_only_offered_where_there_was_a_decision(self):
		"""One plan covering the dates is not a choice; it is the only budget
		there is, and the screen re-selects it on the next render. Offering
		Clear there would be a button that undoes itself."""
		self.assertIn("var wasAChoice = !!chosen && covering.length!==1;", self.fn)

	def test_the_ambiguous_state_asks_rather_than_just_listing(self):
		self.assertIn("approved plans cover these dates", self.fn)
		self.assertIn("Say which:", self.fn)

	def test_it_stops_asking_once_answered(self):
		self.assertIn("covering.length>1 && !ST.masterPlan", self.fn)


class TestTheSpanIsReadable(unittest.TestCase):
	def setUp(self):
		self.fn = js_function(read(SCREEN), "planSpan")

	def test_one_month_prints_once(self):
		self.assertIn('(a[0]===b[0] && a[1]===b[1])', self.fn)

	def test_the_year_is_only_shown_when_it_is_not_this_one(self):
		self.assertIn("var thisYear=today().slice(0,4);", self.fn)

	def test_an_unexpected_value_falls_back_to_the_dates(self):
		"""Rather than printing NaN at somebody."""
		self.assertIn("if(a.length<3 || b.length<3) return", self.fn)


class TestTheButtonInTheMarkupMatches(unittest.TestCase):
	def setUp(self):
		self.html = read(MARKUP)

	def test_it_starts_hidden(self):
		at = self.html.index('id="f-usemp"')
		self.assertIn('style="display:none"', self.html[at:at + 120])

	def test_it_no_longer_says_something_it_does_not_do(self):
		"""Its own label, not the file -- the comment above it quotes the old one
		on purpose, and a test that trips on that is one people edit rather than
		believe."""
		at = self.html.index('id="f-usemp"')
		label = self.html[self.html.index(">", at) + 1:self.html.index("</button>", at)]
		self.assertEqual(label.strip(), "Clear")

	def test_the_chosen_line_has_somewhere_to_sit(self):
		self.assertIn("#wpp .mp-period .mp-chosen{", self.html)


if __name__ == "__main__":
	unittest.main()
