"""Switch on 'Never record work on a day marked Absent' on running sites
(asked for 2026-11-13). A Check added to an already-saved Single reads 0."""

import frappe


def execute():
	if frappe.db.exists("DocType", "Work Management Settings"):
		frappe.db.set_single_value("Work Management Settings", "att_absent_never", 1)
