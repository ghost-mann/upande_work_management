"""Three checks the audit could not ask before hours existed.

A day was atomic, so "did this day add up to more than a day" and "do the hours
and the output contradict each other" had no answer. They do now, and they join
the eleven existing discrepancy checks -- same catalogue, same per-check
Settings toggle, same row shape.

Every threshold here was set by running the check against real data and looking
at what came back, not by choosing a number that sounded careful. All three were
wrong first time:

    hours_vs_qty  309 rows, every one this project's own backfill putting a
                  date's standard against an hourly row whose quantity already
                  recorded the hours. Fixed in the backfill, not the check: an
                  Hour-unit task's quantity IS its hours.

    long_day      337 rows, because a single row was compared against the site
                  standard -- and some tasks run longer by design. Security
                  Patroll's daily target is 12 hours, Coffee Picking's is 3. Now
                  only a date with more than one row can be too long, which is
                  the split day this check was asked for. 337 -> 34.

    short_day     162 rows, every one somebody beating their target across a
                  full day. Productive is not contradictory, so a day that was
                  essentially whole is out of scope.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_the_hours_audit_flags -v
"""

import json
import os
import re
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(APP, "work_management", "doctype",
	"work_management_settings", "work_management_settings.json")
MIRROR = "/home/austin/vscodeProjects/kaitet-work-management/server_scripts"

FLAGS = (
	("long_day", "disc_long_day"),
	("short_day", "disc_short_day"),
	("hours_vs_qty", "disc_hours_vs_qty"),
)


def payment_source():
	with open(os.path.join(MIRROR, "wm_payment.py")) as handle:
		return handle.read()


class TestTheMirrorIsCheckedOut(unittest.TestCase):
	def setUp(self):
		if not os.path.isdir(MIRROR):
			self.skipTest("mirror not present")
		self.text = payment_source()


class TestEachFlagIsWiredAllTheWayThrough(TestTheMirrorIsCheckedOut):
	"""Four places, and a flag missing from any one of them half-works: it would
	appear and ignore its switch, or be switchable and never appear."""

	def test_each_is_in_the_check_catalogue(self):
		for key, _field in FLAGS:
			with self.subTest(key=key):
				self.assertIn('"key": "%s"' % key, self.text)

	def test_each_says_what_it_means(self):
		"""The `about` text is what somebody reads when deciding whether a row is
		a problem. A check without one is a number nobody can act on."""
		for key, _field in FLAGS:
			at = self.text.index('"key": "%s"' % key)
			with self.subTest(key=key):
				self.assertIn('"about"', self.text[at:at + 400])

	def test_each_is_in_the_toggle_map(self):
		for key, field in FLAGS:
			with self.subTest(key=key):
				self.assertRegex(self.text, r'"%s":\s*"%s"' % (key, field))

	def test_each_toggle_is_loaded_from_settings(self):
		"""In the map but not in the load tuple means get_single_value is never
		called for it, and the default wins forever."""
		at = self.text.index("disc_on = {}")
		window = self.text[at:at + 800]
		for _key, field in FLAGS:
			with self.subTest(field=field):
				self.assertIn('"%s"' % field, window)

	def test_each_has_a_checkbox_somebody_can_find(self):
		with open(SETTINGS) as handle:
			fields = {f["fieldname"]: f for f in json.load(handle).get("fields", [])}
		with open(SETTINGS) as handle:
			order = json.load(handle).get("field_order", [])
		for _key, field in FLAGS:
			with self.subTest(field=field):
				self.assertIn(field, fields)
				self.assertEqual(fields[field]["fieldtype"], "Check")
				self.assertEqual(str(fields[field].get("default")), "1",
					"the other eleven checks ship on; this one should too")
				self.assertIn(field, order, "a field absent from field_order is "
					"in the table and not on the form")
				self.assertTrue(fields[field].get("description"),
					"%s has no description, so the form says only its label" % field)


class TestTheThresholdsThatRealDataForced(TestTheMirrorIsCheckedOut):
	def test_a_long_day_needs_more_than_one_row(self):
		"""Otherwise every task whose own day runs past the site standard flags:
		337 rows on kaitet.local, none of them a contradiction."""
		self.assertRegex(self.text, r"day_rows\.get\(dk2\)\)\s*<\s*2")

	def test_a_long_day_is_judged_per_date(self):
		"""Two ordinary full days are not one sixteen-hour day."""
		at = self.text.index("for dk2 in day_h:")
		window = self.text[at:at + 1600]
		self.assertIn("STANDARD_DAY", window)
		self.assertIn("getdate(dk_day).weekday()", window)

	def test_a_whole_day_is_never_a_short_day(self):
		"""Somebody doing 150% of target across a full day is productive."""
		self.assertRegex(self.text, r"hd_time_share\s*<\s*0\.95")

	def test_the_short_day_check_needs_a_target_to_compare_against(self):
		self.assertRegex(self.text, r"hd_tgt\s*>\s*0")

	def test_the_hourly_check_knows_the_spellings_in_use(self):
		"""The catalogue carries Hour and HR."""
		self.assertRegex(self.text, r'\("hour",\s*"hours",\s*"hr",\s*"hrs"\)')

	def test_an_absent_hour_reads_as_a_full_day_everywhere(self):
		"""Zero is the unset state -- frappe makes a Float column NOT NULL
		DEFAULT 0 -- so every reader has to convert it, or a real day counts as
		no labour."""
		self.assertRegex(self.text, r"flt\(r\.hours\)\s*if\s*frappe\.utils\.flt\(r\.hours\)\s*>\s*0\s*else\s*hd_std")


class TestTheDataTheChecksNeedIsActuallyFetched(TestTheMirrorIsCheckedOut):
	"""The unit and the daily target live on the plan, not the actuals. Without
	the joins these three checks would run and find nothing, silently."""

	def test_base_rows_carries_the_hours(self):
		self.assertIn("we.hours hours", self.text)

	def test_base_rows_reaches_the_plan_for_the_unit_and_target(self):
		self.assertIn("p3.uom plan_uom", self.text)
		self.assertIn("p3.daily_target dtarget", self.text)
		self.assertRegex(self.text, r"LEFT JOIN `tabWork Management Planner` p3")


class TestTheOldFlagAlreadyCoveredOneOfThese(unittest.TestCase):
	"""`left_but_earning` already flags work recorded after somebody was released
	from an assignment, so releasing a worker did not need a twelfth check --
	only the warning at entry, which the audit then shows as a pattern."""

	def setUp(self):
		if not os.path.isdir(MIRROR):
			self.skipTest("mirror not present")

	def test_earning_after_release_is_already_a_check(self):
		self.assertIn('"key": "left_but_earning"', payment_source())

	def test_and_the_entry_screen_warns_at_the_time(self):
		with open(os.path.join(MIRROR, "wm_actuals.py")) as handle:
			text = handle.read()
		self.assertIn("released_warning", text)


if __name__ == "__main__":
	unittest.main()
