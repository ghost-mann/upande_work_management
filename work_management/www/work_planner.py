import frappe

from work_management.api.config import get_config


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.throw(frappe._("Please login to access Work Management"), frappe.PermissionError)
	context.no_cache = 1
	# The page is a bare fragment, so Frappe never wraps it in base.html and its
	# `<!-- csrf_token -->` script is never emitted. The page script reads
	# window.frappe.csrf_token on every write, so the template has to carry it.
	context.csrf_token = frappe.sessions.get_csrf_token()
	context.title = "Planner · Work Management"
	context.taxonomy = get_config().get("taxonomy") or {}
	return context
