"""The money already wrong, as one workbook for management to decide on.

Read-only (2026-11-12): eight sheets drawn from the payroll invariants the
review tested against live. Nothing here changes a row -- applying any
correction (paying the under-stamped days, recovering a double payment) is
a separate, explicit decision.

    bench --site <site> execute work_management.pay_integrity_report.run
"""

import os

import frappe

SHEETS = [
	("Marked paid, not paid",
	 """SELECT we.payment_ref payment, p.workflow_state payment_state, we.parent actuals, we.employee,
	           we.employee_name, we.work_date, we.amount
	    FROM `tabWork Actuals Employee` we
	    LEFT JOIN `tabWork Management Payment` p ON p.name = we.payment_ref
	    WHERE IFNULL(we.payment_ref, '') != '' AND IFNULL(we.paid, 0) = 1
	      AND NOT EXISTS (SELECT 1 FROM `tabWork Payment Line` l WHERE l.parent = we.payment_ref
	          AND l.actuals = we.parent AND l.employee = we.employee
	          AND we.work_date BETWEEN l.work_from AND l.work_to)
	    ORDER BY we.employee, we.work_date"""),
	("Paid twice",
	 """SELECT we.employee, MAX(we.employee_name) employee_name, we.work_date, COUNT(*) records,
	           SUM(we.amount) - MAX(we.amount) extra_paid,
	           GROUP_CONCAT(CONCAT(we.parent, ' / ', IFNULL(we.payment_ref, '-')) SEPARATOR '; ') records_and_payments
	    FROM `tabWork Actuals Employee` we
	    INNER JOIN `tabWork Management Actuals` ac ON ac.name = we.parent
	    WHERE IFNULL(ac.workflow_state, '') != 'Rejected' AND ac.docstatus < 2 AND we.amount > 0
	      AND IFNULL(we.paid, 0) = 1
	    GROUP BY we.employee, we.work_date HAVING COUNT(*) > 1
	    ORDER BY extra_paid DESC"""),
	("Overlapping payments",
	 """SELECT a.employee, a.name payment_a, a.period_from a_from, a.period_to a_to, a.workflow_state a_state,
	           b.name payment_b, b.period_from b_from, b.period_to b_to, b.workflow_state b_state, b.amount b_amount
	    FROM `tabWork Management Payment` a
	    INNER JOIN `tabWork Management Payment` b ON b.employee = a.employee AND b.name > a.name
	      AND b.period_from <= a.period_to AND b.period_to >= a.period_from
	    WHERE a.workflow_state != 'Cancelled' AND b.workflow_state != 'Cancelled'
	    ORDER BY a.employee"""),
	("Quantity outliers paid",
	 """SELECT we.parent actuals, ac.farm, we.employee, we.employee_name, we.work_date, we.actual_quantity qty,
	           pl.daily_target, ROUND(we.actual_quantity / pl.daily_target, 1) times_target, we.amount,
	           IFNULL(we.payment_ref, '') payment
	    FROM `tabWork Actuals Employee` we
	    INNER JOIN `tabWork Management Actuals` ac ON ac.name = we.parent
	    INNER JOIN `tabWork Management Assigner` a ON a.name = ac.assignment
	    INNER JOIN `tabWork Management Planner` pl ON pl.name = a.planner_request
	    WHERE ac.workflow_state = 'CONFIRMED' AND pl.daily_target > 0 AND we.amount > 0
	      AND we.actual_quantity > 2 * pl.daily_target
	    ORDER BY times_target DESC"""),
	("Paid on Absent or no-scan days",
	 """SELECT we.parent actuals, ac.farm, we.employee, we.employee_name, we.work_date, we.amount,
	           IFNULL(we.payment_ref, '') payment, IFNULL(att.status, '') attendance,
	           EXISTS (SELECT 1 FROM `tabEmployee Checkin` c WHERE c.employee = we.employee
	                   AND c.time >= we.work_date AND c.time < DATE_ADD(we.work_date, INTERVAL 1 DAY)) scanned
	    FROM `tabWork Actuals Employee` we
	    INNER JOIN `tabWork Management Actuals` ac ON ac.name = we.parent
	    LEFT JOIN `tabAttendance` att ON att.employee = we.employee AND att.attendance_date = we.work_date
	         AND att.docstatus = 1
	    WHERE ac.workflow_state = 'CONFIRMED' AND we.amount > 0 AND we.work_date >= '2026-09-07'
	      AND (att.status = 'Absent' OR (IFNULL(att.status, '') NOT IN ('Present', 'Half Day', 'Work From Home')
	           AND NOT EXISTS (SELECT 1 FROM `tabEmployee Checkin` c2 WHERE c2.employee = we.employee
	                   AND c2.time >= we.work_date AND c2.time < DATE_ADD(we.work_date, INTERVAL 1 DAY))))
	    ORDER BY ac.farm, we.work_date"""),
	("After relieving date",
	 """SELECT we.parent actuals, ac.farm, we.employee, we.employee_name, e.relieving_date, we.work_date,
	           we.amount, IFNULL(we.payment_ref, '') payment, IFNULL(we.paid, 0) paid
	    FROM `tabWork Actuals Employee` we
	    INNER JOIN `tabWork Management Actuals` ac ON ac.name = we.parent
	    INNER JOIN `tabEmployee` e ON e.name = we.employee
	    WHERE IFNULL(ac.workflow_state, '') != 'Rejected' AND ac.docstatus < 2 AND we.amount > 0
	      AND e.relieving_date IS NOT NULL AND we.work_date > e.relieving_date
	    ORDER BY we.employee, we.work_date"""),
	("Approval gaps",
	 """SELECT name actuals, farm, workflow_state, total_payment, IFNULL(paid, 0) paid, entered_by,
	           fm_approved_by, hr_approved_by, gm_approved_by,
	           CONCAT_WS('; ',
	             IF(IFNULL(fm_approved_by, '') = '', 'no farm manager', NULL),
	             IF(IFNULL(hr_approved_by, '') = '', 'no HR', NULL),
	             IF(IFNULL(gm_approved_by, '') = '', 'no GM', NULL),
	             IF(hr_approved_by IS NOT NULL AND hr_approved_by = gm_approved_by, 'same person HR and GM', NULL),
	             IF(entered_by IN (fm_approved_by, hr_approved_by, gm_approved_by), 'self-approved', NULL)) gaps
	    FROM `tabWork Management Actuals`
	    WHERE workflow_state = 'CONFIRMED' AND creation >= '2026-08-01'
	      AND (IFNULL(fm_approved_by, '') = '' OR IFNULL(hr_approved_by, '') = '' OR IFNULL(gm_approved_by, '') = ''
	           OR hr_approved_by = gm_approved_by OR entered_by IN (fm_approved_by, hr_approved_by, gm_approved_by))
	    ORDER BY total_payment DESC"""),
	("Backdated assignments",
	 """SELECT a.name assignment, a.farm, a.owner created_by, a.from_date, DATE(a.creation) created,
	           DATEDIFF(a.creation, a.from_date) days_late,
	           (SELECT COALESCE(SUM(we.amount), 0) FROM `tabWork Actuals Employee` we
	              INNER JOIN `tabWork Management Actuals` ac ON ac.name = we.parent
	              WHERE ac.assignment = a.name AND ac.workflow_state = 'CONFIRMED') confirmed_kes
	    FROM `tabWork Management Assigner` a
	    WHERE a.docstatus < 2 AND DATEDIFF(a.creation, a.from_date) > 7
	    ORDER BY days_late DESC"""),
]


def run(out_path=None):
	"""Write the workbook and return its path. Reads only."""
	from openpyxl import Workbook

	wb = Workbook()
	wb.remove(wb.active)
	summary = []
	frappe.db.sql("SET SESSION SQL_BIG_SELECTS = 1")
	for title, query in SHEETS:
		rows = frappe.db.sql(query, as_dict=True)
		ws = wb.create_sheet(title[:31])
		cols = list(rows[0].keys()) if rows else ["(none)"]
		ws.append(cols)
		for r in rows:
			ws.append([str(r[c]) if r[c] is not None and not isinstance(r[c], (int, float)) else r[c] for c in cols])
		summary.append((title, len(rows)))
	cover = wb.create_sheet("Summary", 0)
	cover.append(["Sheet", "Rows"])
	for s in summary:
		cover.append(list(s))
	cover.append([])
	cover.append(["Read-only. Nothing in this workbook changed any record; management decides each sheet."])
	if not out_path:
		out_path = os.path.join(frappe.get_site_path("private", "files"),
			"pay_integrity_" + str(frappe.utils.today()) + ".xlsx")
	wb.save(out_path)
	return out_path
