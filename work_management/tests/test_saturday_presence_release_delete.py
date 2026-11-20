"""The 2026-11-19 batch agreed with the farms.

- An hourly task's Saturday (a 6-hour day) pays the full daily wage: hours worked
  are scaled to the weekday's 8, capped there, so a clerk who still types 8 pays
  the same wage and not more.
- A worker with no scan yet is paid only when the person entering ticks them as
  present; the tick is kept on the row, HR acknowledges it in the payroll check,
  and the Absent-pay rule leaves it for HR rather than zeroing it.
- Releasing frees a worker from the day after their last recorded work, not
  from tomorrow; everyone working on the farm's plans may release, at any live stage.
- Duplicate assignments and unconfirmed actuals can be deleted, with a reason.
- An early close carries a rating, from the requester and from the GM.
- The payroll check opens to everyone on the farm for viewing and fixing;
  approving stays with the farm manager, HR and the GM.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "api"
JS = ROOT / "public" / "js"


def src(name):
	return (API / name).read_text()


def block(name, action):
	s = src(name)
	i = s.index('elif action == "%s":' % action)
	return s[i:s.index("elif action ==", i + 10)]


class TestSaturdayHourly(unittest.TestCase):
	def scale(self, qty, std_h, wk=8.0, hourly=1):
		# the arithmetic from act_submit, kept in step with it below
		hrs = 0
		if hourly and std_h > 0 and std_h < wk:
			hrs = qty
			qty = min(round(qty * wk / std_h, 2), wk)
		return qty, hrs

	def test_a_full_saturday_pays_a_full_day(self):
		self.assertEqual(self.scale(6, 6), (8.0, 6))

	def test_a_part_saturday_is_proportional(self):
		self.assertEqual(self.scale(3, 6), (4.0, 3))

	def test_typing_eight_as_before_does_not_overpay(self):
		self.assertEqual(self.scale(8, 6), (8.0, 8))

	def test_weekdays_and_other_units_untouched(self):
		self.assertEqual(self.scale(6, 8)[0], 6)
		self.assertEqual(self.scale(6, 6, hourly=0)[0], 6)

	def test_the_code_does_this(self):
		s = src("actuals.py")
		self.assertIn("if wmg_hourly and std_h > 0 and std_h < wmg_wk_h:", s)
		self.assertIn("qty = min(round(qty * wmg_wk_h / std_h, 2), wmg_wk_h)", s)
		# an edit shows the hours worked, so saving again does not scale twice
		self.assertIn('frappe.utils.getdate(r.work_date).weekday() == 5:', s)


class TestConfirmedPresent(unittest.TestCase):
	def test_unticked_no_scan_days_are_sent_back_to_the_screen(self):
		s = src("actuals.py")
		self.assertIn('out["needs_presence"] = 1', s)
		self.assertIn("row.presence_confirmed_by = pres_used[(emp, str(wdate))]", s)

	def test_the_screen_asks_per_person(self):
		js = (JS / "work-actuals.js").read_text()
		self.assertIn("if(d.needs_presence){", js)
		self.assertIn("args.confirm_present=", js)

	def test_hr_acknowledges_it_in_the_payroll_check(self):
		s = src("payment.py")
		self.assertIn('"presence_confirmed": ("ack", "HR",', s)
		self.assertIn('"confirmed_absent": ("ack", "HR",', s)

	def test_absent_pay_leaves_it_for_hr(self):
		s = (ROOT / "absent_pay.py").read_text()
		self.assertIn("IFNULL(we.presence_confirmed_by, '') = ''", s)


class TestRelease(unittest.TestCase):
	def rel(self, lw, sd, today="2026-11-19"):
		import datetime as dt
		if lw:
			return lw
		return str(dt.date.fromisoformat(sd) - dt.timedelta(days=1))

	def test_free_from_the_day_after_the_last_work(self):
		self.assertEqual(self.rel("2026-11-17", "2026-11-10"), "2026-11-17")
		# nothing recorded on a finishing plan: never busy there
		self.assertEqual(self.rel(None, "2026-11-10"), "2026-11-09")
		self.assertEqual(self.rel(None, "2026-11-25"), "2026-11-24")

	def test_closing_and_finishing_use_it(self):
		s = src("actuals.py")
		self.assertEqual(s.count("rel_day = wmg_rel_day(fr)"), 2)

	def test_release_is_open_to_the_farms_people_at_any_live_stage(self):
		b = block("assigner.py", "a_release")
		self.assertIn("wmg_crew_err(d,", b)
		self.assertIn("wmg_auto_left(", b)


class TestDelete(unittest.TestCase):
	def test_assignment_delete_refuses_one_with_actuals(self):
		b = block("assigner.py", "a_delete")
		self.assertIn("has actuals recorded against it", b)
		self.assertIn("wmg_crew_err(d,", b)
		self.assertIn("add_comment", b)

	def test_actuals_delete_never_touches_confirmed_or_paid(self):
		b = block("actuals.py", "act_delete")
		self.assertIn('dl.workflow_state == "CONFIRMED"', b)
		self.assertIn("IFNULL(payroll_check, '') != ''", b)
		self.assertIn("wmg_log_deleted(dl, dl_reason)", b)

	def test_both_are_post_only(self):
		self.assertIn('"a_delete": ""', src("assigner.py"))
		self.assertIn('"act_delete": ""', src("actuals.py"))


class TestCloseRating(unittest.TestCase):
	def test_request_and_confirm_need_a_rating(self):
		s = src("actuals.py")
		self.assertIn('"custom_close_request_rating", cl_rating', s)
		self.assertIn('{"custom_close_rating": gm_rating,', s)

	def test_every_close_dialog_sends_it(self):
		for name in ("work-actuals.js", "work-assigner.js", "work-planner.js"):
			self.assertIn("rating", (JS / name).read_text(), name)


class TestPayrollCheckAccess(unittest.TestCase):
	def test_approval_stays_with_the_approvers(self):
		s = src("payment.py")
		self.assertIn("elif not (pc_gm or af in pc_fm_appr):", s)
		self.assertIn('"approve_farms": pc_fm_appr', s)


class TestPeopleBoard(unittest.TestCase):
	def test_dashboard_serves_and_shows_it(self):
		self.assertIn('if action == "people_board":', src("dashboard.py"))
		js = (JS / "work-management-dashboard.js").read_text()
		for s in ('data-pp="on"', 'data-pp="free"', 'data-pp="acts"', 'data-pp="month"', "initPeople();"):
			self.assertIn(s, js)


if __name__ == "__main__":
	unittest.main()


class TestAbsentButAtWork(unittest.TestCase):
	"""2026-11-20: a day marked Absent can be ticked present too; the tick pays it,
	HR sees it in the payroll check, and an Attendance Request goes to HR."""

	def test_absent_days_join_the_tick_list(self):
		s = src("actuals.py")
		self.assertIn('pres_need.append({"employee": pe, "date": pd, "absent": 1,', s)
		self.assertIn("pres_absent[(pe, pd)] = 1", s)

	def test_a_ticked_absent_day_raises_an_attendance_request(self):
		s = src("actuals.py")
		self.assertIn('ar = frappe.new_doc("Attendance Request")', s)
		self.assertIn('ar.reason = "On Duty"', s)
		self.assertIn("WHERE w.document_type = 'Attendance Request' AND w.is_active = 1", s)

	def test_the_screen_says_so(self):
		js = (JS / "work-actuals.js").read_text()
		self.assertIn("marked Absent</span>", js)
		self.assertIn("d.attendance_requests", js)


class TestFarmCardCountsOpenIssues(unittest.TestCase):
	"""2026-11-20: Lokitela's card looked clean (no duplicates, nothing unfinished)
	but one quantity outlier was unacknowledged, so Approve was offered and refused."""

	def test_detail_counts_them(self):
		b = block("payment.py", "chk_detail")
		self.assertIn('by[oi_x["owner"]]["open_issues"]', b)

	def test_the_card_holds_approve_until_they_are_cleared(self):
		js = (JS / "work-payment.js").read_text()
		self.assertIn("&& !f.open_issues;", js)
		self.assertIn("Issues to fix or acknowledge", js)


class TestNobodyStaysBusyOnAFinishedPlan(unittest.TestCase):
	"""2026-11-20: David Mzee Naibei (400178) was released on the close day, the 17th,
	after his last work on the 16th, and showed "assigned elsewhere" on the 17th.
	1,731 such dates were corrected. The close and finish steps now fix every
	release date on the plan, and an hourly sweep catches anything else."""

	def want(self, lw, sd, td):
		import datetime as dt
		w = lw if lw else str(dt.date.fromisoformat(sd) - dt.timedelta(days=1))
		return td if td < w else w

	def test_the_rule(self):
		self.assertEqual(self.want("2026-11-16", "2026-11-16", "2026-11-20"), "2026-11-16")
		self.assertEqual(self.want(None, "2026-11-16", "2026-11-20"), "2026-11-15")
		self.assertEqual(self.want("2026-11-22", "2026-11-16", "2026-11-20"), "2026-11-20")

	def test_close_and_finish_correct_the_whole_plan(self):
		s = src("actuals.py")
		self.assertIn("def wmg_fix_left_dates(plan):", s)
		self.assertIn('out["release_dates_corrected"] = wmg_fix_left_dates(plan)', s)
		i = s.index("def wmg_plan_done(")
		self.assertIn("wmg_fix_left_dates(asg)", s[i:s.index("\n    def ", i + 10)])

	def test_no_work_on_a_finishing_plan_means_never_busy_there(self):
		s = src("actuals.py")
		i = s.index("def wmg_rel_day(")
		body = s[i:s.index("def wmg_fix_left_dates(", i)]
		self.assertIn('return str(frappe.utils.add_days(fr.get("sd"), -1))', body)

	def test_hourly_sweep_is_scheduled(self):
		hooks = (ROOT / "hooks.py").read_text()
		self.assertIn('"work_management.release_dates.sweep"', hooks)
		self.assertIn("pl.custom_close_state IN ('Closed', 'Completed')", (ROOT / "release_dates.py").read_text())
