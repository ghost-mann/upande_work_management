# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Presence answers for the day the work was done.

Reported from Altura. Master plans and actuals are raised for PAST weeks --
backfilling a fortnight is ordinary there -- and the assigner's presence chips
and the presence bar reported who had scanned in THIS MORNING against a window of
14-18 September. Daniel was deciding whether a day was payable against a scan
from a different fortnight.

The fault was three queries in `a_employees`:

    WHERE DATE(`time`) = %s          -- today
    WHERE attendance_date = %s       -- today
    WHERE att.attendance_date = %s   -- today

asked whatever window the plan covered. The date a presence question is about is
the WINDOW'S, and `work_management/presence.py` is that rule stated once.

**One rule stays about today and is asserted to stay that way.** The morning-scan
gate asks whether the crew turned up this morning; it exists to stop somebody
staffing today's work with people who never arrived, and it is not a question you
can put to a window that finished last week. `applies_today()` says no there.

    PYTHONPATH=. ~/frappe-bench3/env/bin/python -m unittest \\
        work_management.tests.test_presence_answers_for_the_work_date -v
"""

import os
import unittest

from work_management import presence

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: The dates in the report, so the assertions read as the case does.
TODAY = "2026-09-23"           # a Wednesday
LAST_WEEK = ("2026-09-14", "2026-09-18")    # Mon-Fri, finished
THIS_WEEK = ("2026-09-21", "2026-09-25")    # Mon-Fri, running
NEXT_WEEK = ("2026-09-28", "2026-10-02")    # Mon-Fri, not started


def api(module):
	with open(os.path.join(HERE, "api", module + ".py"), encoding="utf-8") as handle:
		return handle.read()


def screen(name):
	with open(os.path.join(HERE, "public", "js", name), encoding="utf-8") as handle:
		return handle.read()


class TestTheWindowIsTheWindowsOwnDays(unittest.TestCase):
	def test_a_finished_window_reads_its_own_days(self):
		self.assertEqual(presence.evidence_window(LAST_WEEK[0], LAST_WEEK[1], TODAY),
			("2026-09-14", "2026-09-18", 5))

	def test_a_running_window_stops_at_today(self):
		"""Thursday and Friday have not happened; there is nothing to find and
		"no record" for them is a date, not a finding."""
		self.assertEqual(presence.evidence_window(THIS_WEEK[0], THIS_WEEK[1], TODAY),
			("2026-09-21", "2026-09-23", 3))

	def test_a_window_that_has_not_started_reads_nothing(self):
		self.assertEqual(presence.evidence_window(NEXT_WEEK[0], NEXT_WEEK[1], TODAY),
			(None, None, 0))

	def test_a_one_day_window_is_one_day(self):
		self.assertEqual(presence.evidence_window(TODAY, TODAY, TODAY), (TODAY, TODAY, 1))

	def test_a_missing_period_is_not_a_window(self):
		for pair in ((None, LAST_WEEK[1]), (LAST_WEEK[0], None), (None, None), ("", "")):
			with self.subTest(pair=pair):
				self.assertEqual(presence.evidence_window(pair[0], pair[1], TODAY),
					(None, None, 0))

	def test_a_datetime_is_read_as_its_date(self):
		"""Frappe hands dates back in several shapes; the comparison is on the
		date, not on whatever the driver returned."""
		self.assertEqual(
			presence.evidence_window("2026-09-14 00:00:00", "2026-09-18 23:59:59", TODAY),
			("2026-09-14", "2026-09-18", 5))


class TestTheDayAChipAnswersFor(unittest.TestCase):
	def test_a_past_window_answers_for_its_last_day(self):
		self.assertEqual(presence.day_asked_about(LAST_WEEK[0], LAST_WEEK[1], TODAY),
			"2026-09-18")

	def test_a_running_window_answers_for_today(self):
		"""So nothing a screen prints changes on a current plan -- which is what
		makes this safe to ship on a site that never backfills."""
		self.assertEqual(presence.day_asked_about(THIS_WEEK[0], THIS_WEEK[1], TODAY), TODAY)

	def test_a_future_window_answers_for_nothing(self):
		self.assertIsNone(presence.day_asked_about(NEXT_WEEK[0], NEXT_WEEK[1], TODAY))

	def test_a_past_window_is_recognised_as_one(self):
		self.assertTrue(presence.is_past_window(LAST_WEEK[0], LAST_WEEK[1], TODAY))
		self.assertFalse(presence.is_past_window(THIS_WEEK[0], THIS_WEEK[1], TODAY))


class TestTheMorningScanGateIsTheOneThingAboutToday(unittest.TestCase):
	def test_it_does_not_fire_on_a_past_window(self):
		"""The crew cannot have turned up this morning for work that finished
		last Friday, and refusing to staff it because they did not is the gate
		answering a question nobody asked."""
		self.assertFalse(presence.applies_today(LAST_WEEK[0], LAST_WEEK[1], TODAY))

	def test_it_fires_on_a_window_containing_today(self):
		self.assertTrue(presence.applies_today(THIS_WEEK[0], THIS_WEEK[1], TODAY))

	def test_it_does_not_fire_on_a_future_window(self):
		self.assertFalse(presence.applies_today(NEXT_WEEK[0], NEXT_WEEK[1], TODAY))

	def test_the_boundaries_count(self):
		self.assertTrue(presence.applies_today(TODAY, "2026-09-30", TODAY))
		self.assertTrue(presence.applies_today("2026-09-01", TODAY, TODAY))

	def test_a_missing_period_is_not_today(self):
		self.assertFalse(presence.applies_today(None, None, TODAY))


class TestTheAssignerAsksTheWindow(unittest.TestCase):
	"""The picker chips, the presence bar and the submit gate -- the three places
	that read `today` and should not have."""

	def setUp(self):
		self.src = api("assigner")

	def test_it_uses_the_shared_rule(self):
		self.assertIn("presence.evidence_window(", self.src)
		self.assertIn("presence.applies_today(", self.src)

	def picker_block(self):
		"""The chips' own presence reads, which is where the bug lived. The
		morning-scan gate in `a_submit` is a separate block and is meant to be
		bounded by today -- see the class below."""
		at = self.src.index("PRESENCE OVER THE WINDOW")
		return self.src[at:self.src.index("night_shifts =", at)]

	def test_no_presence_query_is_bounded_by_today(self):
		"""The exact shape of the bug: a single-date bound on a checkin or
		attendance read, where the plan has a window."""
		block = self.picker_block()
		for bad in ("DATE(`time`) = %s", "attendance_date = %s"):
			with self.subTest(clause=bad):
				self.assertNotIn(bad, block)

	def test_the_three_reads_are_bounded_by_the_window(self):
		self.assertEqual(self.picker_block().count("(pres_from, pres_to, emp_names2)"), 3)

	def test_the_payload_says_which_days_it_answered_for(self):
		"""A screen cannot print the right day unless it is told one."""
		self.assertIn('"presence_window"', self.src)
		self.assertIn('"is_today"', self.src)

	def test_the_morning_gate_still_asks_about_today(self):
		self.assertIn("includes_today = presence.applies_today(", self.src)
		self.assertIn('"checked": 1 if includes_today else 0', self.src)

	def test_the_submit_gate_is_the_only_read_left_bounded_by_today(self):
		"""a_submit's morning check reads `DATE(time) = g_today`, and should: it
		is the one rule about this morning. It is behind applies_today(), so a
		past window never reaches it."""
		at = self.src.index("MORNING PRESENCE gate:")
		block = self.src[at:self.src.index("for ce in emp_list:", at)]
		self.assertIn("presence.applies_today(gpf, gpt, g_today)", block)
		self.assertIn("DATE(`time`) = %s", block)


class TestTheActualsGridAsksEachCellsOwnDate(unittest.TestCase):
	"""Audited rather than changed: `act_detail` and the `act_submit` gate were
	already keyed on the work date. This pins that, so the fix cannot be undone
	from the other end."""

	def setUp(self):
		self.src = api("actuals")

	def test_the_grid_reads_the_windows_days(self):
		self.assertIn("presence.evidence_window(", self.src)
		self.assertIn("(wemps, ev_from, ev_to)", self.src)

	def test_no_presence_read_is_bounded_by_today(self):
		for bad in ("DATE(`time`) = %s", "attendance_date = %s"):
			with self.subTest(clause=bad):
				self.assertNotIn(bad, self.src)

	def test_the_submit_gate_keys_on_the_cells_date(self):
		"""`pd` is the date typed into the cell, and every lookup is keyed on
		(employee, pd)."""
		block = self.src[self.src.index("reasons_map = {}"):]
		block = block[:block.index("for ce in reasons_map:")]
		for keyed in ("absent_set.get((pe, pd))", "scan_set.get((pe, pd))",
				"present_set.get((pe, pd))"):
			with self.subTest(lookup=keyed):
				self.assertIn(keyed, block)

	def test_today_is_only_the_future_cutoff_in_that_gate(self):
		block = self.src[self.src.index("reasons_map = {}"):]
		block = block[:block.index("for ce in reasons_map:")]
		self.assertEqual(block.count("ns_today"), 1)
		self.assertIn("pd <= ns_today", block)

	def test_leave_is_judged_against_the_cells_date_too(self):
		block = self.src[self.src.index("reasons_map = {}"):]
		block = block[:block.index("for ce in reasons_map:")]
		self.assertIn("if lf <= pd <= lt:", block)


class TestTheDiscrepancyAuditJudgesTheWorkDate(unittest.TestCase):
	"""The presence rules in `pay_discrepancies`, audited. `wd` is the row's own
	`work_date`; `today_d` appears once, as the future cutoff for ghost days."""

	def setUp(self):
		self.src = api("payment")
		at = self.src.index("---- single pass: bucket rows into the presence-based checks ----")
		self.block = self.src[at:at + 3000]

	def test_presence_is_looked_up_by_the_rows_work_date(self):
		for keyed in ("scan_ev.get((r.employee, wd))", "att_ev.get((r.employee, wd))"):
			with self.subTest(lookup=keyed):
				self.assertIn(keyed, self.block)

	def test_leave_and_off_days_are_judged_against_it(self):
		self.assertIn("if lv[0] <= wd <= lv[1]:", self.block)
		self.assertIn("off_ev.get((hl_ev[r.employee], wd))", self.block)

	def test_today_is_only_the_ghost_day_cutoff(self):
		"""One use, and it is the future cutoff: a day that has not happened
		cannot be a ghost day."""
		self.assertIn('wd <= today_d and not rr["scan_in"]', self.block)
		uses = [line for line in self.block.splitlines()
			if "today_d" in line and "today_d = " not in line]
		self.assertEqual(len(uses), 1, uses)


class TestTheReviewSheetJudgesTheWorkDate(unittest.TestCase):
	"""The worker review sheet's daily log, audited: evidence keyed by the row's
	date, with no `today` anywhere in it."""

	def test_the_daily_log_keys_presence_on_the_rows_date(self):
		src = api("payment")
		at = src.index("# presence evidence per worked day")
		block = src[at:src.index('"day_off": ev_off.get(wd, 0)', at) + 40]
		for keyed in ('ev_scan.get(wd)', 'ev_att.get(wd)', 'ev_leave.get(wd)',
				'ev_off.get(wd, 0)'):
			with self.subTest(lookup=keyed):
				self.assertIn(keyed, block)
		self.assertNotIn("frappe.utils.today()", block)


class TestTheScreenSaysWhichDayItMeans(unittest.TestCase):
	"""A chip that says "A today" against a plan for last Tuesday is the bug
	restated in the browser."""

	def setUp(self):
		self.src = screen("work-assigner.js")

	def test_the_word_today_is_computed_not_written(self):
		self.assertIn("function presDayWord(", self.src)
		self.assertIn("si.is_today ?", self.src)

	def test_the_chips_use_it(self):
		block = self.src[self.src.index("var pday=presDayWord(si);"):]
		block = block[:block.index("var busy =")]
		self.assertEqual(block.count("presDayWord"), 1)
		for literal in ('">A today<', '">? today<'):
			with self.subTest(literal=literal):
				self.assertNotIn(literal, block)

	def test_the_presence_bar_names_the_day(self):
		at = self.src.index("if(ST.showToday) h+=")
		block = self.src[at:self.src.index("if(!list.length)", at)]
		self.assertIn("presDayWord(si)", block)
		self.assertNotIn("marked present today", block)

	def test_a_multi_day_window_reports_how_much_of_it(self):
		self.assertIn("function presSpanWord(", self.src)
		self.assertIn("present_days", self.src)

	def test_the_not_seen_warning_still_says_today(self):
		"""Because the gate behind it IS about today, and only fires when the
		window contains it."""
		at = self.src.index("function attReasons(")
		block = self.src[at:at + 1600]
		self.assertIn("si.checked", block)
		self.assertIn("not seen on site today", block)


class TestNoAttendancePathStillAsksTheClock(unittest.TestCase):
	"""The sweep the brief asked for, as a standing check: every `today` left in
	an attendance read has to be one of the two that belong there."""

	#: `frappe.utils.today()` calls inside the presence blocks, and why each is
	#: allowed. Anything else is a relapse.
	ALLOWED = {
		"assigner": 1,   # today_str -> the morning gate + the window's clip
		"actuals": 2,    # the evidence window's clip, and the no-scan future cutoff
	}

	def test_each_presence_block_holds_only_the_calls_it_should(self):
		blocks = {
			"assigner": ("PRESENCE OVER THE WINDOW", "night_shifts ="),
			"actuals": ("PRESENCE PER WORKER-DAY", 'a["workers"] = workers'),
		}
		for module, (start, end) in blocks.items():
			src = api(module)
			at = src.index(start)
			block = src[at:src.index(end, at)]
			with self.subTest(module=module):
				self.assertEqual(block.count("frappe.utils.today()"),
					self.ALLOWED[module],
					"a presence read in api/%s.py asks the clock: %r" % (module, block))

	def test_no_attendance_query_uses_the_database_clock(self):
		"""`CURDATE()` / `NOW()` would put the same fault below the Python."""
		for module in ("assigner", "actuals", "payment"):
			src = api(module)
			for bad in ("CURDATE()", "CURRENT_DATE"):
				with self.subTest(module=module, clause=bad):
					self.assertNotIn(bad, src)


if __name__ == "__main__":
	unittest.main()
