"""Record every worker-day already paid twice in the payroll-check audit log.

Management decided (2026-11-12) that money already overpaid is recorded, not
recovered by the system. A payroll check logs the paid-twice days inside its
own dates; this fills in the rest of history once, so the audit log starts
complete. It changes no actuals row. Safe to run again: a worker-day already
logged is skipped.

    bench --site <site> execute work_management.payroll_check_backfill.run --kwargs '{"dry_run": 0}'
"""

import frappe


def run(dry_run=True):
	rows = frappe.db.sql(
		"""
		SELECT we.name row, we.parent doc, we.employee emp, we.employee_name ename, we.work_date d,
		       ac.farm farm, we.actual_quantity qty, we.amount amount, IFNULL(we.payment_ref, '') payment_ref
		FROM `tabWork Actuals Employee` we
		INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
		INNER JOIN (
		    SELECT w.employee, w.work_date FROM `tabWork Actuals Employee` w
		    INNER JOIN `tabWork Management Actuals` a ON w.parent = a.name
		    WHERE w.parenttype = 'Work Management Actuals' AND IFNULL(a.workflow_state, '') != 'Rejected'
		      AND a.docstatus < 2 AND w.amount > 0 AND IFNULL(w.paid, 0) = 1
		    GROUP BY w.employee, w.work_date HAVING COUNT(*) > 1
		) twice ON twice.employee = we.employee AND twice.work_date = we.work_date
		WHERE we.parenttype = 'Work Management Actuals' AND IFNULL(ac.workflow_state, '') != 'Rejected'
		  AND ac.docstatus < 2 AND we.amount > 0 AND IFNULL(we.paid, 0) = 1
		ORDER BY we.employee, we.work_date, we.payment_ref
		""",
		as_dict=True,
	)
	groups = {}
	for r in rows:
		groups.setdefault((r.emp, str(r.d)), []).append(r)
	found = [g for g in groups.values() if len(g) > 1]
	out = {"found": len(found), "logged": 0, "skipped": 0,
		"amount": sum(sum(frappe.utils.flt(x.amount) for x in g[1:]) for g in found)}
	if dry_run:
		return out
	for g in found:
		emp, day = g[0].emp, str(g[0].d)
		if frappe.db.exists("Work Management Payroll Check Fix",
				{"kind": "paid twice", "employee": emp, "work_date": day}):
			out["skipped"] += 1
			continue
		fx = frappe.new_doc("Work Management Payroll Check Fix")
		fx.kind = "paid twice"
		fx.employee = emp
		fx.employee_name = g[0].ename
		fx.work_date = day
		fx.farm = g[0].farm
		fx.kept_row = g[0].row
		fx.kept_actuals = g[0].doc
		fx.zeroed_row = g[1].row
		fx.zeroed_actuals = g[1].doc
		fx.qty_before = frappe.utils.flt(g[1].qty)
		fx.amount_before = sum(frappe.utils.flt(x.amount) for x in g[1:])
		fx.payments = ", ".join(x.payment_ref or "paid" for x in g)
		fx.fixed_by = frappe.session.user
		fx.fixed_at = frappe.utils.now()
		fx.reason = "Back-filled 2026-11-12: paid on {0} records. Recorded only; management decides.".format(len(g))
		fx.insert(ignore_permissions=True)
		out["logged"] += 1
	frappe.db.commit()
	return out
