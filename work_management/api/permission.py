# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt
"""Whether to show Work Management on the apps screen.

Anyone who takes part in the work — submits a plan, approves a step, records
actuals, pays a worker — holds one of the module's roles. Showing the tile to
everyone else is clutter.
"""

import frappe

from work_management import approvals


def has_app_permission():
	if frappe.session.user == "Administrator":
		return True

	roles = set(frappe.get_roles())
	if "System Manager" in roles:
		return True

	try:
		return bool(roles & approvals.managed_roles())
	except Exception:
		# Settings not installed yet, or unreadable for this user. Fall back to
		# the catalogue's own defaults rather than hiding the app outright.
		return bool(roles & {stage.role for stage in approvals.CATALOGUE})
