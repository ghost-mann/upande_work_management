"""Per worker, per task, per day -- and the two things it must not invent.

HR asked for a flat row per worker per task per day: the task, the daily target,
what was actually done, and the clock at both ends. The grain is already
`Work Actuals Employee`, so the report does not have to invent a shape -- a
worker on two tasks in one day has two rows there already.

What needs holding down is everything the report computes rather than selects:

**The clock is aggregated before it is joined.** `Employee Checkin` holds many
rows per employee-day. Joined inline, a worker with three scans appears three
times with their quantity repeated, and an HR export overstates the day. That is
the failure this file exists to prevent, and it is asserted structurally against
the query text -- a subquery with its own GROUP BY, never a bare join.

**An absent out-scan stays absent.** The app has only ever read arrival, because
on live that is all there is: of the newest 400 checkins some 390 are IN and 10
are OUT, and 394 of 397 employee-days carry one scan. So clock_out is None, not
zero and not in-time plus a standard day. A guessed departure in an HR report is
worse than an empty cell, because nothing downstream can tell it from a measured
one.

**The target is pro-rated by hours.** Somebody who gave four hours is not under
target at half of it. With the split-day switch off every row holds its date's
standard hours and the pro-rating is a no-op, so this is safe either way.

Pure -- no site. `project_row()` was factored out of the query for exactly that::

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_the_worker_task_day_report -v
"""

import inspect
import json
import os
import re
import unittest

from work_management import approvals
from work_management.work_management.report.worker_task_day import worker_task_day as report

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT_DIR = os.path.join(HERE, "work_management", "report", "worker_task_day")

# a Monday, so the standard day is 8 hours
WEEKDAY = "2026-10-05"
# a Saturday, where the standard day is 6 -- a full Saturday expects the WHOLE
# target, which is the case that catches a hardcoded 8
SATURDAY = "2026-10-10"


def row(**over):
	base = {
		"employee": "HR-EMP-00002", "employee_name": "Peter Mwangi",
		"work_date": WEEKDAY, "farm": "KenTrout Farm", "task": "TASK-2026-00003",
		"task_subject": "Weeding", "block_section": "GH-5 - U", "uom": "Bay",
		"daily_target": 3.0, "actual_quantity": 3.0, "amount": 400.0, "hours": 8.0,
		"clock_in": None, "clock_out": None, "att_in": None, "att_out": None,
		"actuals": "WMAC-00179", "workflow_state": "CONFIRMED",
	}
	base.update(over)
	return base


class TestTheClockIsNeverInvented(unittest.TestCase):
	def test_no_scan_at_all_leaves_both_ends_blank(self):
		out = report.project_row(row())
		self.assertIsNone(out["clock_in"])
		self.assertIsNone(out["clock_out"])

	def test_an_in_scan_with_no_out_scan_leaves_clock_out_blank(self):
		"""The ordinary case on this data, and the one worth being explicit about."""
		out = report.project_row(row(clock_in="2026-10-05 06:58:00"))
		self.assertEqual(out["clock_in"], "2026-10-05 06:58:00")
		self.assertIsNone(out["clock_out"],
			"an absent out-scan must stay absent, not become a guessed departure")

	def test_blank_is_none_and_not_zero(self):
		"""Zero is a time. Absence is not, and a 0 would render as midnight."""
		out = report.project_row(row())
		self.assertNotEqual(out["clock_out"], 0)
		self.assertIsNone(out["clock_out"])

	def test_attendance_fills_in_when_there_are_no_scans(self):
		out = report.project_row(row(
			att_in="2026-10-05 07:02:00", att_out="2026-10-05 16:30:00"))
		self.assertEqual(out["clock_in"], "2026-10-05 07:02:00")
		self.assertEqual(out["clock_out"], "2026-10-05 16:30:00")

	def test_the_scans_win_over_attendance(self):
		"""Checkins are the raw measurement; Attendance is derived from them."""
		out = report.project_row(row(
			clock_in="2026-10-05 06:58:00", att_in="2026-10-05 08:00:00"))
		self.assertEqual(out["clock_in"], "2026-10-05 06:58:00")

	def test_attendance_can_supply_only_the_end_it_has(self):
		out = report.project_row(row(
			clock_in="2026-10-05 06:58:00", att_out="2026-10-05 16:30:00"))
		self.assertEqual(out["clock_in"], "2026-10-05 06:58:00")
		self.assertEqual(out["clock_out"], "2026-10-05 16:30:00")


class TestTheTargetIsProRated(unittest.TestCase):
	def test_a_whole_day_expects_the_whole_target(self):
		out = report.project_row(row(hours=8.0, daily_target=3.0))
		self.assertEqual(out["target_for_hours"], 3.0)
		self.assertEqual(out["achieved_pct"], 100.0)

	def test_a_split_day_expects_half_of_it(self):
		"""The headline case: four hours of an eight-hour day."""
		out = report.project_row(row(hours=4.0, daily_target=3.0, actual_quantity=1.5))
		self.assertEqual(out["target_for_hours"], 1.5)
		self.assertEqual(out["achieved_pct"], 100.0,
			"a half-day worker meeting half the target is ON target")

	def test_the_split_day_this_sprint_actually_drove(self):
		"""3 Bay in 4 hours against a 3/day target -- twice the pro-rated figure."""
		out = report.project_row(row(hours=4.0, daily_target=3.0, actual_quantity=3.0))
		self.assertEqual(out["target_for_hours"], 1.5)
		self.assertEqual(out["achieved_pct"], 200.0)

	def test_a_full_saturday_expects_the_whole_target_not_six_eighths(self):
		"""Six hours IS the day on a Saturday, so the fraction is against six."""
		out = report.project_row(row(work_date=SATURDAY, hours=6.0, daily_target=3.0))
		self.assertEqual(out["target_for_hours"], 3.0)

	def test_absent_hours_read_as_a_whole_day(self):
		"""Every row written before `hours` existed means a full day, and with
		the split-day switch off that is every row.

		Frappe stores 0 for those, not null, so a stored 0 has to be read as
		absent -- the same translation `NULLIF(we.hours, 0)` makes in the man-day
		query. Reading it as zero hours would give 30,833 live rows a pro-rated
		target of nothing.
		"""
		for absent in (0, 0.0, None, ""):
			with self.subTest(hours=absent):
				out = report.project_row(row(hours=absent, daily_target=3.0))
				self.assertEqual(out["target_for_hours"], 3.0)
				self.assertIsNone(out["hours"], "an unrecorded hour shows blank")

	def test_an_explicit_zero_is_not_reported_as_zero_hours_worked(self):
		"""The column blanks rather than claiming somebody worked no time."""
		self.assertIsNone(report.project_row(row(hours=0))["hours"])

	def test_no_target_gives_no_percentage_rather_than_a_division_error(self):
		out = report.project_row(row(daily_target=0))
		self.assertIsNone(out["target_for_hours"])
		self.assertIsNone(out["achieved_pct"])

	def test_the_full_daily_target_is_reported_beside_the_pro_rated_one(self):
		"""HR asks "what was expected of a whole day" too, and a single column
		cannot answer both questions."""
		out = report.project_row(row(hours=4.0, daily_target=3.0))
		self.assertEqual(out["daily_target"], 3.0)
		self.assertEqual(out["target_for_hours"], 1.5)


class TestTheTaskIsNamed(unittest.TestCase):
	def test_the_subject_is_what_is_shown(self):
		self.assertEqual(report.project_row(row())["task"], "Weeding")

	def test_it_falls_back_to_the_docname(self):
		"""A site whose tasks ARE named by subject has no separate subject to
		show, and must read exactly as it did."""
		out = report.project_row(row(task_subject=None, task="FIELD IRRIGATION"))
		self.assertEqual(out["task"], "FIELD IRRIGATION")

	def test_the_column_is_data_not_a_link_to_task(self):
		"""A Link column renders the docname however the row is projected, which
		is the whole bug this avoids."""
		col = [c for c in report.COLUMNS if c["fieldname"] == "task"][0]
		self.assertEqual(col["fieldtype"], "Data")
		self.assertNotIn("options", col)


class TestTheGrainCannotMultiply(unittest.TestCase):
	"""Many scans in a day must not become many rows for that day."""

	def source(self):
		return inspect.getsource(report)

	def test_the_checkins_are_collapsed_before_they_are_joined(self):
		sub = report._clock_subquery.__doc__ and inspect.getsource(report._clock_subquery)
		self.assertIn("GROUP BY ck.employee, DATE(ck.`time`)", sub,
			"one row per employee-day, or the join multiplies the report")
		self.assertIn("MIN(CASE WHEN ck.log_type = 'IN'", sub)
		self.assertIn("MAX(CASE WHEN ck.log_type = 'OUT'", sub)

	def test_attendance_is_collapsed_too(self):
		"""A cancelled row can sit beside the submitted one."""
		sub = inspect.getsource(report._attendance_subquery)
		self.assertIn("GROUP BY att.employee, att.attendance_date", sub)

	def test_no_checkin_table_is_joined_directly(self):
		"""The shape that would multiply: a bare LEFT JOIN on the raw table."""
		text = self.source()
		self.assertIsNone(
			re.search(r"LEFT JOIN\s+`tabEmployee Checkin`", text),
			"Employee Checkin must be joined as an aggregated subquery, never directly")
		self.assertIsNone(
			re.search(r"LEFT JOIN\s+`tabAttendance`", text),
			"Attendance must be joined as an aggregated subquery, never directly")

	def test_the_time_predicate_can_use_the_index(self):
		"""`DATE(time) BETWEEN` wraps the column and gives up the index; on live's
		864k checkins that is the difference between a report and a timeout."""
		sub = inspect.getsource(report._clock_subquery)
		self.assertIn("ck.`time` >= %(from_date)s", sub)
		self.assertIn("DATE_ADD(%(to_date)s, INTERVAL 1 DAY)", sub)
		self.assertNotIn("DATE(ck.`time`) BETWEEN", sub)

	def test_a_missing_checkin_table_is_a_blank_column_not_a_crash(self):
		"""Guard every read of a doctype a site may not have."""
		text = self.source()
		self.assertIn('frappe.db.table_exists(CHECKIN)', text)
		self.assertIn('frappe.db.table_exists(ATTENDANCE)', text)


class TestWhichRowsCount(unittest.TestCase):
	def test_confirmed_only_by_default(self):
		"""Payroll-adjacent: quantities still in approval would mislead."""
		self.assertEqual(report._states(False), ["CONFIRMED"])

	def test_the_terminal_state_is_read_from_the_chain_not_spelled_out(self):
		terminal = approvals.CHAIN_ENDS["Work Management Actuals"]["terminal"][0]
		self.assertEqual(report._states(False), [terminal])

	def test_including_pending_adds_the_waiting_states_and_keeps_confirmed(self):
		# settings=None resolves against the shipped catalogue -- no site needed
		states = report._states(True, settings=None)
		self.assertIn("CONFIRMED", states)
		self.assertGreater(len(states), 1)
		self.assertEqual(len(states), len(set(states)), "no state twice")


class TestTheFiltersHRActuallyNeeds(unittest.TestCase):
	def filters(self):
		with open(os.path.join(REPORT_DIR, "worker_task_day.js")) as handle:
			return handle.read()

	def test_the_dates_are_required_and_the_rest_are_not(self):
		text = self.filters()
		for name in ("from_date", "to_date"):
			block = text[text.index('fieldname: "%s"' % name):][:400]
			self.assertIn("reqd: 1", block, name + " must be required")
		for name in ("farm", "employee", "task"):
			block = text[text.index('fieldname: "%s"' % name):][:400]
			self.assertNotIn("reqd: 1", block, name + " must stay optional")

	def test_a_single_day_is_the_default(self):
		""""Show me today" is the commonest question, and a month-wide default
		on live's volume would be a slow first load."""
		text = self.filters()
		self.assertEqual(text.count("frappe.datetime.get_today()"), 2)

	def test_pending_is_off_by_default(self):
		block = self.filters()
		block = block[block.index('fieldname: "include_pending"'):][:400]
		self.assertIn("default: 0", block)

	def test_the_clock_out_caveat_is_on_the_page(self):
		"""The report's most confusing feature, explained where it is read."""
		text = self.filters()
		self.assertIn("add_inner_message", text)
		self.assertIn("out-scan", text)


class TestItIsAStandardReportTheRightPeopleCanOpen(unittest.TestCase):
	def definition(self):
		with open(os.path.join(REPORT_DIR, "worker_task_day.json")) as handle:
			return json.load(handle)

	def test_it_is_a_standard_script_report_in_this_module(self):
		doc = self.definition()
		self.assertEqual(doc["report_type"], "Script Report")
		self.assertEqual(doc["is_standard"], "Yes")
		self.assertEqual(doc["module"], "Work Management")
		self.assertEqual(doc["ref_doctype"], "Work Management Actuals")

	def test_hr_can_open_it(self):
		roles = {r["role"] for r in self.definition()["roles"]}
		self.assertIn("HR User", roles)
		self.assertIn("HR Manager", roles)
		self.assertIn("System Manager", roles)

	def test_it_names_no_role_this_app_refuses_to_ship(self):
		"""HOD HR and HR Clerk are two of the five job titles this app was
		stopped from inventing. Report.roles is a Link, so naming one would fail
		the import on a site that has not got it -- Altura adds them by hand.
		"""
		invented = {"Farm Manager", "General Manager", "HOD HR", "HR Clerk",
			"Production Section Head"}
		roles = {r["role"] for r in self.definition()["roles"]}
		self.assertEqual(roles & invented, set())
