import frappe

from work_management.api.config import get_config, screen_chain, header_logo
from work_management.assets import screen_js


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.throw(frappe._("Please login to access Work Management"), frappe.PermissionError)
	context.no_cache = 1
	context.title = "Command Centre · Work Management"
	context.header_logo = header_logo()
	_cfg = get_config()
	context.taxonomy = _cfg.get("taxonomy") or {}
	# THE CHAIN THIS SITE RUNS, delivered with the page. A status chip is drawn
	# before any roles call has answered, and a screen that waits for the chain
	# prints the raw workflow state once and never corrects itself.
	context.chain = screen_chain(_cfg)
	# Cache-busted: /assets is served immutable for a year from a URL that
	# never changed, so every deploy left readers on the old script.
	context.screen_js = screen_js('work-management-dashboard.js')

	return context
