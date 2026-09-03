"""A day split between two tasks is one day, and the arithmetic has to say so.

Until now a day was atomic: an actuals row said worker, date, task and how much,
never how long. So man-days could only ever be counted --

    COUNT(DISTINCT CONCAT(we.employee, '|', we.work_date))

-- which is right while a worker can be on one task a day, and wrong the moment
they can be on two. The same worker on two assignments for 12 August counts as
two man-days at farm level, a plan for ten people cannot take ten half-day
workers, and a half-day worker misses a full day's `daily_target` and reads as
underperforming.

So the day stops being counted and starts being measured. `hours` on the actuals
row, against the standard hours for that date, and every figure derives from the
ratio.

The properties that matter most are the boring ones: an ordinary unsplit day must
come out exactly as it does today, or this cannot be deployed against 30,833
existing rows.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_split_day -v
"""

import unittest

from work_management import split_day

# 12 Aug 2026 is a Wednesday, 15 Aug a Saturday, 16 Aug a Sunday.
WED, SAT, SUN = "2026-08-12", "2026-08-15", "2026-08-16"


class TestTheStandardDay(unittest.TestCase):
	def test_a_weekday_is_eight_hours(self):
		self.assertEqual(split_day.standard_hours(WED), 8)

	def test_saturday_is_six(self):
		self.assertEqual(split_day.standard_hours(SAT), 6)

	def test_sunday_is_a_working_day_here(self):
		"""Sunday is worked on these farms, so it is eight and not zero. A zero
		would make every Sunday man-day a division by zero."""
		self.assertEqual(split_day.standard_hours(SUN), 8)

	def test_a_site_can_say_otherwise(self):
		model = {"weekday": 6, "saturday": 4, "sunday": 0}
		self.assertEqual(split_day.standard_hours(WED, model), 6)
		self.assertEqual(split_day.standard_hours(SAT, model), 4)

	def test_a_zero_standard_never_divides(self):
		"""A site that says Sunday is not worked must not crash on a Sunday row."""
		model = {"weekday": 8, "saturday": 6, "sunday": 0}
		self.assertEqual(split_day.man_days([(SUN, 8)], model), 0)

	def test_a_date_object_works_as_well_as_a_string(self):
		import datetime

		self.assertEqual(split_day.standard_hours(datetime.date(2026, 8, 15)), 6)


class TestAnOrdinaryDayIsUnchanged(unittest.TestCase):
	"""The property that makes this deployable."""

	def test_one_full_day_is_one_man_day(self):
		self.assertEqual(split_day.man_days([(WED, 8)]), 1.0)

	def test_five_full_days_are_five(self):
		self.assertEqual(split_day.man_days([(WED, 8)] * 5), 5.0)

	def test_a_full_saturday_is_one_man_day_not_six_eighths(self):
		"""Six hours IS the whole day on a Saturday."""
		self.assertEqual(split_day.man_days([(SAT, 6)]), 1.0)


class TestASplitDay(unittest.TestCase):
	def test_two_halves_are_one_man_day(self):
		self.assertEqual(split_day.man_days([(WED, 4), (WED, 4)]), 1.0)

	def test_an_uneven_split_still_totals_one(self):
		self.assertEqual(split_day.man_days([(WED, 1), (WED, 7)]), 1.0)

	def test_three_ways(self):
		self.assertEqual(split_day.man_days([(WED, 2), (WED, 2), (WED, 4)]), 1.0)

	def test_a_short_day_is_less_than_one(self):
		"""Somebody may simply have worked four hours and gone home."""
		self.assertEqual(split_day.man_days([(WED, 4)]), 0.5)

	def test_an_over_long_day_is_more_than_one(self):
		"""Recorded, not clamped: clamping would make an overrun look like a fit."""
		self.assertEqual(split_day.man_days([(WED, 5), (WED, 5)]), 1.25)


class TestMissingHoursFallBackToTheStandard(unittest.TestCase):
	"""30,833 rows predate the field. A null must read as a full day, which is
	what those rows have always meant, not as zero."""

	def test_none_hours_count_as_a_full_day(self):
		self.assertEqual(split_day.man_days([(WED, None)]), 1.0)

	def test_a_null_saturday_is_a_full_saturday(self):
		self.assertEqual(split_day.man_days([(SAT, None)]), 1.0)

	def test_zero_is_respected_as_zero(self):
		"""Explicitly zero is a real answer and must not be read as absent."""
		self.assertEqual(split_day.man_days([(WED, 0)]), 0.0)


class TestTheCrewLimit(unittest.TestCase):
	"""The assigner refuses more workers than the plan budgets. It compared
	people, so two half-days read as two people and a plan for ten could take
	only five split workers."""

	def test_ten_full_days_fill_a_plan_for_ten(self):
		self.assertEqual(split_day.person_days([(WED, 8)] * 10), 10.0)

	def test_twenty_half_days_also_fill_a_plan_for_ten(self):
		self.assertEqual(split_day.person_days([(WED, 4)] * 20), 10.0)

	def test_it_is_the_same_measure_as_man_days(self):
		rows = [(WED, 4), (WED, 4), (SAT, 6)]
		self.assertEqual(split_day.person_days(rows), split_day.man_days(rows))


class TestTheDailyTarget(unittest.TestCase):
	def test_a_full_day_expects_the_whole_target(self):
		self.assertEqual(split_day.prorated_target(150, 8, WED), 150.0)

	def test_a_half_day_expects_half(self):
		self.assertEqual(split_day.prorated_target(150, 4, WED), 75.0)

	def test_a_full_saturday_expects_the_whole_target(self):
		"""Six hours is a whole Saturday, so the target is not cut to six eighths."""
		self.assertEqual(split_day.prorated_target(150, 6, SAT), 150.0)

	def test_no_target_stays_no_target(self):
		self.assertEqual(split_day.prorated_target(0, 4, WED), 0.0)

	def test_absent_hours_expect_the_whole_target(self):
		self.assertEqual(split_day.prorated_target(150, None, WED), 150.0)


class TestTheFlags(unittest.TestCase):
	def test_a_day_over_its_standard_is_long(self):
		self.assertTrue(split_day.is_long_day([(WED, 5), (WED, 5)]))

	def test_an_exact_day_is_not_long(self):
		self.assertFalse(split_day.is_long_day([(WED, 4), (WED, 4)]))

	def test_a_short_day_is_not_long(self):
		self.assertFalse(split_day.is_long_day([(WED, 3)]))

	def test_a_full_saturday_is_not_long(self):
		self.assertFalse(split_day.is_long_day([(SAT, 6)]))

	def test_rows_spanning_dates_are_judged_per_date(self):
		"""Two ordinary full days are not one sixteen-hour day. Taking the
		standard from the first row and summing the rest was the shape of the
		bug this catches."""
		self.assertFalse(split_day.is_long_day([(WED, 8), ("2026-08-13", 8)]))

	def test_one_long_date_among_ordinary_ones_is_found(self):
		self.assertTrue(split_day.is_long_day(
			[(WED, 8), ("2026-08-13", 5), ("2026-08-13", 5)]))

	def test_a_long_saturday_is_judged_against_six(self):
		self.assertTrue(split_day.is_long_day([(SAT, 4), (SAT, 4)]))

	def test_no_rows_is_not_a_long_day(self):
		self.assertFalse(split_day.is_long_day([]))

	def test_half_the_output_in_half_the_time_is_not_flagged(self):
		"""An ordinary half day. Flagging it would make the flag noise."""
		self.assertFalse(split_day.output_disagrees_with_hours(75, 150, 4, WED))

	def test_a_full_day_of_output_in_three_hours_is_flagged(self):
		"""Either the hours are wrong or the quantity is."""
		self.assertTrue(split_day.output_disagrees_with_hours(150, 150, 3, WED))

	def test_a_full_day_of_output_in_a_full_day_is_not_flagged(self):
		self.assertFalse(split_day.output_disagrees_with_hours(150, 150, 8, WED))

	def test_less_output_than_time_is_not_this_flag(self):
		"""Under-performance is a different question and has its own reporting;
		this flag is for hours and output contradicting each other."""
		self.assertFalse(split_day.output_disagrees_with_hours(10, 150, 8, WED))

	def test_no_target_cannot_disagree(self):
		self.assertFalse(split_day.output_disagrees_with_hours(50, 0, 4, WED))

	def test_hours_and_quantity_must_agree_on_an_hourly_task(self):
		"""The user chose to type hours on every split row, including tasks already
		measured in Hour -- 34 of them, and 497 of the planners. So the same number
		is typed twice there and can be typed twice differently."""
		self.assertTrue(split_day.hourly_task_mismatch(4, 5, "Hour"))
		self.assertFalse(split_day.hourly_task_mismatch(4, 4, "Hour"))
		self.assertFalse(split_day.hourly_task_mismatch(3, 4, "Tree"),
			"a Tree task's quantity has nothing to do with its hours")

	def test_the_hourly_check_tolerates_rounding(self):
		self.assertFalse(split_day.hourly_task_mismatch(4.0, 4.004, "Hour"))

	def test_the_hourly_check_knows_the_other_spellings(self):
		"""The catalogue carries `Hour` and `HR`."""
		self.assertTrue(split_day.hourly_task_mismatch(4, 6, "HR"))


if __name__ == "__main__":
	unittest.main()


class TestTheMirrorMeasuresRatherThanCounts(unittest.TestCase):
	"""The man-day query itself, not just the arithmetic beside it.

	`COUNT(DISTINCT CONCAT(we.employee, '|', we.work_date))` is exact while a
	worker gives a whole day to one task and wrong the moment they can give it to
	two. It is also invisible to every unit test in this file, because it lives
	in SQL -- so this reads the source.

	Verified neutral on real data before it went in: on kaitet.local's 256
	plan/farm groups the old and new queries agreed to the third decimal, totals
	4,810.000 either way. That is the property that made it deployable.
	"""

	MIRROR = "/home/austin/vscodeProjects/kaitet-work-management/server_scripts"

	def setUp(self):
		import os

		if not os.path.isdir(self.MIRROR):
			self.skipTest("mirror not present")
		with open(os.path.join(self.MIRROR, "wm_dashboard.py")) as handle:
			self.text = handle.read()

	def test_man_days_are_no_longer_counted(self):
		self.assertNotIn("CONCAT(we.employee, '|', we.work_date)) mandays", self.text,
			"man-days are still a count of distinct worker-days, so a split day "
			"counts twice")

	def test_man_days_read_the_hours_column(self):
		self.assertIn("we.hours", self.text)

	def test_an_absent_hour_falls_back_to_the_standard(self):
		"""And zero is the absent state, not null.

		Frappe makes a Float column NOT NULL DEFAULT 0, so an unfilled row holds
		0. A bare COALESCE would read that as zero hours and count a real day as
		no labour at all -- which is why this asserts the NULLIF."""
		self.assertRegex(self.text, r"COALESCE\(NULLIF\(we\.hours, 0\),\s*CASE DAYOFWEEK")

	def test_it_cannot_divide_by_a_zero_length_day(self):
		"""A site that says Sunday is not worked must not make the query fail."""
		self.assertIn("NULLIF(CASE DAYOFWEEK", self.text)

	def test_the_hours_model_is_one_value_not_three_loose_ones(self):
		"""WEEKDAY_HOURS / SATURDAY_HOURS / SUNDAY_HOURS were declared in five
		scripts and read in one. Two models drift; the port only rebuilds one."""
		import glob
		import os

		for path in glob.glob(os.path.join(self.MIRROR, "wm_*.py")):
			with open(path) as handle:
				text = handle.read()
			with self.subTest(script=os.path.basename(path)):
				for dead in ("WEEKDAY_HOURS", "SATURDAY_HOURS", "SUNDAY_HOURS"):
					self.assertNotIn(dead, text,
						"%s still carries the old loose hours constant %s"
						% (os.path.basename(path), dead))


class TestAWholeDayIsNeverAContradiction(unittest.TestCase):
	"""Found by running the check against real data: it returned 162 rows on
	kaitet.local and every one was somebody beating their target across a full
	day. Productive is not contradictory."""

	def test_beating_the_target_in_a_full_day_is_not_flagged(self):
		self.assertFalse(split_day.output_disagrees_with_hours(225, 150, 8, WED))

	def test_beating_it_in_a_full_saturday_is_not_flagged(self):
		self.assertFalse(split_day.output_disagrees_with_hours(225, 150, 6, SAT))

	def test_a_full_day_of_output_in_three_hours_still_is(self):
		self.assertTrue(split_day.output_disagrees_with_hours(150, 150, 3, WED))

	def test_double_the_target_in_half_the_day_still_is(self):
		self.assertTrue(split_day.output_disagrees_with_hours(300, 150, 4, WED))
