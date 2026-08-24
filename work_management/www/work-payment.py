import frappe

from work_management.api.config import get_config


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.throw(frappe._("Please login to access Work Management"), frappe.PermissionError)
	context.no_cache = 1
	context.title = "Payment · Work Management"
	# Printed and exported audit documents are headed with this.
	context.org_name = get_config().get("default_company") or ""
	return context
