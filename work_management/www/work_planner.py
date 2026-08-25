import frappe

from work_management.api.config import get_config


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.throw(frappe._("Please login to access Work Management"), frappe.PermissionError)
	context.no_cache = 1
	context.title = "Planner · Work Management"
	context.taxonomy = get_config().get("taxonomy") or {}
	return context
