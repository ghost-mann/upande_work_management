"""No pay on a day marked Absent.

The Actuals screen already refuses work for a worker marked Absent that day
(Work Management Settings > "Never record work on a day marked Absent"). It can
only see attendance that exists when the work is entered, and attendance often
arrives later: the hourly auto-attendance run, a bulk upload, HR's corrections.
This closes that gap. When an Absent record is submitted, any unpaid pay that
worker has on that day is set to 0. The quantity is kept, so the plan's progress
is unchanged. Each change is logged as a Payroll Check Fix, against the open
check that covers the day when there is one. Cancelling the Absent record puts
the pay back. A daily sweep catches attendance written without its hooks.

A day somebody confirmed present by hand when the work was saved (no scan yet,
see presence_confirmed_by) is left for HR: the payroll check raises it to them.
A day whose pay was put back by hand (its fix entry says "Restored by
management") is left alone. A day that also has a Present / Half Day / Work From
Home record is not Absent.
Pay already paid (paid=1 or a payment reference) is never touched; the payroll
check still raises it.
"""

import frappe

ISSUE = "absent_paid"
TAG = "Auto: day marked Absent"
# A day someone put the pay back on (to verify it, or because management decided
# to pay it) is theirs: the rule never zeroes it again. Its fix entry carries this.
RESTORED = "Restored by management"


def enabled():
	return bool(frappe.db.sql("""SELECT 1 FROM `tabSingles` WHERE doctype = 'Work Management Settings'
		AND field = 'att_absent_never' AND value = '1' LIMIT 1"""))


def is_absent(employee, day):
	"""Absent that day with nothing saying they were there."""
	return bool(frappe.db.sql("""
		SELECT 1 FROM `tabAttendance` att
		WHERE att.employee = %(e)s AND att.attendance_date = %(d)s AND att.docstatus = 1 AND att.status = 'Absent'
		  AND NOT EXISTS (SELECT 1 FROM `tabAttendance` pp WHERE pp.employee = att.employee
			AND pp.attendance_date = att.attendance_date AND pp.docstatus = 1
			AND pp.status IN ('Present', 'Half Day', 'Work From Home'))
		LIMIT 1""", {"e": employee, "d": day}))


def _open_check(day):
	r = frappe.db.sql("""SELECT name FROM `tabWork Management Payroll Check`
		WHERE period_from <= %s AND period_to >= %s AND status NOT IN ('Sent', 'Cancelled')
		ORDER BY creation DESC LIMIT 1""", (day, day))
	return r[0][0] if r else None


def _retotal(parent):
	t = frappe.db.sql("""SELECT COALESCE(SUM(actual_quantity),0) q, COALESCE(SUM(amount),0) p
		FROM `tabWork Actuals Employee` WHERE parent = %s""", (parent,), as_dict=True)
	if t:
		frappe.db.set_value("Work Management Actuals", parent, {
			"total_actual_qty": frappe.utils.flt(t[0].q),
			"total_payment": round(frappe.utils.flt(t[0].p), 2)}, update_modified=False)


def zero_day(employee, day, why=None):
	"""Set unpaid pay on `day` to 0 for `employee`. Returns the rows changed."""
	rows = frappe.db.sql("""
		SELECT we.name, we.parent, we.actual_quantity, we.amount, we.employee_name, ac.farm
		FROM `tabWork Actuals Employee` we
		INNER JOIN `tabWork Management Actuals` ac ON ac.name = we.parent
		WHERE we.parenttype = 'Work Management Actuals' AND we.employee = %s AND we.work_date = %s
		  AND ac.docstatus < 2 AND IFNULL(ac.workflow_state, '') != 'Rejected'
		  AND we.amount > 0 AND IFNULL(we.paid, 0) = 0 AND IFNULL(we.payment_ref, '') = ''
		  AND IFNULL(we.presence_confirmed_by, '') = ''
		  AND NOT EXISTS (SELECT 1 FROM `tabWork Management Payroll Check Fix` fx
			WHERE fx.zeroed_row = we.name AND fx.issue = %s AND fx.reason LIKE %s)
	""", (employee, day, ISSUE, "%" + RESTORED + "%"), as_dict=True)
	if not rows:
		return []
	pc = _open_check(day)
	for r in rows:
		frappe.db.set_value("Work Actuals Employee", r.name, {"amount": 0, "custom_reviewed": 0},
			update_modified=False)
		_retotal(r.parent)
		fx = frappe.new_doc("Work Management Payroll Check Fix")
		fx.payroll_check = pc
		fx.kind = "zeroed"
		fx.issue = ISSUE
		fx.zeroed_row = r.name
		fx.zeroed_actuals = r.parent
		fx.employee = employee
		fx.employee_name = r.employee_name
		fx.work_date = day
		fx.farm = r.farm
		fx.qty_before = frappe.utils.flt(r.actual_quantity)
		fx.amount_before = frappe.utils.flt(r.amount)
		fx.fixed_by = frappe.session.user
		fx.fixed_at = frappe.utils.now()
		fx.reason = TAG + (" (" + why + ")" if why else "") + ". Pay set to 0; quantity kept."
		fx.insert(ignore_permissions=True)
	return rows


def restore_day(employee, day):
	"""Undo zero_day() once the day is no longer Absent. Only rows this rule
	zeroed, still at 0 and still unpaid."""
	fixes = frappe.get_all("Work Management Payroll Check Fix",
		filters={"employee": employee, "work_date": day, "kind": "zeroed", "issue": ISSUE},
		fields=["name", "zeroed_row", "zeroed_actuals", "amount_before", "reason", "payroll_check", "farm",
			"employee_name", "qty_before"])
	back = []
	for f in fixes:
		if not (f.reason or "").startswith(TAG) or not f.zeroed_row:
			continue
		row = frappe.db.get_value("Work Actuals Employee", f.zeroed_row, ["amount", "paid", "payment_ref"], as_dict=True)
		if not row or frappe.utils.flt(row.amount) != 0 or frappe.utils.cint(row.paid) or row.payment_ref:
			continue
		frappe.db.set_value("Work Actuals Employee", f.zeroed_row, "amount", f.amount_before, update_modified=False)
		_retotal(f.zeroed_actuals)
		frappe.db.set_value("Work Management Payroll Check Fix", f.name, "reason",
			(f.reason or "") + " Restored " + frappe.utils.now()[:16] + ": the Absent record was cancelled.",
			update_modified=False)
		back.append(f.zeroed_row)
	return back


def on_attendance_submit(doc, method=None):
	if doc.status != "Absent" or not enabled():
		return
	if is_absent(doc.employee, doc.attendance_date):
		zero_day(doc.employee, doc.attendance_date, doc.name)


def on_attendance_cancel(doc, method=None):
	if doc.status != "Absent":
		return
	if not is_absent(doc.employee, doc.attendance_date):
		restore_day(doc.employee, doc.attendance_date)


def sweep(days=60):
	"""Daily backstop: any unpaid pay still on an Absent day."""
	if not enabled():
		return 0
	n = 0
	for r in frappe.db.sql("""
		SELECT DISTINCT we.employee, we.work_date
		FROM `tabWork Actuals Employee` we
		INNER JOIN `tabWork Management Actuals` ac ON ac.name = we.parent
		INNER JOIN `tabAttendance` att ON att.employee = we.employee AND att.attendance_date = we.work_date
			AND att.docstatus = 1 AND att.status = 'Absent'
		WHERE we.parenttype = 'Work Management Actuals' AND we.work_date >= %s
		  AND ac.docstatus < 2 AND IFNULL(ac.workflow_state, '') != 'Rejected'
		  AND we.amount > 0 AND IFNULL(we.paid, 0) = 0 AND IFNULL(we.payment_ref, '') = ''
		  AND NOT EXISTS (SELECT 1 FROM `tabAttendance` pp WHERE pp.employee = we.employee
			AND pp.attendance_date = we.work_date AND pp.docstatus = 1
			AND pp.status IN ('Present', 'Half Day', 'Work From Home'))
	""", (frappe.utils.add_days(frappe.utils.today(), -days),), as_dict=True):
		n = n + len(zero_day(r.employee, r.work_date, "daily sweep"))
	frappe.db.commit()
	return n
