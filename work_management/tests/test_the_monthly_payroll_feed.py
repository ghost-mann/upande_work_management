"""Paying by the month, from the 21st to the 20th -- and weekly exactly as before.

Altura moved casual payroll from weekly to monthly. A pay month runs from a
configured start day to the day before it in the next month, and is named for
the month it ends in ("October 2026: 21 Sep -> 20 Oct"). The start day is a
setting, not a constant, because the client has not fully confirmed which way
the cut-off falls: 20 instead of 21 must need no code change.

What has to hold, and is tested here:

- the resolver draws the right periods, across month ends and the year end;
- a completed month feeds its total; an open month can be previewed, never fed;
- THE TRANSITION MONTH: days a weekly feed already paid are excluded from the
  first monthly feed, and reported, and nothing is paid twice;
- the off-day bonus stays weekly inside a month, skips weeks already fed, and
  is recorded on the run per week (a pay rule: confirm with the client);
- Weekly restores today's behaviour;
- the Altura seed fills only what is missing.

    bench --site kentrout.local run-tests --app work_management \\
        --module work_management.tests.test_the_monthly_payroll_feed
"""

import datetime
import unittest
from unittest import mock

import frappe

from work_management import pay_period, pay_week
from work_management.tests import pipeline
from work_management.tests.pipeline import call

MONTHLY_21 = pay_period.shape("Monthly", 21, "Monday", "Sunday", "Monday")


def d(text):
	return datetime.date.fromisoformat(text)


class TestTheResolver(unittest.TestCase):
	"""Pure: no site needed."""

	def test_a_month_runs_from_the_21st_to_the_20th(self):
		for day in ("2026-09-21", "2026-10-01", "2026-10-20"):
			with self.subTest(day=day):
				self.assertEqual(pay_period.period_of(day, MONTHLY_21), (d("2026-09-21"), d("2026-10-20")))
		self.assertEqual(pay_period.period_of("2026-10-21", MONTHLY_21), (d("2026-10-21"), d("2026-11-20")))

	def test_the_year_end_period(self):
		for day in ("2026-12-21", "2026-12-31", "2027-01-01", "2027-01-20"):
			with self.subTest(day=day):
				self.assertEqual(pay_period.period_of(day, MONTHLY_21), (d("2026-12-21"), d("2027-01-20")))

	def test_february_and_a_leap_year(self):
		self.assertEqual(pay_period.period_of("2028-03-01", MONTHLY_21), (d("2028-02-21"), d("2028-03-20")))
		self.assertEqual(pay_period.period_of("2027-02-25", MONTHLY_21), (d("2027-02-21"), d("2027-03-20")))

	def test_it_is_named_for_the_month_it_ends_in_with_both_dates(self):
		self.assertEqual(pay_period.label(d("2026-09-21"), d("2026-10-20"), MONTHLY_21),
			"October 2026: 21 Sep → 20 Oct")
		self.assertEqual(pay_period.label(d("2026-12-21"), d("2027-01-20"), MONTHLY_21),
			"January 2027: 21 Dec → 20 Jan")

	def test_the_other_reading_is_a_setting(self):
		"""20 instead of 21: no code change, only the setting."""
		sh = pay_period.shape("Monthly", 20)
		self.assertEqual(pay_period.period_of("2026-10-15", sh), (d("2026-09-20"), d("2026-10-19")))

	def test_a_start_day_months_do_not_all_have_falls_back(self):
		self.assertEqual(pay_period.shape("Monthly", 31)["month_start_day"], 1)
		self.assertEqual(pay_period.shape("Monthly", 0)["month_start_day"], 1)

	def test_stepping_and_the_latest_closed_month(self):
		self.assertEqual(pay_period.previous_complete("2026-10-15", MONTHLY_21), (d("2026-08-21"), d("2026-09-20")))
		self.assertEqual(pay_period.shift("2026-10-15", 1, MONTHLY_21), (d("2026-10-21"), d("2026-11-20")))
		self.assertEqual(pay_period.shift("2026-12-25", 1, MONTHLY_21), (d("2027-01-21"), d("2027-02-20")))
		self.assertEqual(pay_period.shift("2027-01-05", -1, MONTHLY_21), (d("2026-11-21"), d("2026-12-20")))

	def test_a_month_is_paid_the_day_it_closes(self):
		self.assertEqual(pay_period.pay_date("2026-10-20", MONTHLY_21), d("2026-10-20"))

	def test_each_pay_week_belongs_to_the_month_it_closes_in(self):
		weeks = pay_period.weeks_closing_in("2026-09-21", "2026-10-20", MONTHLY_21)
		self.assertEqual(weeks[0], (d("2026-09-21"), d("2026-09-27")))
		self.assertEqual(weeks[-1], (d("2026-10-12"), d("2026-10-18")))
		# the week straddling the 20th/21st (19-25 Oct) closes in November's month
		nov = pay_period.weeks_closing_in("2026-10-21", "2026-11-20", MONTHLY_21)
		self.assertEqual(nov[0], (d("2026-10-19"), d("2026-10-25")))

	def test_weekly_is_pay_week_unchanged(self):
		for start, end in (("Sunday", "Saturday"), ("Monday", "Sunday"), ("Monday", "Friday")):
			sh = pay_period.shape("Weekly", 21, start, end, None)
			wk = pay_week.shape(start, end, None)
			day = d("2026-09-01")
			for _ in range(21):
				with self.subTest(shape=(start, end), day=day):
					self.assertEqual(pay_period.period_of(day, sh), pay_week.week_of(day, wk))
					found = pay_week.week_of(day, wk)
					if found:
						self.assertEqual(pay_period.pay_date(found[1], sh), pay_week.pay_date(found[1], wk))
				day += datetime.timedelta(days=1)
			self.assertEqual(pay_period.previous_complete("2026-10-15", sh),
				pay_week.last_complete_week("2026-10-15", wk))

	def test_an_unset_frequency_is_weekly(self):
		self.assertEqual(pay_period.shape(None, None)["frequency"], "Weekly")
		self.assertEqual(pay_period.shape("", 0)["frequency"], "Weekly")


class FeedCase(pipeline.SiteTestCase, unittest.TestCase):
	"""Two workers, confirmed actuals on six days, 3-8 Sep 2026: Thu 3 to Sun 6
	in the pay week 31 Aug - 6 Sep, Mon 7 and Tue 8 in the next. All of it in the
	pay month 21 Aug - 20 Sep, which has closed."""

	MONTH = ("2026-08-21", "2026-09-20")
	WEEK1 = ("2026-08-31", "2026-09-06")

	def setUp(self):
		super().setUp()
		self.settings(att_block_absent=0, att_block_leave=0, att_block_noscan_actuals=0,
			att_block_off=0, block_self_approval=0, payment_mode="Payroll feed",
			pay_week_starts_on="Monday", pay_week_ends_on="Sunday", pay_day="Monday",
			pay_frequency="Monthly", pay_month_start_day=21,
			pay_weekly_off_on_full_attendance=0, weekly_off_bonus_amount=400)
		# whether a worker has a Salary Structure Assignment is payroll's
		# precondition, tested in its own right; here it would only hide the sums
		gate = mock.patch("work_management.api.payroll.payroll_preconditions", return_value=None)
		gate.start()
		self.addCleanup(gate.stop)
		p = self.p = pipeline.Pipeline(from_date="2026-09-03", days=6)
		p.master_plan()
		p.plan(quantity=12)
		p.assignment()
		p.actuals(submit=True, qty=1)
		call(p.ep.act, action="act_approve", name=p.act, stage="actuals_farm_manager")
		out = call(p.ep.act, action="act_approve", name=p.act, stage="actuals_hr_head")
		self.assertEqual(out.get("workflow_state"), "CONFIRMED", out)
		self.amount = {w: frappe.db.sql("""SELECT COALESCE(SUM(amount),0) FROM `tabWork Actuals Employee`
			WHERE parent=%s AND employee=%s""", (p.act, w))[0][0] for w in p.workers}
		self.amount_week1 = {w: frappe.db.sql("""SELECT COALESCE(SUM(amount),0) FROM `tabWork Actuals Employee`
			WHERE parent=%s AND employee=%s AND work_date BETWEEN %s AND %s""",
			(p.act, w, self.WEEK1[0], self.WEEK1[1]))[0][0] for w in p.workers}

	def payroll(self, **params):
		from work_management.api.payroll import wm_payroll

		return call(wm_payroll, **params)

	def preview(self, date):
		return self.payroll(action="preview", period_from=date)

	def feed(self, date):
		return self.payroll(action="feed_week_to_payroll", period_from=date)

	def row(self, out, worker):
		return [r for r in out["rows"] if r["employee"] == worker][0]

	def basic_pay(self, worker):
		return frappe.db.get_value("Employee", worker, ["custom_basic_pay", "custom_basic_pay_week"])


class TestFeedingAMonth(FeedCase):
	def test_the_preview_names_the_month(self):
		out = self.preview("2026-09-05")
		self.assertEqual((out["period_from"], out["period_to"]), self.MONTH)
		self.assertEqual(out["period_label"], "September 2026: 21 Aug → 20 Sep")
		self.assertEqual(out["frequency"], "Monthly")
		self.assertEqual(out["complete"], 1)

	def test_a_completed_month_feeds_its_total(self):
		out = self.feed("2026-09-05")
		self.assertFalse(out.get("error"), out)
		self.assertEqual(out["written"], 2)
		for w in self.p.workers:
			with self.subTest(worker=w):
				pay, stamp = self.basic_pay(w)
				self.assertAlmostEqual(pay, self.amount[w], places=2)
				self.assertEqual(stamp, "2026-08-21 → 2026-09-20")
		run = frappe.get_all("Work Management Payment", filters={"employee": self.p.workers[0]},
			fields=["period_from", "period_to", "payroll_date", "workflow_state"])[0]
		self.assertEqual((str(run.period_from), str(run.period_to), str(run.payroll_date)),
			("2026-08-21", "2026-09-20", "2026-09-20"))
		self.assertEqual(run.workflow_state, "Paid")

	def test_feeding_it_again_does_nothing(self):
		self.feed("2026-09-05")
		out = self.feed("2026-09-05")
		# refused, as a weekly re-feed is: the days are stamped paid by the first
		self.assertIn("Cannot feed this month", out.get("error") or "")
		self.assertFalse(out.get("written"))
		self.assertEqual(frappe.db.count("Work Management Payment",
			{"employee": self.p.workers[0], "period_from": self.MONTH[0]}), 1)

	def test_an_open_month_previews_but_refuses_to_feed(self):
		today = frappe.utils.today()
		out = self.preview(today)
		self.assertEqual(out["complete"], 0)
		self.assertEqual(out["can_feed"], 0)
		self.assertIn("has not closed yet", out["cannot_feed"])
		self.assertIn("Cannot feed this month", self.feed(today).get("error") or "")

	def test_the_start_day_20_needs_no_code(self):
		self.settings(pay_month_start_day=20)
		out = self.preview("2026-09-05")
		self.assertEqual((out["period_from"], out["period_to"]), ("2026-08-20", "2026-09-19"))

	def test_switching_back_to_weekly_feeds_a_week(self):
		self.settings(pay_frequency="Weekly")
		out = self.preview("2026-09-05")
		self.assertEqual((out["week_from"], out["week_to"]), self.WEEK1)
		self.assertEqual(out["frequency"], "Weekly")
		self.assertNotIn("excluded_weekly_total", out)
		self.assertEqual(out["week_stamp"], "2026-08-31 → 2026-09-06")
		self.assertEqual(out["pay_date"], "2026-09-07")      # the Monday after
		fed = self.feed("2026-09-05")
		self.assertEqual(fed["written"], 2)
		self.assertAlmostEqual(self.basic_pay(self.p.workers[0])[0], self.amount_week1[self.p.workers[0]], places=2)


class TestTheTransitionMonth(FeedCase):
	"""Some weeks fed weekly, then the first monthly feed over the same days."""

	def setUp(self):
		super().setUp()
		self.settings(pay_frequency="Weekly")
		self.assertEqual(self.feed(self.WEEK1[0])["written"], 2)
		self.settings(pay_frequency="Monthly")

	def test_the_weekly_days_are_excluded_and_reported(self):
		out = self.preview("2026-09-05")
		for w in self.p.workers:
			with self.subTest(worker=w):
				r = self.row(out, w)
				self.assertAlmostEqual(r["actuals"], self.amount[w] - self.amount_week1[w], places=2)
				self.assertAlmostEqual(r["excluded_weekly"], self.amount_week1[w], places=2)
				self.assertTrue(r["excluded_runs"])
		self.assertAlmostEqual(out["excluded_weekly_total"], sum(self.amount_week1.values()), places=2)

	def test_nothing_is_paid_twice(self):
		self.assertFalse(self.feed("2026-09-05").get("error"))
		for w in self.p.workers:
			with self.subTest(worker=w):
				paid = frappe.db.sql("""SELECT COALESCE(SUM(amount),0) FROM `tabWork Management Payment`
					WHERE employee=%s AND workflow_state='Paid'""", (w,))[0][0]
				self.assertAlmostEqual(paid, self.amount[w], places=2)
				# every day row is on exactly one run
				self.assertEqual(frappe.db.count("Work Actuals Employee",
					{"parent": self.p.act, "employee": w, "payment_ref": ["is", "not set"]}), 0)

	def test_basic_pay_is_overwritten_with_the_month_s_leftover(self):
		self.feed("2026-09-05")
		w = self.p.workers[0]
		self.assertAlmostEqual(self.basic_pay(w)[0], self.amount[w] - self.amount_week1[w], places=2)
		run = frappe.get_all("Work Management Payment",
			filters={"employee": w, "period_from": self.MONTH[0]}, fields=["excluded_weekly_amount"])[0]
		self.assertAlmostEqual(run.excluded_weekly_amount, self.amount_week1[w], places=2)


class TestTheBonusStaysWeekly(FeedCase):
	"""One bonus per pay week closing in the month; weeks already fed skipped;
	every week's verdict recorded on the run. A PAY RULE: confirm with the client."""

	def setUp(self):
		super().setUp()
		self.settings(pay_weekly_off_on_full_attendance=1)
		self.worker = self.p.workers[0]
		# full attendance in the week 7-13 Sep, nothing anywhere else
		for day in ("2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11", "2026-09-12"):
			frappe.get_doc({"doctype": "Attendance", "employee": self.worker, "attendance_date": day,
				"status": "Present", "company": frappe.db.get_value("Employee", self.worker, "company"),
				"docstatus": 1}).db_insert()

	def test_one_bonus_per_week_that_earned_it(self):
		r = self.row(self.preview("2026-09-05"), self.worker)
		weeks = {w["week_from"]: w for w in r["bonus_weeks"]}
		self.assertEqual(sorted(weeks), ["2026-08-17", "2026-08-24", "2026-08-31", "2026-09-07", "2026-09-14"])
		self.assertEqual(weeks["2026-09-07"]["amount"], 400)
		self.assertEqual(r["bonus"], 400)
		self.assertIn("no attendance", weeks["2026-08-31"]["note"])

	def test_a_week_already_fed_weekly_is_skipped(self):
		self.settings(pay_frequency="Weekly")
		self.feed("2026-09-08")        # the week 7-13 Sep, with its bonus
		self.settings(pay_frequency="Monthly")
		r = self.row(self.preview("2026-09-05"), self.worker)
		week = [w for w in r["bonus_weeks"] if w["week_from"] == "2026-09-07"][0]
		self.assertEqual(week["amount"], 0)
		self.assertIn("paid with weekly feed", week["note"])
		self.assertEqual(r["bonus"], 0)

	def test_the_verdicts_are_recorded_on_the_run(self):
		self.assertFalse(self.feed("2026-09-05").get("error"))
		run = frappe.get_all("Work Management Payment",
			filters={"employee": self.worker, "period_from": self.MONTH[0]}, pluck="name")[0]
		rows = frappe.get_all("Work Payment Bonus Week", filters={"parent": run},
			fields=["week_from", "amount", "note"], order_by="week_from")
		self.assertEqual(len(rows), 5)
		self.assertEqual(sum(r.amount for r in rows), 400)
		pay = self.basic_pay(self.worker)[0]
		self.assertAlmostEqual(pay, self.amount[self.worker] + 400, places=2)


class TestTheScreenAsksTheServer(pipeline.SiteTestCase, unittest.TestCase):
	def setUp(self):
		super().setUp()
		self.settings(pay_frequency="Monthly", pay_month_start_day=21)

	def pay(self, **params):
		from work_management.api.payment import wm_payment

		return call(wm_payment, **params)

	def test_the_navigator_steps_by_month(self):
		p = self.pay(action="pay_period", date="2026-10-05", step=1)["period"]
		self.assertEqual((p["from"], p["to"], p["label"]), ("2026-10-21", "2026-11-20", "November 2026: 21 Oct → 20 Nov"))
		p = self.pay(action="pay_period", date="2026-10-05", step=-1)["period"]
		self.assertEqual((p["from"], p["to"]), ("2026-08-21", "2026-09-20"))

	def test_pay_roles_hands_over_the_first_period_and_the_word(self):
		out = self.pay(action="pay_roles")
		self.assertEqual(out["period_word"], "month")
		self.assertEqual(out["period_latest"]["is_complete"], 1)

	def test_weekly_steps_by_week(self):
		self.settings(pay_frequency="Weekly", pay_week_starts_on="Monday", pay_week_ends_on="Sunday")
		p = self.pay(action="pay_period", date="2026-10-15", step=-1)["period"]
		self.assertEqual((p["from"], p["to"], p["label"]), ("2026-10-05", "2026-10-11", "5 Oct → 11 Oct 2026"))


class TestTheSeed(pipeline.SiteTestCase, unittest.TestCase):
	"""Insert if missing; never overwrite."""

	def run_seed(self):
		from work_management.patches.v1_0 import seed_monthly_pay_period

		seed_monthly_pay_period.execute()
		frappe.clear_cache(doctype="Work Management Settings")

	def clear(self, field):
		frappe.db.sql("DELETE FROM `tabSingles` WHERE doctype='Work Management Settings' AND field=%s", (field,))

	def test_a_site_that_never_chose_gets_monthly_from_the_21st(self):
		self.clear("pay_frequency")
		self.clear("pay_month_start_day")
		self.run_seed()
		self.assertEqual(frappe.db.get_single_value("Work Management Settings", "pay_frequency"), "Monthly")
		self.assertEqual(frappe.db.get_single_value("Work Management Settings", "pay_month_start_day"), 21)

	def test_a_value_the_site_holds_is_kept(self):
		self.settings(pay_frequency="Weekly", pay_month_start_day=20)
		self.run_seed()
		self.assertEqual(frappe.db.get_single_value("Work Management Settings", "pay_frequency"), "Weekly")
		self.assertEqual(frappe.db.get_single_value("Work Management Settings", "pay_month_start_day"), 20)

	def test_each_field_is_decided_on_its_own(self):
		self.settings(pay_frequency="Monthly")
		self.clear("pay_month_start_day")
		self.run_seed()
		self.assertEqual(frappe.db.get_single_value("Work Management Settings", "pay_month_start_day"), 21)

	def test_a_start_day_out_of_range_is_refused_on_save(self):
		doc = frappe.get_single("Work Management Settings")
		doc.pay_frequency = "Monthly"
		doc.pay_month_start_day = 30
		self.assertRaises(frappe.ValidationError, doc.validate_pay_month)
