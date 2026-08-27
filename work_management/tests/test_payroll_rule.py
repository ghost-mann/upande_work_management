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


class TestWhichPayWeekADayBelongsTo(unittest.TestCase):
	"""Two ways to send: grouped into pay weeks, which is the default and what
	payroll has always received, or one payment per day when somebody ticks the
	box in Settings.

	Weekly grouping has a hole. A pay week shorter than seven days leaves a
	weekday belonging to no week at all -- on the live Tuesday-to-Sunday week
	that is Monday, and the bulk send dropped those dates silently: 5,027 lines,
	KES 1.78m, 943 workers, unsendable and unreported. Per-day sending has no
	such hole, because every date is its own week.
	"""

	# weekday indices: Mon=0 .. Sun=6. Live config is start=Tuesday(1),
	# end=Sunday(6) -- six days, so Monday is the orphan.
	TUE_START, SIX_DAYS = 1, 6

	# ---- weekly, the default ------------------------------------------------
	def test_weekly_puts_a_day_in_its_week(self):
		self.assertEqual(rule.pay_week_for(1, self.TUE_START, self.SIX_DAYS, False), (0, 6))
		self.assertEqual(rule.pay_week_for(6, self.TUE_START, self.SIX_DAYS, False), (5, 6))

	def test_weekly_cannot_place_the_orphan_weekday(self):
		"""Monday, on a Tuesday-to-Sunday week. This is the reported bug, and
		weekly mode still cannot send it -- but the caller now reports it."""
		self.assertIsNone(rule.pay_week_for(0, self.TUE_START, self.SIX_DAYS, False))

	def test_a_seven_day_week_orphans_nobody(self):
		for wd in range(7):
			self.assertIsNotNone(rule.pay_week_for(wd, 0, 7, False), wd)

	# ---- per day, when the box is ticked ------------------------------------
	def test_per_day_gives_every_day_its_own_payment(self):
		for wd in range(7):
			self.assertEqual(rule.pay_week_for(wd, self.TUE_START, self.SIX_DAYS, True), (0, 1), wd)

	def test_per_day_reaches_the_day_weekly_could_not(self):
		"""Monday sends under per-day, which is the point of the checkbox."""
		self.assertIsNone(rule.pay_week_for(0, self.TUE_START, self.SIX_DAYS, False))
		self.assertEqual(rule.pay_week_for(0, self.TUE_START, self.SIX_DAYS, True), (0, 1))

	def test_per_day_ignores_the_configured_week_entirely(self):
		"""Whatever the week is set to, per-day is one day. Otherwise the two
		settings would interact and nobody could predict the grouping."""
		for start in range(7):
			for length in (1, 3, 6, 7):
				self.assertEqual(rule.pay_week_for(4, start, length, True), (0, 1))

	def test_a_one_day_pay_week_still_works_weekly(self):
		self.assertEqual(rule.pay_week_for(3, 3, 1, False), (0, 1))
		self.assertIsNone(rule.pay_week_for(4, 3, 1, False))
