"""Give 'Cut-off on the day before' its 18:00 default on running sites
(2026-11-26). A field added to an already-saved Single reads empty, so the form
would show no cut-off while assign_ahead falls back to 18:00 behind it."""

import frappe


def execute():
	if not frappe.db.exists("DocType", "Work Management Settings"):
		return
	if not frappe.db.get_single_value("Work Management Settings", "assign_cutoff_time"):
		frappe.db.set_single_value("Work Management Settings", "assign_cutoff_time", "18:00:00")
