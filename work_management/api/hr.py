# Auto-release inactive employees from live assignments (portable app
# equivalent of the live "WM Auto Release Inactive" DocType Event script).
# Gated by Work Management Settings > att_auto_release_inactive (default OFF).

import frappe


def release_inactive(doc, method=None):
	if doc.status == "Active":
		return
	try:
		enabled = frappe.utils.cint(frappe.db.get_single_value("Work Management Settings", "att_auto_release_inactive"))
	except Exception:
		enabled = 0
	if not enabled:
		return
	rows = frappe.db.sql("""
		SELECT we.name rowname, a.name asg
		FROM `tabWork Assignment Employee` we
		INNER JOIN `tabWork Management Assigner` a ON we.parent = a.name
		WHERE we.employee = %s AND IFNULL(we.status,'Active') = 'Active'
		  AND a.workflow_state IN ('Pending Farm Manager','Pending HR Head','Pending GM','Assigned')
	""", (doc.name,), as_dict=True)
	touched = {}
	for r in rows:
		frappe.db.set_value("Work Assignment Employee", r.rowname, "status", "Left", update_modified=False)
		frappe.db.set_value("Work Assignment Employee", r.rowname, "left_date", frappe.utils.today(), update_modified=False)
		touched[r.asg] = 1
	for asg in touched:
		cnt = frappe.db.sql("""
			SELECT COUNT(*) n FROM `tabWork Assignment Employee`
			WHERE parent = %s AND IFNULL(status,'Active') = 'Active'
		""", (asg,), as_dict=True)
		if cnt:
			frappe.db.set_value("Work Management Assigner", asg, "assigned_count", frappe.utils.cint(cnt[0].n), update_modified=False)
		try:
			frappe.get_doc("Work Management Assigner", asg).add_comment("Comment",
				"Auto-released " + (doc.employee_name or doc.name) + " — employee deactivated in HR (status: " + str(doc.status) + ")")
		except Exception:
			pass
