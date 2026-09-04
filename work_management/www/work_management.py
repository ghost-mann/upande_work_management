import frappe

from work_management.api.config import get_config, header_logo
from work_management.assets import screen_js


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.throw(frappe._("Please login to access Work Management"), frappe.PermissionError)
	context.no_cache = 1
	context.title = "Command Centre · Work Management"
	context.header_logo = header_logo()
	context.taxonomy = get_config().get("taxonomy") or {}
	# Cache-busted: /assets is served immutable for a year from a URL that
	# never changed, so every deploy left readers on the old script.
	context.screen_js = screen_js('work-management-dashboard.js')

	return context
