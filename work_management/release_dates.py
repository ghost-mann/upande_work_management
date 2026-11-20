"""No worker stays "assigned elsewhere" past their last day of work on a finished plan.

When a plan is closed early or finishes (custom_close_state Closed / Completed)
no more work can be recorded on it, so a released worker's left date can be no
later than the last day they have work on it -- or, with none, the day before
they started. The close and finish steps write that date themselves
(wmg_rel_day / wmg_fix_left_dates in api/actuals.py). This hourly sweep is the
backstop for anything that reaches a finished plan another way: a hand-picked
release date ahead of the entries, actuals rejected or deleted after the close,
an older release. 2026-11-20: 1,731 such dates were found and corrected; David
Mzee Naibei (400178) could not be assigned because of one.
"""

import frappe

LOOKBACK_DAYS = 21  # new assignments may be backdated 7 days at most; older dates never block anyone


def stale_rows(since=None):
	"""Left rows on finished plans whose left date is past their last day of work."""
	since = since or frappe.utils.add_days(frappe.utils.today(), -LOOKBACK_DAYS)
	rows = frappe.db.sql("""
		SELECT we.name row_id, we.employee, we.left_date, a.name asg, a.to_date td,
		       COALESCE(we.start_date, a.from_date) sd,
		       (SELECT MAX(w.work_date) FROM `tabWork Actuals Employee` w
		        INNER JOIN `tabWork Management Actuals` ac ON ac.name = w.parent
		        WHERE ac.assignment = a.name AND w.employee = we.employee AND ac.docstatus < 2
		          AND IFNULL(ac.workflow_state, '') != 'Rejected'
		          AND (IFNULL(w.actual_quantity, 0) > 0 OR IFNULL(w.amount, 0) > 0)) lw
		FROM `tabWork Assignment Employee` we
		INNER JOIN `tabWork Management Assigner` a ON a.name = we.parent
		INNER JOIN `tabWork Management Planner` pl ON pl.name = a.planner_request
		WHERE IFNULL(we.status, 'Active') = 'Left' AND we.left_date IS NOT NULL
		  AND pl.custom_close_state IN ('Closed', 'Completed')
		  AND a.to_date >= %s
	""", (since,), as_dict=True)
	out = []
	for r in rows:
		want = str(r.lw) if r.lw else str(frappe.utils.add_days(r.sd, -1))
		if r.td and str(r.td) < want:
			want = str(r.td)
		if str(r.left_date) > want:
			r["want"] = want
			out.append(r)
	return out


def sweep():
	"""Hourly: move each stale left date back to the last day worked."""
	if not frappe.db.has_column("Work Management Planner", "custom_close_state"):
		return 0
	fixed = stale_rows()
	for r in fixed:
		frappe.db.set_value("Work Assignment Employee", r.row_id, "left_date", r.want, update_modified=False)
	if fixed:
		frappe.db.commit()
		frappe.logger("work_management").info("release_dates.sweep moved %s left dates" % len(fixed))
	return len(fixed)
