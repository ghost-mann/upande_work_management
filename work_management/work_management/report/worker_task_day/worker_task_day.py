# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Per worker, per task, per day: what was expected, what was done, and the clock.

HR's question is not one this app could answer from any existing screen. The
dashboard aggregates, the payment screens are money-shaped, and the review sheet
is per worker per payment run. What was missing is the flat grain underneath all
of them -- one row per worker per task per day -- with the target beside the
output and the clock beside both.

That grain is exactly `Work Actuals Employee`, so the report does not have to
invent a shape: a worker on two tasks in one day already has two rows there, and
that is what one-row-per-task-day means.

A Script Report rather than another tab on a web screen. The audience is HR, and
a Script Report arrives with the date filters, the column sort, the Excel and CSV
export and the print view already built; the screens hand-write all of that --
`work-payment.js` carries its own XLSX writer and a CSV fallback for when the CDN
fails. Role visibility comes from the Report doctype for the same reason.

TWO THINGS THIS REPORT REFUSES TO GUESS

**Clock-out.** The app has only ever read `MIN(time)` from `Employee Checkin` --
when somebody arrived -- because on live that is all there is: 864,507 checkins,
of the newest 400 some 390 are `IN` and 10 are `OUT`, and 394 of 397 employee-days
carry exactly one scan. So an absent out-scan renders BLANK. Not zero, not the
shift end, not in-time plus the standard day. A guessed departure in an HR
report is worse than an empty cell, because nothing downstream can tell it from
a measured one.

**The target on a split day.** `daily_target` is the output expected of one
person for one whole day. Somebody who gave four hours is not under target at
half of it, so the expectation is pro-rated -- `split_day.prorated_target()`,
the same tested function the discrepancy flags use. `hours` is read
unconditionally: with the split-day switch off every row holds its date's
standard hours, the pro-rating is a no-op, and the column reads exactly as the
plain daily target.

GRAIN, AND WHY THE CLOCK IS AGGREGATED FIRST

`Employee Checkin` holds many rows per employee-day and `Attendance` can hold a
cancelled or amended row beside the submitted one. Joined inline, either would
multiply this report's rows -- a worker with three scans would appear three
times, with their quantity repeated, and an HR export would overstate the day's
work. Both are therefore collapsed to one row per employee-day in a subquery
before they are joined. There is a test for exactly this.
"""

import frappe
from frappe import _

from work_management import approvals, split_day
from work_management.api.config import get_config

ACTUALS = "Work Management Actuals"

#: Where the clock comes from, in order of preference. Checkins are the raw
#: scans; Attendance is what the biometric integration rolls them into, and on a
#: site that keeps only the latter it is the sole source.
CHECKIN = "Employee Checkin"
ATTENDANCE = "Attendance"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.get("from_date") or not filters.get("to_date"):
		frappe.throw(_("Pick a date range: both From date and To date are required."))
	if str(filters.to_date) < str(filters.from_date):
		frappe.throw(_("To date {0} is before From date {1}.").format(
			filters.to_date, filters.from_date))

	rows = _rows(filters)
	return _columns(), rows


#: `_states(..., settings=FROM_SITE)` reads the chain this installation runs.
#: Passing `settings=None` instead resolves against the shipped catalogue, which
#: needs no database -- that is how the tests reach this without a site.
FROM_SITE = object()


def _states(include_pending, settings=FROM_SITE):
	"""Which workflow states count.

	Read from the configured chain rather than spelled out, so a site that has
	switched an approval step off does not lose rows from an HR report. Confirmed
	only by default: this report is payroll-adjacent, and quantities still moving
	through approval would mislead whoever reads it as a record of what happened.
	"""
	ends = approvals.CHAIN_ENDS.get(ACTUALS) or {}
	terminal = (ends.get("terminal") or ("CONFIRMED",))[0]
	if not include_pending:
		return [terminal]
	if settings is FROM_SITE:
		states = approvals.pipeline_states(document_type=ACTUALS) or {}
	else:
		states = approvals.pipeline_states(settings=settings, document_type=ACTUALS) or {}
	waiting = list(states.get("waiting") or [])
	return [terminal] + [s for s in waiting if s != terminal]


def _clock_subquery():
	"""One row per employee-day, or nothing if the site has no checkin table.

	`time >= from AND time < to + 1 day` rather than `DATE(time) BETWEEN`: the
	latter wraps the column in a function and gives up the index, which on live's
	864k rows is the difference between a report and a timeout.
	"""
	if not frappe.db.table_exists(CHECKIN):
		return None
	return """
		SELECT ck.employee employee, DATE(ck.`time`) d,
		       MIN(CASE WHEN ck.log_type = 'IN'  THEN ck.`time` END) clock_in,
		       MAX(CASE WHEN ck.log_type = 'OUT' THEN ck.`time` END) clock_out
		FROM `tabEmployee Checkin` ck
		WHERE ck.`time` >= %(from_date)s
		  AND ck.`time` < DATE_ADD(%(to_date)s, INTERVAL 1 DAY)
		GROUP BY ck.employee, DATE(ck.`time`)
	"""


def _attendance_subquery():
	"""The fallback, also collapsed to one row per employee-day.

	Aggregated even though Attendance is usually unique per employee-date: a
	cancelled row can sit beside the submitted one, and `docstatus = 1` narrowing
	it is a fact about today's data rather than a guarantee. MIN/MAX over one row
	is free; a duplicated grain in an HR export is not.
	"""
	if not frappe.db.table_exists(ATTENDANCE):
		return None
	return """
		SELECT att.employee employee, att.attendance_date d,
		       MIN(att.in_time) in_time, MAX(att.out_time) out_time,
		       MAX(att.working_hours) working_hours
		FROM `tabAttendance` att
		WHERE att.docstatus = 1
		  AND att.attendance_date BETWEEN %(from_date)s AND %(to_date)s
		GROUP BY att.employee, att.attendance_date
	"""


def _rows(filters):
	states = _states(filters.get("include_pending"))
	params = {
		"from_date": filters.from_date,
		"to_date": filters.to_date,
		"states": states,
	}

	where = ["we.work_date BETWEEN %(from_date)s AND %(to_date)s",
		"ac.workflow_state IN %(states)s"]
	if filters.get("farm"):
		where.append("ac.farm = %(farm)s")
		params["farm"] = filters.farm
	if filters.get("employee"):
		where.append("we.employee = %(employee)s")
		params["employee"] = filters.employee
	if filters.get("task"):
		where.append("ac.task = %(task)s")
		params["task"] = filters.task

	clock = _clock_subquery()
	attendance = _attendance_subquery()

	select_clock = "NULL clock_in, NULL clock_out"
	join_clock = ""
	if clock:
		select_clock = "ck.clock_in clock_in, ck.clock_out clock_out"
		join_clock = ("LEFT JOIN (" + clock + ") ck "
			"ON ck.employee = we.employee AND ck.d = we.work_date")

	select_att = "NULL att_in, NULL att_out"
	join_att = ""
	if attendance:
		select_att = "at2.in_time att_in, at2.out_time att_out"
		join_att = ("LEFT JOIN (" + attendance + ") at2 "
			"ON at2.employee = we.employee AND at2.d = we.work_date")

	data = frappe.db.sql("""
		SELECT
			we.employee, we.employee_name, we.work_date,
			ac.farm, ac.task, ac.block_section, ac.name actuals, ac.workflow_state,
			t.subject task_subject,
			COALESCE(NULLIF(pr.daily_target, 0), t.custom_daily_target) daily_target,
			we.actual_quantity, we.amount, we.hours,
			COALESCE(NULLIF(pr.uom, ''), t.custom_uom) uom,
			""" + select_clock + """,
			""" + select_att + """
		FROM `tabWork Actuals Employee` we
		INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
		-- through the assignment to the request, which is where the target was
		-- frozen when the work was planned. LEFT so a row whose plan has gone
		-- still appears, falling back to the Task's current figure.
		LEFT JOIN `tabWork Management Assigner` asg ON ac.assignment = asg.name
		LEFT JOIN `tabWork Management Planner` pr ON asg.planner_request = pr.name
		LEFT JOIN `tabTask` t ON t.name = ac.task
		""" + join_clock + """
		""" + join_att + """
		WHERE """ + " AND ".join(where) + """
		ORDER BY we.work_date, we.employee_name, t.subject, ac.name
	""", params, as_dict=True)

	model = (get_config() or {}).get("standard_day")
	return [project_row(r, model) for r in data]


def project_row(r, model=None):
	"""One database row as one report row. Pure, so it can be tested on its own.

	Everything this report promises that is not a plain column lives here: the
	pro-rated target, the clock's preference order, and the fact that an absent
	scan stays absent. Keeping it out of the query is what lets those be asserted
	without a site -- which is how the rest of this suite works.
	"""
	r = frappe._dict(r or {})
	hours = _hours_recorded(r.get("hours"))
	target = _flt(r.get("daily_target"))
	# pro-rated to the hours actually given. `hours` is None when nothing was
	# recorded, and prorated_target() reads that as the date's whole standard day
	# -- which is what every row written before the field existed means, and what
	# every row means at all while the split-day switch is off. So this is a
	# no-op there and the column equals the plain daily target.
	expected = split_day.prorated_target(target, hours, r.get("work_date"), model)
	done = _flt(r.get("actual_quantity"))
	return {
		"employee": r.get("employee"),
		"employee_name": r.get("employee_name"),
		"work_date": r.get("work_date"),
		"farm": r.get("farm"),
		# the SUBJECT, never the docname -- a site autonaming tasks
		# TASK-.YYYY.-.##### hands back an id from every read, and the fallback
		# keeps a site whose docnames ARE subjects reading exactly as before.
		"task": r.get("task_subject") or r.get("task"),
		"block_section": r.get("block_section"),
		"uom": r.get("uom"),
		"hours": hours,
		"daily_target": target or None,
		"target_for_hours": expected or None,
		"actual_quantity": done,
		# against the pro-rated figure, so a half day meeting half the target
		# reads as on target rather than as half a worker.
		"achieved_pct": (done / expected * 100) if expected else None,
		"amount": _flt(r.get("amount")),
		# The scans first, Attendance second, then nothing. NEVER a computed
		# departure: see the module docstring. `or None` rather than `or 0`,
		# because zero is a time and absence is not.
		"clock_in": r.get("clock_in") or r.get("att_in") or None,
		"clock_out": r.get("clock_out") or r.get("att_out") or None,
		"actuals": r.get("actuals"),
		"workflow_state": r.get("workflow_state"),
	}


def _flt(value):
	"""float(), tolerating None and the strings a Float column hands back."""
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0


def _hours_recorded(value):
	"""The hours on the row, or None when nothing was recorded.

	ZERO IS THE ABSENT STATE, and this is the one place it is easy to get wrong.
	Frappe makes a Float column NOT NULL DEFAULT 0, so a row written before
	`hours` existed holds 0 rather than null -- there are 30,833 of them on live,
	and every one means a whole day, because that is what a row meant before a
	day could be divided.

	`split_day.hours_of()` keeps an explicit zero as a real answer and only reads
	None as absent, which is right for its own callers. The database cannot tell
	the two apart, so the translation happens here -- the same translation the
	man-day query makes with `NULLIF(we.hours, 0)`. Reading a stored 0 as zero
	hours would give every historical row a pro-rated target of nothing and an
	achieved percentage of infinity.
	"""
	hours = _flt(value)
	return hours if hours > 0 else None


#: The column spec, as plain data with untranslated labels.
#:
#: Declared rather than built inside _columns() so the shape can be asserted
#: without a site: `_()` reaches for redis and the translation cache, which a
#: pure test has not got. _columns() applies the translation on the way out.
#:
#: `task` is deliberately Data and NOT a Link to Task. A Link renders the
#: DOCNAME whatever the row holds, which on a site autonaming tasks
#: TASK-.YYYY.-.##### is the very id this report exists to stop showing.
COLUMNS = [
	{"fieldname": "employee", "label": "Employee", "fieldtype": "Link",
		"options": "Employee", "width": 110},
	{"fieldname": "employee_name", "label": "Worker", "fieldtype": "Data", "width": 170},
	{"fieldname": "work_date", "label": "Date", "fieldtype": "Date", "width": 95},
	{"fieldname": "task", "label": "Task", "fieldtype": "Data", "width": 190},
	{"fieldname": "farm", "label": "Farm", "fieldtype": "Data", "width": 120},
	{"fieldname": "block_section", "label": "Block / Section", "fieldtype": "Data",
		"width": 120},
	{"fieldname": "hours", "label": "Hours", "fieldtype": "Float",
		"precision": 2, "width": 75},
	{"fieldname": "daily_target", "label": "Daily target", "fieldtype": "Float",
		"precision": 2, "width": 105},
	{"fieldname": "target_for_hours", "label": "Target for hours", "fieldtype": "Float",
		"precision": 2, "width": 120},
	{"fieldname": "actual_quantity", "label": "Actual qty", "fieldtype": "Float",
		"precision": 2, "width": 100},
	{"fieldname": "uom", "label": "UoM", "fieldtype": "Data", "width": 90},
	{"fieldname": "achieved_pct", "label": "Achieved %", "fieldtype": "Percent",
		"width": 100},
	{"fieldname": "amount", "label": "Amount", "fieldtype": "Currency", "width": 110},
	{"fieldname": "clock_in", "label": "Clock in", "fieldtype": "Datetime", "width": 150},
	{"fieldname": "clock_out", "label": "Clock out", "fieldtype": "Datetime", "width": 150},
	{"fieldname": "actuals", "label": "Actuals", "fieldtype": "Link",
		"options": "Work Management Actuals", "width": 130},
	{"fieldname": "workflow_state", "label": "State", "fieldtype": "Data", "width": 130},
]


def _columns():
	return [dict(column, label=_(column["label"])) for column in COLUMNS]
