# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Links into the command-centre screens.

Notification emails used to send people to the desk form. People work in the
screens, so a link now opens the screen, the tab and the document:

    /work-planner?tab=appr&ref=WM-KenTrout-00042

One convention on every screen: `tab` picks the tab, `ref` opens that
document's detail once the list has loaded. A ref the reader cannot see gets a
short message on the screen (see locate()), never a blank page.

`wm_screen_url(doc)` builds the link and is a Jinja global (hooks.py `jinja`),
so a Notification template writes `{{ wm_screen_url(doc) }}`.
"""

from urllib.parse import quote, urlencode

import frappe
from frappe import _

PLANNER = "Work Management Planner"
ASSIGNER = "Work Management Assigner"
ACTUALS = "Work Management Actuals"
MASTER_PLAN = "Work Management Master Plan"
PAYMENT = "Work Management Payment"

#: doctype -> (route, {kind: tab}). `kind` is where the document is in its
#: chain: waiting on someone (pending), sent back (rejected), or anything else
#: (final -- approved, assigned, or still a draft with its author). A master
#: plan has one tab for all of them; its detail carries the actions.
SCREENS = {
	PLANNER: ("/work-planner", {"pending": "appr", "rejected": "rej", "final": "mine"}),
	ASSIGNER: ("/work-assigner", {"pending": "aappr", "rejected": "arej", "final": "amine"}),
	ACTUALS: ("/work-actuals", {"pending": "acappr", "rejected": "acrej", "final": "acmine"}),
	MASTER_PLAN: ("/work-planner", {"pending": "mp", "rejected": "mp", "final": "mp"}),
}

#: What /work-management may open in a modal, besides the four above.
DASHBOARD_DOCTYPES = (PLANNER, ASSIGNER, ACTUALS, MASTER_PLAN, PAYMENT)

#: One message for "no such document" and "not yours to see", so a link cannot
#: be used to find out which names exist.
UNAVAILABLE = "{0} could not be opened. It may have been deleted, or you may not have access to it."


def state_kind(state, groups):
	"""pending / rejected / final for a workflow state. Pure.

	`groups` is one doctype's entry of get_config()["stage_states"]: the chain's
	own state lists, so a renamed or added step is still recognised.
	"""
	groups = groups or {}
	if state and state in (groups.get("waiting") or []):
		return "pending"
	if state and state == groups.get("reject"):
		return "rejected"
	return "final"


def screen_path(doctype, name, state, groups):
	"""The site-relative link for one document. Pure."""
	route, tabs = SCREENS[doctype]
	tab = tabs[state_kind(state, groups)]
	return route + "?" + urlencode({"tab": tab, "ref": name}, quote_via=quote)


def _groups(doctype):
	from work_management.api.config import get_config

	return ((get_config().get("stage_states") or {}).get(doctype)) or {}


def wm_screen_url(doc):
	"""The command-centre URL for a document, absolute, for emails.

	Pending -> the Approvals tab; Rejected -> the author's Rejected tab;
	anything else -> My Requests / My Assignments / My Actuals. A doctype with
	no screen falls back to its desk form, so a template never renders nothing.
	"""
	doctype = doc.get("doctype") if isinstance(doc, dict) else doc.doctype
	name = doc.get("name")
	if doctype not in SCREENS:
		return frappe.utils.get_url_to_form(doctype, name)
	return frappe.utils.get_url(
		screen_path(doctype, name, doc.get("workflow_state"), _groups(doctype)))


#: The name the brief and older notes use.
screen_url = wm_screen_url


@frappe.whitelist(methods=["GET"])
def locate(name, doctype=None):
	"""What a screen needs to open `name` from a link, or why it cannot.

	{ok: 1, doctype, name, state, kind, tab} -- `tab` is where wm_screen_url()
	would send this document -- or {ok: 0, message}. Without a doctype the
	dashboard's doctypes are tried in turn, since its links carry only a ref.
	"""
	allowed = DASHBOARD_DOCTYPES
	if doctype and doctype not in allowed:
		return {"ok": 0, "message": _(UNAVAILABLE).format(name)}
	for dt in ([doctype] if doctype else allowed):
		if not frappe.db.exists(dt, name):
			continue
		if not frappe.has_permission(dt, "read", name):
			break
		state = frappe.db.get_value(dt, name, "workflow_state") if frappe.get_meta(dt).has_field(
			"workflow_state") else None
		out = {"ok": 1, "doctype": dt, "name": name, "state": state}
		# the dashboard opens an assignment through its plan's modal
		if dt == ASSIGNER:
			out["plan"] = frappe.db.get_value(dt, name, "planner_request")
		if dt in SCREENS:
			groups = _groups(dt)
			out["kind"] = state_kind(state, groups)
			out["tab"] = SCREENS[dt][1][out["kind"]]
		return out
	return {"ok": 0, "message": _(UNAVAILABLE).format(name)}


def require_login():
	"""Send a Guest to log in and come back to the SAME link, query included.

	Frappe's own Not Permitted page builds its Login button from the request
	path alone, so `?tab=appr&ref=WM-...` was lost on the way through login and
	the person landed on the screen's first tab. Raising Redirect here keeps it.
	"""
	if frappe.session.user != "Guest":
		return
	req = frappe.request
	back = req.path
	qs = req.query_string.decode() if req and req.query_string else ""
	if qs:
		back = back + "?" + qs
	frappe.local.flags.redirect_location = "/login?" + urlencode({"redirect-to": back})
	# 302, not Redirect's default 301: browsers cache a 301, and would keep
	# sending a reader who has since logged in back to the login page
	raise frappe.Redirect(302)
