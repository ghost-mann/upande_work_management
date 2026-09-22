import frappe

from work_management.api.config import get_config, screen_chain
from work_management.assets import screen_js


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.throw(frappe._("Please login to access Work Management"), frappe.PermissionError)
	context.no_cache = 1
	# The page is a bare fragment, so Frappe never wraps it in base.html and its
	# `<!-- csrf_token -->` script is never emitted. The page script reads
	# window.frappe.csrf_token on every write, so the template has to carry it.
	context.csrf_token = frappe.sessions.get_csrf_token()
	context.title = "Assigner · Work Management"
	_cfg = get_config()
	context.taxonomy = _cfg.get("taxonomy") or {}
	# THE CHAIN THIS SITE RUNS, delivered with the page. A status chip is drawn
	# before any roles call has answered, and a screen that waits for the chain
	# prints the raw workflow state once and never corrects itself.
	context.chain = screen_chain(_cfg)
	# Cache-busted: /assets is served immutable for a year from a URL that
	# never changed, so every deploy left readers on the old script.
	context.screen_js = screen_js('work-assigner.js')

	return context
