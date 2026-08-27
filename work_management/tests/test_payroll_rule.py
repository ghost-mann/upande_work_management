"""Guards on the task-worker rule and on spotting rows it no longer agrees with.

Pure: settings text and employee fields in, verdicts out. No site::

    ./env/bin/python -m unittest work_management.tests.test_payroll_rule -v
"""

import unittest

from work_management import payroll_rule as rule


class TestReadingTheConfiguredLists(unittest.TestCase):
	"""These are free-text boxes whose contents are interpolated into SQL. A
	newline in one of them once took the whole list down silently and stopped
	315 task workers being payable, so how the text is read is the part that
	has actually broken in production.
	"""

	def test_a_comma_separated_list_is_read(self):
		self.assertEqual(rule.parse_list("Contract, Permanent"), {"Contract", "Permanent"})

	def test_a_newline_separated_list_is_read_too(self):
		"""The regression that stopped 315 people being paid."""
		self.assertEqual(rule.parse_list("Task Worker\nSecurity Guard"),
			{"Task Worker", "Security Guard"})

	def test_a_windows_newline_is_read_too(self):
		self.assertEqual(rule.parse_list("Task Worker\r\nSecurity Guard"),
			{"Task Worker", "Security Guard"})

	def test_padding_is_trimmed(self):
		self.assertEqual(rule.parse_list("  Contract  ,  Permanent "), {"Contract", "Permanent"})

	def test_an_empty_box_reads_as_nothing(self):
		self.assertEqual(rule.parse_list(""), set())
		self.assertEqual(rule.parse_list(None), set())

	def test_a_value_that_could_break_out_of_the_sql_is_dropped(self):
		"""Dropped on its own -- never taking the rest of the list with it."""
		self.assertEqual(rule.parse_list("Contract, Rob'; drop table--, Permanent"),
			{"Contract", "Permanent"})

	def test_the_punctuation_a_job_title_really_uses_is_kept(self):
		self.assertEqual(rule.parse_list("Cook / Cleaner, Director's Aide, Fixed-Term"),
			{"Cook / Cleaner", "Director's Aide", "Fixed-Term"})


class TestWhoQualifies(unittest.TestCase):
	"""Any one of the three lists is enough -- they are ORed, not ANDed."""

	RULE = {"employment_type": {"Contract"},
		"designation": {"Task Worker", "Security Guard"},
		"custom_category": {"Value Adder"}}

	def test_the_employment_type_alone_qualifies(self):
		self.assertTrue(rule.qualifies({"employment_type": "Contract"}, self.RULE))

	def test_the_designation_alone_qualifies(self):
		"""626 people are carried by this and nothing else."""
		self.assertTrue(rule.qualifies(
			{"employment_type": "Task Worker", "designation": "Task Worker"}, self.RULE))

	def test_the_category_alone_qualifies(self):
		self.assertTrue(rule.qualifies(
			{"employment_type": "Permanent", "custom_category": "Value Adder"}, self.RULE))

	def test_matching_nothing_does_not_qualify(self):
		self.assertFalse(rule.qualifies(
			{"employment_type": "Permanent", "designation": "Supervisor",
			 "custom_category": "Team Leader"}, self.RULE))

	def test_a_missing_field_is_not_a_match(self):
		self.assertFalse(rule.qualifies({}, self.RULE))

	def test_an_empty_rule_never_qualifies_anyone(self):
		"""Fail closed. A blank or unusable Settings must not pay everyone."""
		self.assertFalse(rule.qualifies({"employment_type": "Contract"},
			{"employment_type": set(), "designation": set(), "custom_category": set()}))


class TestSpottingRowsTheRuleNoLongerAgreesWith(unittest.TestCase):
	"""count_in_payroll is decided once, when the row is written, and never
	revisited. Change an employee's classification or the lists in Settings and
	every row already recorded keeps the old answer -- silently, at zero. This
	is what nobody had: a way to see that it happened.
	"""

	RULE = {"employment_type": {"Contract"}, "designation": set(), "custom_category": set()}
	PEOPLE = {"400617": {"employment_type": "Contract"},
		"400001": {"employment_type": "Permanent"}}

	def row(self, employee, flag):
		return {"name": f"r-{employee}-{flag}", "employee": employee, "count_in_payroll": flag}

	def test_a_row_left_out_of_payroll_whose_employee_now_qualifies_is_reported(self):
		found = rule.disagreements([self.row("400617", 0)], self.RULE, self.PEOPLE)
		self.assertEqual([r["employee"] for r in found], ["400617"])
		self.assertEqual(found[0]["stored"], 0)
		self.assertEqual(found[0]["expected"], 1)

	def test_a_row_in_payroll_whose_employee_no_longer_qualifies_is_reported(self):
		"""The other direction matters too -- that one is money going out."""
		found = rule.disagreements([self.row("400001", 1)], self.RULE, self.PEOPLE)
		self.assertEqual(found[0]["expected"], 0)

	def test_rows_the_rule_still_agrees_with_are_not_reported(self):
		rows = [self.row("400617", 1), self.row("400001", 0)]
		self.assertEqual(rule.disagreements(rows, self.RULE, self.PEOPLE), [])

	def test_an_employee_the_lookup_does_not_know_is_left_alone(self):
		"""Not guessed at: a deleted employee is a different problem."""
		self.assertEqual(rule.disagreements([self.row("999", 0)], self.RULE, {}), [])


class TestReadingEitherShape(unittest.TestCase):
	"""The three lists are moving from free text to picked values, and payroll
	cannot be down for a moment in between. So the reader accepts both: child
	rows if the table has any, otherwise the legacy text. Every intermediate
	state -- code deployed but tables empty, tables filled but text still there
	-- resolves to the same rule.
	"""

	def settings(self, **kw):
		base = {"tw_employment_types": "", "tw_designations": "", "tw_categories": "",
			"tw_employment_type_rows": [], "tw_designation_rows": [], "tw_category_rows": []}
		base.update(kw)
		return base

	def test_the_legacy_text_is_still_read_when_no_rows_exist(self):
		"""The state live is in today. Nothing may change for it."""
		r = rule.rule_from(self.settings(tw_employment_types="Contract",
			tw_designations="Task Worker\nSecurity Guard", tw_categories="Value Adder"))
		self.assertEqual(r["employment_type"], {"Contract"})
		self.assertEqual(r["designation"], {"Task Worker", "Security Guard"})
		self.assertEqual(r["custom_category"], {"Value Adder"})

	def test_picked_rows_are_read_when_they_exist(self):
		r = rule.rule_from(self.settings(
			tw_employment_type_rows=[{"employment_type": "Contract"}],
			tw_designation_rows=[{"designation": "Task Worker"}, {"designation": "Security Guard"}],
			tw_category_rows=[{"category": "Value Adder"}]))
		self.assertEqual(r["employment_type"], {"Contract"})
		self.assertEqual(r["designation"], {"Task Worker", "Security Guard"})
		self.assertEqual(r["custom_category"], {"Value Adder"})

	def test_rows_win_over_leftover_text(self):
		"""Once a list is picked, the old text is history -- not an addition."""
		r = rule.rule_from(self.settings(tw_employment_types="Permanent, Intern",
			tw_employment_type_rows=[{"employment_type": "Contract"}]))
		self.assertEqual(r["employment_type"], {"Contract"})

	def test_the_two_shapes_can_be_mixed_per_list(self):
		"""Migrating one list at a time must not disturb the others."""
		r = rule.rule_from(self.settings(
			tw_employment_type_rows=[{"employment_type": "Contract"}],
			tw_designations="Task Worker"))
		self.assertEqual(r["employment_type"], {"Contract"})
		self.assertEqual(r["designation"], {"Task Worker"})

	def test_blank_rows_are_ignored_rather_than_matching_everyone(self):
		r = rule.rule_from(self.settings(tw_employment_type_rows=[{"employment_type": ""},
			{"employment_type": None}], tw_employment_types="Contract"))
		self.assertEqual(r["employment_type"], {"Contract"})

	def test_a_picked_value_needs_no_character_check(self):
		"""A Link value is a docname, not typing. Apostrophes stay."""
		r = rule.rule_from(self.settings(
			tw_designation_rows=[{"designation": "Director's Aide"}]))
		self.assertEqual(r["designation"], {"Director's Aide"})

	def test_nothing_configured_anywhere_qualifies_nobody(self):
		r = rule.rule_from(self.settings())
		self.assertFalse(rule.qualifies({"employment_type": "Contract"}, r))


class TestWhatOneSendCovers(unittest.TestCase):
	"""Two ways to send: grouped into pay weeks, which is the default and what
	payroll has always received, or a span of days somebody chose -- one day, a
	fortnight, whatever the range is -- once Settings offers it.

	Weekly grouping has a hole. A pay week shorter than seven days leaves a
	weekday belonging to no week at all -- on the live Tuesday-to-Sunday week
	that is Monday, and the bulk send dropped those dates silently: 5,027 lines,
	KES 1.78m, 943 workers, unsendable and unreported. A chosen span has no such
	hole, because it starts on the date chosen rather than on a weekday the
	configuration favours.
	"""

	# weekday indices: Mon=0 .. Sun=6. Live config is start=Tuesday(1),
	# end=Sunday(6) -- six days, so Monday is the orphan.
	TUE_START, SIX_DAYS = 1, 6

	# ---- pay weeks, always available ---------------------------------------
	def test_a_pay_week_puts_a_day_in_its_week(self):
		self.assertEqual(rule.send_window(1, self.TUE_START, self.SIX_DAYS), (0, 6))
		self.assertEqual(rule.send_window(6, self.TUE_START, self.SIX_DAYS), (5, 6))

	def test_a_pay_week_cannot_place_the_orphan_weekday(self):
		"""Monday, on a Tuesday-to-Sunday week. This is the reported bug, and
		week mode still cannot place it -- but the caller now reports it instead
		of dropping it, and a chosen span can send it."""
		self.assertIsNone(rule.send_window(0, self.TUE_START, self.SIX_DAYS))

	def test_a_seven_day_week_orphans_nobody(self):
		for wd in range(7):
			self.assertIsNotNone(rule.send_window(wd, 0, 7), wd)

	def test_a_one_day_pay_week_still_works(self):
		self.assertEqual(rule.send_window(3, 3, 1), (0, 1))
		self.assertIsNone(rule.send_window(4, 3, 1))

	# ---- a chosen span of days ---------------------------------------------
	def test_one_day_is_a_span_of_one(self):
		""""Send just this day" is not a special mode -- it is the smallest
		span, so it needs no code of its own."""
		for wd in range(7):
			self.assertEqual(rule.send_window(wd, self.TUE_START, self.SIX_DAYS, 1), (0, 1), wd)

	def test_a_span_can_be_any_length(self):
		for days in (1, 2, 3, 5, 6, 7, 10, 14, 31):
			self.assertEqual(rule.send_window(2, self.TUE_START, self.SIX_DAYS, days), (0, days))

	def test_a_span_starts_at_the_range_start_not_a_weekday(self):
		"""The operator picked the range; snapping it to the configured week
		would pay days they did not choose and leave out days they did. So the
		first day of the range opens the window whatever weekday it is."""
		for wd in range(7):
			back, length = rule.send_window(wd, self.TUE_START, self.SIX_DAYS, 5, 0)
			self.assertEqual((back, length), (0, 5), wd)

	def test_a_span_tiles_forward_from_the_range_start(self):
		"""Five-day spans over a range: days 0-4 belong to the first window,
		days 5-9 to the second. Without this every date would open a window of
		its own, the windows would overlap, and two of them would claim the same
		row -- whichever the database returned first would win."""
		for offset in range(10):
			back, length = rule.send_window(3, self.TUE_START, self.SIX_DAYS, 5, offset)
			self.assertEqual(length, 5)
			self.assertEqual(back, offset % 5, offset)

	def test_windows_of_a_span_never_overlap(self):
		"""Every date in a long range resolves to exactly one window start."""
		starts = set()
		for offset in range(30):
			back, length = rule.send_window(offset % 7, self.TUE_START, self.SIX_DAYS, 7, offset)
			starts.add(offset - back)
		self.assertEqual(sorted(starts), [0, 7, 14, 21, 28])

	def test_a_single_day_needs_no_anchor(self):
		for offset in (0, 1, 5, 99, None):
			self.assertEqual(rule.send_window(4, self.TUE_START, self.SIX_DAYS, 1, offset), (0, 1))

	def test_a_span_reaches_the_day_a_pay_week_could_not(self):
		"""Monday sends as a span, which is the whole point of offering one."""
		self.assertIsNone(rule.send_window(0, self.TUE_START, self.SIX_DAYS))
		self.assertEqual(rule.send_window(0, self.TUE_START, self.SIX_DAYS, 1), (0, 1))

	def test_a_span_ignores_the_configured_week_entirely(self):
		"""Whatever the week is set to, a chosen span is what was chosen.
		Otherwise the two would interact and nobody could predict the grouping."""
		for start in range(7):
			for length in (1, 3, 6, 7):
				self.assertEqual(rule.send_window(4, start, length, 4), (0, 4))


class TestChoosingHowASendGroups(unittest.TestCase):
	"""Two independent things: whether spans are OFFERED at all, which is a
	Settings decision, and what THIS send covers, which is the operator's. So a
	site can offer both and let the person sending choose, or offer pay weeks
	only.

	Pay weeks are always available. Enabling spans adds an option; it never
	takes the weekly one away, and an ordinary send behaves exactly as before.

	None means "the configured pay week". A number means "this many days,
	starting on the date sent" -- 1 for a single day, 5 for a working week, 14
	for a fortnight.
	"""

	def test_a_site_offering_only_pay_weeks_sends_the_pay_week(self):
		self.assertEqual(rule.send_span(None, False), (None, None))

	def test_a_site_offering_spans_still_sends_the_pay_week_by_default(self):
		"""The point of offering both: enabling spans must not change what an
		ordinary send does."""
		self.assertEqual(rule.send_span(None, True), (None, None))

	def test_one_day_where_spans_are_offered(self):
		self.assertEqual(rule.send_span(1, True), (1, None))

	def test_any_number_of_days_where_spans_are_offered(self):
		for days in (1, 2, 3, 4, 5, 6, 7, 9, 14, 30, 31):
			self.assertEqual(rule.send_span(days, True), (days, None))

	def test_asking_for_a_span_where_it_is_not_offered_is_refused(self):
		"""Refused, not quietly sent as a pay week. The operator asked to pay a
		particular range; a pay week would hand payroll different documents,
		covering different dates, without anyone noticing."""
		days, error = rule.send_span(1, False)
		self.assertIsNone(days)
		self.assertTrue(error)
		self.assertIn("Settings", error)

	def test_zero_days_means_nobody_chose_a_span(self):
		"""A form sends 0 for a field left alone, so 0 has to mean "no span
		asked for" and fall through to the pay week. Refusing it would break an
		ordinary weekly send on any screen that posts its unset fields."""
		self.assertEqual(rule.send_span(0, True), (None, None))
		self.assertEqual(rule.send_span(0, False), (None, None))

	def test_a_negative_span_is_refused(self):
		"""Unlike 0, a negative can only be a mistake -- no unset field sends
		one -- and it would ask for a window that ends before it starts."""
		for bad in (-1, -7):
			days, error = rule.send_span(bad, True)
			self.assertIsNone(days, bad)
			self.assertTrue(error, bad)

	def test_a_span_longer_than_a_month_is_refused(self):
		"""Open-ended, but not unbounded. A mistyped 3650 would sweep ten years
		of work into one payment, and a payment already sent is the expensive
		thing to undo. A month is longer than any pay period this pays on."""
		self.assertEqual(rule.send_span(rule.MAX_SPAN_DAYS, True)[0], rule.MAX_SPAN_DAYS)
		days, error = rule.send_span(rule.MAX_SPAN_DAYS + 1, True)
		self.assertIsNone(days)
		self.assertIn(str(rule.MAX_SPAN_DAYS), error)

	def test_something_that_is_not_a_number_of_days_is_refused(self):
		for bad in ("week", "3.5.1", "abc"):
			days, error = rule.send_span(bad, True)
			self.assertIsNone(days, bad)
			self.assertTrue(error, bad)

	def test_a_multi_day_span_needs_a_range_to_start_from(self):
		"""Choosing an anchor on its behalf would put one day on different
		payments for different workers, and re-running the send would draw the
		boundaries somewhere else."""
		days, error = rule.send_span(5, True, anchored=False)
		self.assertIsNone(days)
		self.assertTrue(error)

	def test_a_single_day_span_needs_no_range(self):
		"""One day is the same window wherever it is tiled from."""
		self.assertEqual(rule.send_span(1, True, anchored=False), (1, None))

	def test_the_values_are_read_loosely(self):
		"""They arrive as strings from a form and as numbers from the database."""
		self.assertEqual(rule.send_span("5", 1), (5, None))
		self.assertEqual(rule.send_span(" 5 ", "1"), (5, None))
		self.assertEqual(rule.send_span("", 1), (None, None))
		self.assertEqual(rule.send_span("0", 1)[0], None)
		self.assertEqual(rule.send_span(None, None), (None, None))
