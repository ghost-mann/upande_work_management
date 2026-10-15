"""Who may not approve a document: the person who raised it, or who sent it back.

Off unless Work Management Settings › "Block self-approval" is ticked.

The generated workflows allow self-approval, and the screens move documents
with `frappe.db.set_value` rather than through the workflow anyway, so nothing
in Frappe would stop a section head approving their own plan. This is the one
place that does, and every approve action asks it -- single and bulk, because
bulk re-enters the single action (work_management/bulk.py).

A REJECTION MOVES THE AUTHORSHIP. A rejected entry that somebody else fixes
and resubmits is, from then on, partly theirs: if they could approve it at the
next step, the block would be one rejection away from meaningless. So the
resubmitter is stamped on the document (`resubmitted_by`) and refused exactly
as the original author is. Only the LAST resubmitter is kept: each resubmit
replaces the one before.
"""

import frappe

REJECTED = "Rejected"

#: the field on each document that names who raised it
AUTHOR_FIELD = {
	"Work Management Planner": "requested_by",
	"Work Management Assigner": "assigned_by",
	"Work Management Actuals": "entered_by",
	"Work Management Master Plan": "raised_by",
}

NOUN = {
	"Work Management Planner": "plan",
	"Work Management Assigner": "assignment",
	"Work Management Actuals": "work record",
	"Work Management Master Plan": "master plan",
}


def is_on():
	return bool(frappe.utils.cint(
		frappe.db.get_single_value("Work Management Settings", "block_self_approval")))


def mark_resubmitted(doctype, name, previous_state, user=None):
	"""Stamp the resubmitter when a document leaves Rejected for the chain.

	Called on every submit; it does nothing unless the document was Rejected,
	so a first submission never records anybody."""
	if previous_state != REJECTED:
		return
	frappe.db.set_value(doctype, name, "resubmitted_by", user or frappe.session.user,
		update_modified=False)


def refusal(doctype, name, user=None):
	"""The sentence refusing `user` this approval, or None when they may take it."""
	if not is_on():
		return None
	user = user or frappe.session.user
	row = frappe.db.get_value(doctype, name, [AUTHOR_FIELD[doctype], "resubmitted_by"], as_dict=True)
	if not row:
		return None
	noun = NOUN.get(doctype, "document")
	if user == row.get(AUTHOR_FIELD[doctype]):
		return ("You raised this " + noun + ", so you cannot approve it. Self-approval is "
				"blocked in Work Management Settings; another approver has to take this step.")
	if user == row.get("resubmitted_by"):
		return ("You resubmitted this " + noun + " after it was rejected, so you cannot approve "
				"it. Self-approval is blocked in Work Management Settings; another approver has "
				"to take this step.")
	return None
