"""One pay week's total onto Employee.custom_basic_pay, and the rest day it pays.

A colleague owns the Salary Structure whose Basic component fetches
`custom_basic_pay`, so this feature writes that field and stops. What it writes
is the confirmed, unpaid, payroll-counted actuals the payment run would send for
the week -- the SAME figure, through the same helper, because a payroll feed that
summed its own would hand payroll a number the payment screen disagrees with --
plus the weekly off-day bonus where it was earned.

The bonus is the part with a rule worth writing down:

  * The rest day is each WORKER'S OWN. Employees sit on different weekly offs
    (with Sundays, with Thursdays, with Fridays), so there is no company-wide off
    day and Sunday must not be hardcoded. It comes from the Holiday List assigned
    to them.
  * **`Holiday.weekly_off` separates the two features.** Ticked is a rest day and
    is what this bonus pays for. Unticked is a PUBLIC HOLIDAY, which is a working
    day here -- missing it forfeits the bonus, attending it earns doubled actuals
    (Phase 5b) and keeps the streak. Reading one as the other pays a bonus on
    every public holiday in the calendar, or double on every rest day.
  * A worker with no off-day data at all gets Sunday ASSUMED and flagged. A bonus
    paid on a guessed rest day is a bonus nobody can check.

Measured on kentrout.local before this was written, with a synthetic list holding
one of each kind of Holiday row: a worker present on all six working days
(2026-09-02, a public holiday, among them) took the 387 bonus; a worker who
missed only that holiday was refused with "no attendance on 2026-09-02 (missed
holiday: 2026-09-02)".

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_the_weekly_payroll_feed -v
"""

import json
import os
import re
import unittest

from work_management import pay_week

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAYROLL = os.path.join(APP, "api", "payroll.py")
PAYMENT = os.path.join(APP, "api", "payment.py")
SCREEN = os.path.join(APP, "public", "js", "work-payment.js")
MARKUP = os.path.join(APP, "www", "work-payment.html")
SETTINGS = os.path.join(APP, "work_management", "doctype",
	"work_management_settings", "work_management_settings.json")
INSTALL = os.path.join(APP, "install.py")

ACTION = "feed_week_to_payroll"
FIELD = "custom_basic_pay"


def read(path):
	with open(path) as handle:
		return handle.read()


def feed_block():
	"""The whole feature: the read half, the write half, and the two actions.

	It was one action's body until the panel's 417 forced it apart -- a loader
	that called the write action could not be fixed while the two were the same
	code. These tests are about what the feature does, not about where the lines
	sit, so the block is stitched back together here rather than each assertion
	being taught which half to look in.
	"""
	src = read(PAYROLL)
	helpers = src[src.index("def feed_preview("):src.index("@frappe.whitelist()")]
	actions = src[src.index('elif action == "preview":'):
		src.index('\n    else:\n        out["error"] = "unknown action')]
	return helpers + "\n" + actions


def feed_code():
	"""The same block with its comments stripped.

	Half of what this feature is, is written in those comments -- including the
	sentence explaining why `update_modified=False` is the WRONG tool here. A test
	asserting that string is absent has to read the code, or the explanation of
	the mistake reads as the mistake.
	"""
	return "\n".join(line.split("#")[0] for line in feed_block().splitlines())


def settings_fields():
	return {f["fieldname"]: f for f in json.load(open(SETTINGS))["fields"]}


# ---------------------------------------------------------------- the pay week


class TestThePayWeekIsThePaymentRunsPayWeek(unittest.TestCase):
	"""A feed that grouped days into different weeks from the payment run would
	pay a worker for a week the payment never covered, and the two figures would
	never reconcile. The arithmetic is one module now and both sides ask it."""

	def setUp(self):
		self.week = pay_week.shape("Sunday", "Saturday", None)

	def test_the_shipped_shape_is_sunday_to_saturday(self):
		self.assertEqual(self.week["days"], 7)
		self.assertEqual(self.week["start_wd"], pay_week.WEEKDAYS.index("Sunday"))

	def test_an_unset_setting_falls_back_rather_than_raising(self):
		"""The Select ships with a blank first option, and an unconfigured site
		must get the default shape, not an exception on the payment screen."""
		self.assertEqual(pay_week.shape("", "", ""), self.week)
		self.assertEqual(pay_week.shape(None, None, None), self.week)

	def test_pay_day_defaults_to_the_closing_day(self):
		self.assertEqual(self.week["pay_wd"], self.week["end_wd"])

	def test_every_day_of_a_week_resolves_to_the_same_week(self):
		spans = {pay_week.week_of(d, self.week)
			for d in ("2026-08-30", "2026-09-01", "2026-09-05")}
		self.assertEqual(len(spans), 1)
		self.assertEqual(spans.pop(), (pay_week.as_date("2026-08-30"),
			pay_week.as_date("2026-09-05")))

	def test_the_next_day_is_the_next_week(self):
		self.assertEqual(pay_week.week_of("2026-09-06", self.week)[0],
			pay_week.as_date("2026-09-06"))

	def test_a_short_week_leaves_days_belonging_to_no_week(self):
		"""Monday to Friday: Saturday and Sunday belong to no pay week at all.
		api/payment.py reports those as `outside_any_week` rather than dropping
		them, and week_of() returning None is what lets it."""
		short = pay_week.shape("Monday", "Friday", "Friday")
		self.assertEqual(short["days"], 5)
		self.assertIsNone(pay_week.week_of("2026-09-12", short))   # a Saturday
		self.assertIsNone(pay_week.week_of("2026-09-13", short))   # a Sunday
		self.assertIsNotNone(pay_week.week_of("2026-09-11", short))

	def test_a_week_that_wraps_the_weekend_is_still_measured_forward(self):
		"""Saturday to Wednesday is five days, not minus three."""
		wrap = pay_week.shape("Saturday", "Wednesday", None)
		self.assertEqual(wrap["days"], 5)
		self.assertEqual(pay_week.week_of("2026-09-06", wrap),
			(pay_week.as_date("2026-09-05"), pay_week.as_date("2026-09-09")))

	def test_the_week_in_progress_is_not_complete(self):
		self.assertFalse(pay_week.is_complete("2026-09-12", "2026-09-09"))
		self.assertTrue(pay_week.is_complete("2026-09-05", "2026-09-09"))

	def test_a_site_may_send_the_week_in_progress_anyway(self):
		self.assertTrue(pay_week.is_complete("2026-09-12", "2026-09-09", True))

	def test_the_last_complete_week_is_never_the_one_being_worked(self):
		"""The default the feed offers. Feeding the open week writes a figure
		that is still growing, and payroll reads whichever value it catches."""
		found = pay_week.last_complete_week("2026-09-09", self.week)
		self.assertEqual(found, (pay_week.as_date("2026-08-30"),
			pay_week.as_date("2026-09-05")))

	def test_it_walks_back_a_day_at_a_time_on_a_short_week(self):
		"""Stepping back seven days would land on a gap day, which belongs to no
		week, and the answer would be None on a week that certainly closed."""
		short = pay_week.shape("Monday", "Friday", "Friday")
		self.assertEqual(pay_week.last_complete_week("2026-09-13", short),
			(pay_week.as_date("2026-09-07"), pay_week.as_date("2026-09-11")))

	def test_the_pay_date_is_the_first_pay_day_on_or_after_the_close(self):
		self.assertEqual(pay_week.pay_date("2026-09-05", self.week),
			pay_week.as_date("2026-09-05"))
		monday = pay_week.shape("Sunday", "Saturday", "Monday")
		self.assertEqual(pay_week.pay_date("2026-09-05", monday),
			pay_week.as_date("2026-09-07"))

	def test_days_in_a_week_are_every_date_inclusive(self):
		self.assertEqual(len(pay_week.days_in("2026-08-30", "2026-09-05")), 7)

	def test_payment_and_the_feed_derive_the_week_the_same_way(self):
		"""api/payment.py still has its copy inline. If it stops agreeing with
		this module, two features disagree about which days a week holds."""
		src = read(PAYMENT)
		self.assertIn('((wk_end_idx - wk_start_wd) % 7) + 1', src,
			"payment.py's week length no longer matches pay_week.shape()")
		self.assertIn("(wdd.weekday() - wk_start_wd) % 7", src,
			"payment.py's week boundary no longer matches pay_week.week_of()")


# --------------------------------------------------------------- what it sums


class TestItSumsWhatThePaymentRunWouldSend(unittest.TestCase):
	def setUp(self):
		self.payment = read(PAYMENT)

	def test_the_aggregate_is_exposed_rather_than_re_implemented(self):
		self.assertIn("def weekly_earnings(", self.payment)
		imports = "\n".join(l for l in read(PAYROLL).splitlines()[:30])
		self.assertIn("weekly_earnings", imports)
		self.assertIn("from work_management.api.payment import", imports)

	def test_the_feed_calls_it(self):
		self.assertIn("weekly_earnings(", feed_block())
		self.assertIn("for earned in weekly_earnings(", feed_block())

	def test_the_eligibility_conditions_are_the_payment_runs_own(self):
		"""Copied verbatim, not reworded. Each of the five excludes money that is
		already spoken for."""
		for cond in ("ac.workflow_state='CONFIRMED'", "IFNULL(we.paid,0)=0",
				"IFNULL(we.count_in_payroll,0)=1", "we.amount>0",
				"IFNULL(we.payment_ref,'')=''"):
			with self.subTest(cond=cond):
				self.assertIn(cond, self.payment)

	def test_the_payment_ref_condition_is_in_the_shared_constant(self):
		"""Without it a second pass re-claims rows that already sit on a payment,
		silently orphaning the first document."""
		at = self.payment.index("EARNINGS_CONDITIONS = ")
		self.assertIn("IFNULL(we.payment_ref,'')=''",
			self.payment[at:at + 400])

	def test_only_task_workers_are_summed(self):
		"""Salaried staff are paid through payroll; their recorded work must
		never turn into a payment here, or into a basic pay figure."""
		at = self.payment.index("def weekly_earnings(")
		self.assertIn("task_worker_sql(", self.payment[at:at + 900])

	def test_the_task_worker_filter_is_shared_not_copied_again(self):
		self.assertIn("def task_worker_sql(", self.payment)
		self.assertIn('TW_ONLY = task_worker_sql("we")', self.payment)

	def test_it_groups_per_worker_and_not_per_job(self):
		"""A payroll feed writes one figure per person."""
		at = self.payment.index("def weekly_earnings(")
		block = self.payment[at:at + 2000]
		self.assertIn("GROUP BY we.employee", block)
		self.assertIn("SUM(we.amount)", block)
		self.assertIn("COUNT(DISTINCT we.work_date)", block)


# ------------------------------------------------------------- the off day


class TestWhoseOffDayItIs(unittest.TestCase):
	def setUp(self):
		self.src = read(PAYROLL)

	def test_sunday_is_not_hardcoded_as_the_rule(self):
		"""It is the FALLBACK for a worker with no data, and nothing else."""
		self.assertIn("def holiday_list_for(", self.src)
		self.assertIn("Employee", self.src)

	def test_the_worker_s_own_list_is_asked_for(self):
		at = self.src.index("def holiday_list_for(")
		block = self.src[at:self.src.index("def off_days_in(")]
		self.assertIn('frappe.db.get_value("Employee", employee, "holiday_list")', block)

	def test_hrms_date_effective_assignment_is_preferred(self):
		"""On Altura upande_ta's Bulk Week Off assigns lists through hrms, so
		Employee.holiday_list is whatever was assigned LAST rather than what
		applied in the week being paid."""
		at = self.src.index("def holiday_list_for(")
		block = self.src[at:self.src.index("def off_days_in(")]
		self.assertIn("get_assigned_holiday_list", block)
		self.assertLess(block.index("get_assigned_holiday_list"),
			block.index('get_value("Employee"'),
			"the Employee field must be the fallback, not the first answer")

	def test_hrms_being_absent_is_not_a_failure(self):
		"""Every other site has no assignment machinery, and a payroll preview
		must not die on an ImportError."""
		at = self.src.index("def holiday_list_for(")
		block = self.src[at:self.src.index("def off_days_in(")]
		self.assertIn("except Exception:", block)

	def test_weekly_off_is_what_splits_a_rest_day_from_a_public_holiday(self):
		at = self.src.index("def off_days_in(")
		block = self.src[at:self.src.index("@frappe.whitelist()")]
		self.assertIn("weekly_off", block)
		self.assertIn('out["weekly_off" if frappe.utils.cint(row.wo) else "public"]', block)

	def test_the_two_kinds_are_kept_apart_in_the_answer(self):
		at = self.src.index("def off_days_in(")
		block = self.src[at:self.src.index("@frappe.whitelist()")]
		self.assertIn('"weekly_off": []', block)
		self.assertIn('"public": []', block)


class TestWhatEarnsTheBonus(unittest.TestCase):
	def setUp(self):
		self.block = feed_block()

	def test_the_working_days_are_everything_that_is_not_the_rest_day(self):
		self.assertIn("working = [d for d in days if d not in rest]", self.block)

	def test_a_public_holiday_is_a_working_day(self):
		"""It is NOT subtracted with the rest day. A casual who misses a public
		holiday forfeits; one who attends earns doubled actuals and keeps the
		streak. Subtracting it here would pay the bonus to somebody who was
		absent on it."""
		at = self.block.index("working = [d for d in days if d not in rest]")
		self.assertNotIn('off["public"]', self.block[at - 300:at + 120])

	def test_missing_any_working_day_forfeits(self):
		self.assertIn("elif absent:", self.block)

	def test_a_missed_holiday_is_named_as_such(self):
		""""missed holiday" is the reason HR asked to see, because a worker who
		thought a holiday was a day off will come and ask."""
		self.assertIn("missed holiday", self.block)

	def test_the_forfeit_names_the_days(self):
		self.assertIn('", ".join(absent[:4])', self.block)

	def test_half_a_day_is_not_a_full_day(self):
		"""PRESENT_STATUSES deliberately excludes Half Day: a full rest day for a
		full week, and half a day is a case for a human."""
		self.assertNotIn("Half Day", read(PAYROLL).split("PRESENT_STATUSES = ")[1][:120])

	def test_the_bonus_is_off_unless_the_site_says_otherwise(self):
		fields = settings_fields()
		self.assertIn("pay_weekly_off_on_full_attendance", fields)
		self.assertEqual(fields["pay_weekly_off_on_full_attendance"]["fieldtype"], "Check")
		self.assertEqual(str(fields["pay_weekly_off_on_full_attendance"].get("default")), "0")

	def test_the_amount_is_configurable_and_defaults_to_the_daily_wage(self):
		fields = settings_fields()
		self.assertIn("weekly_off_bonus_amount", fields)
		self.assertEqual(fields["weekly_off_bonus_amount"]["fieldtype"], "Currency")
		self.assertEqual(str(fields["weekly_off_bonus_amount"].get("default")), "387")

	def test_both_are_on_the_form(self):
		order = json.load(open(SETTINGS))["field_order"]
		for name in ("sb_offday_bonus", "pay_weekly_off_on_full_attendance",
				"weekly_off_bonus_amount"):
			with self.subTest(field=name):
				self.assertIn(name, order)

	def test_the_switch_being_off_is_a_stated_reason_not_a_silent_zero(self):
		self.assertIn("off-day bonus is switched off in Settings", self.block)

	def test_no_off_day_data_is_flagged_rather_than_assumed_quietly(self):
		self.assertIn("assumed = 1", self.block)
		self.assertIn('out["assumed_off_day"]', self.block)

	def test_the_assumption_is_sunday(self):
		at = self.block.index("assumed = 1")
		self.assertIn("weekday() == 6", self.block[at:at + 300])


# ------------------------------------------------------------- the write path


class TestNothingIsWrittenUntilSomebodyHasSeenIt(unittest.TestCase):
	def setUp(self):
		self.block = feed_block()
		self.js = read(SCREEN)

	def test_preview_is_the_default_and_writing_is_opt_in(self):
		self.assertIn('elif action == "preview":', self.block)
		self.assertIn('out["preview"] = 1', self.block)
		self.assertIn('out["preview"] = 0', self.block)

	def test_the_preview_carries_every_column_the_table_needs(self):
		"""worker, actuals total, off day, bonus yes/no + reason, weekly total."""
		for key in ('"employee_name"', '"actuals"', '"off_day"', '"bonus"',
				'"bonus_reason"', '"total"'):
			with self.subTest(key=key):
				self.assertIn(key, self.block)

	def test_the_screen_renders_that_table_before_offering_the_button(self):
		at = self.js.index("function renderFeed(")
		block = self.js[at:at + 4000]
		for header in ("Worker", "Actuals", "Off day", "Bonus", "Weekly total"):
			with self.subTest(header=header):
				self.assertIn(header, block)

	def test_the_write_button_asks_first(self):
		self.assertIn("confirm(", self.js[self.js.index("function wireFeed("):])

	def test_the_control_is_disabled_with_its_reason_in_the_tooltip(self):
		"""A greyed button with no explanation is the thing that costs an
		afternoon -- kaitet-group lost one to exactly that."""
		at = self.js.index("function renderFeed(")
		block = self.js[at:at + 4000]
		self.assertIn("disabled title=", block)
		# the reason comes from the server as a sentence now, rather than the
		# screen assembling one out of config_missing
		self.assertIn("d.cannot_feed", block)

	def test_the_server_refuses_too_rather_than_trusting_the_button(self):
		self.assertIn('elif not out.get("can_feed"):', self.block)

	def test_a_missing_field_is_named_before_anything_is_attempted(self):
		self.assertIn('get_field("custom_basic_pay")', self.block)


class TestTheWriteItself(unittest.TestCase):
	def setUp(self):
		self.block = feed_block()

	def test_it_writes_exactly_the_fieldname_payroll_fetches(self):
		"""A colleague owns the Salary Structure whose Basic component fetches
		this. A near-miss fieldname writes to nothing."""
		self.assertIn("doc.custom_basic_pay = ", self.block)
		self.assertIn('out["field"] = "custom_basic_pay"', self.block)

	def test_it_is_a_versioned_doc_update(self):
		"""This is somebody's pay. frappe.db.set_value(..., update_modified=False)
		is the wrong tool: the change belongs in the Employee's history with who
		made it and when, which a raw column write throws away."""
		self.assertIn('frappe.get_doc("Employee", row["employee"])', self.block)
		self.assertIn("doc.save(ignore_permissions=True)", self.block)
		self.assertNotIn("update_modified=False", feed_code())

	def test_it_leaves_the_arithmetic_on_the_record(self):
		self.assertIn("add_comment", self.block)
		self.assertIn("off-day bonus", self.block)

	def test_the_week_is_stamped(self):
		self.assertIn('doc.custom_basic_pay_week = plan["week_stamp"]', self.block)

	def test_re_feeding_the_same_week_is_a_no_op_that_says_so(self):
		self.assertIn('str(emp.get("custom_basic_pay_week") or "") == stamp', self.block)
		self.assertIn("already fed for ", self.block)

	def test_both_fields_are_shipped_as_custom_field_fixtures(self):
		src = read(INSTALL)
		self.assertIn('("Employee", "custom_basic_pay", "Basic Pay", "Currency"', src)
		self.assertIn('"custom_basic_pay_week"', src)

	def test_a_site_already_installed_gets_them_too(self):
		"""create_core_custom_fields() runs in after_install and nowhere else, so
		a field added to the list later never reaches a live site."""
		patches = read(os.path.join(APP, "patches.txt"))
		self.assertIn("work_management.patches.v1_0.add_the_basic_pay_field", patches)
		self.assertTrue(os.path.exists(os.path.join(APP, "patches", "v1_0",
			"add_the_basic_pay_field.py")))


class TestWhoIsSkippedAndWhy(unittest.TestCase):
	def setUp(self):
		self.block = feed_block()

	def test_the_payment_runs_own_preconditions_are_applied(self):
		"""A worker payroll cannot pay is a worker this must not quietly hand a
		figure to. Same four gates as pay_worker_submit.

		They live in payroll_preconditions() in api/payment.py now, shared with
		the worker review sheet so the two screens give one answer rather than
		two wordings for one condition. The property being held down is that the
		feed applies them -- not where the strings sit."""
		self.assertIn("payroll_preconditions(", self.block)
		gate = read(PAYMENT)
		at = gate.index("def payroll_preconditions(")
		gate = gate[at:gate.index("def payment_mode():")]
		for reason in ("employee is Inactive", "is after the relieving date",
				"is before the joining date", "no submitted Salary Structure Assignment"):
			with self.subTest(reason=reason):
				self.assertIn(reason, gate)

	def test_every_skip_carries_its_reason(self):
		self.assertIn('row["skipped"] = block', self.block)
		self.assertIn('out["skipped"] = skipped', self.block)

	def test_a_zero_work_worker_is_skipped_and_not_written_as_zero(self):
		"""Writing 0 says "this person earned nothing", which is a claim.
		Not writing says "this feed has nothing to say about them"."""
		self.assertIn("no confirmed unpaid work in this week", self.block)
		self.assertIn('row["hr_question"] = 1', self.block)

	def test_that_is_raised_as_a_question_for_hr(self):
		self.assertIn('out["hr_questions"]', self.block)

	def test_the_screen_surfaces_both_flags(self):
		js = read(SCREEN)
		self.assertIn("hr_questions", js)
		self.assertIn("assumed_off_day", js)


class TestTheWeekAskedForIsTheWeekFed(unittest.TestCase):
	def setUp(self):
		self.block = feed_block()

	def test_a_date_in_the_middle_snaps_to_the_whole_week(self):
		self.assertIn("pay_week.week_of(week_from, shape)", self.block)

	def test_no_week_asked_for_means_the_last_one_that_closed(self):
		self.assertIn("pay_week.last_complete_week(today, shape)", self.block)

	def test_a_range_that_is_not_one_pay_week_is_refused(self):
		"""Quietly paying the week the start date lands in would pay days the
		caller never asked about."""
		self.assertIn("is not one pay week", self.block)

	def test_a_day_belonging_to_no_week_is_refused_by_name(self):
		self.assertIn("belongs to no pay", self.block)
		self.assertIn("this project's week runs", self.block)


class TestTheControlIsReachable(unittest.TestCase):
	"""api/payment.py answering an action no screen asks for is the drift
	test_no_capability_is_stranded.py exists for. This one lives in wm_payroll,
	which that test does not cover, so it is covered here."""

	def test_the_screen_calls_the_action(self):
		js = read(SCREEN)
		self.assertIn('"feed_week_to_payroll" : "preview"', js)
		self.assertIn('"wm_payroll"', js)

	def test_the_markup_has_the_panel_the_screen_writes_into(self):
		self.assertIn('id="feed-week"', read(MARKUP))

	def test_the_tab_loads_it(self):
		js = read(SCREEN)
		self.assertIn("feedWeek(false)", js[js.index("function showTab("):][:1400])

	def test_the_action_is_served(self):
		self.assertIn('elif action == "%s":' % ACTION, read(PAYROLL))

	def test_the_warning_banner_it_uses_has_a_style(self):
		"""banner.warn had no rule of its own and rendered as an unstyled row,
		which reads as a layout bug rather than a refusal."""
		self.assertIn("#wpay .banner.warn{", read(MARKUP))


if __name__ == "__main__":
	unittest.main()
