"""Grant the new repair_payments capability to the HR head on existing sites.

Added 2026-11-12 with the write lock-down: the repair tools (purge the queue,
recalculate or round wages, fix orphaned refs, recompute payroll rows) used to
be open to anyone logged in. Fresh installs default to System Manager alone;
a site already running gets the HR head too, who ran these tools until now.
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "Work Management Settings"):
		return
	settings = frappe.get_single("Work Management Settings")
	label = "Repair payments and pay rows"
	have = {(r.capability, r.role) for r in settings.get("capabilities") or []}
	added = 0
	from work_management.api.config import get_config

	hr_roles = list(get_config().get("hr_head_roles") or ["HOD HR"])
	for role in hr_roles + ["System Manager"]:
		if not frappe.db.exists("Role", role):
			continue
		if (label, role) in have or ("repair_payments", role) in have:
			continue
		settings.append("capabilities", {"capability": label, "role": role})
		added += 1
	if added:
		settings.flags.ignore_permissions = True
		settings.save()
