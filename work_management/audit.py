# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""What changed on a record after it was approved, and the trail behind it.

Frappe keeps a Version row per document save when `track_changes` is on, and
this app's two budget-bearing doctypes have it. What it does not keep is an
answer to the question anybody actually asks of an approved plan: *has this
moved since I approved it, and to what?*

**Two things matter about which writes are tracked.** A Version is written by the
DOCUMENT layer. Most of this app moves workflow states with
`frappe.db.set_value(..., update_modified=False)` -- deliberately, because the
workflow engine's own transition gate would refuse a script taking a step on
somebody's behalf -- and those writes leave no Version at all. That is the right
outcome: a state moving along the chain it was designed for is not an amendment.
What DOES version is a real `doc.save()`, which is what the target adjustment and
the post-approval master plan edit both use. So the Versions that exist are, near
enough, exactly the amendments.

**Child rows show up as `removed` + `added`, not `row_changed`.** Both editors
rebuild their child table -- `d.set("activities", [])` and then re-append -- so
Frappe cannot match a row to its predecessor and reports the old one gone and a
new one arrived. Measured, not assumed. So a summary that reads only
`row_changed` would report nothing for the edit most worth reporting, and this
reads all four buckets.

Computed on the server, once, and rendered in three places from that one answer:
the desk form's intro, the planner's plan-trace overlay and the master plan
detail. A summary recomputed in JavaScript is a second implementation of the same
question, and the two would disagree the first time either moved.
"""

import json

import frappe

#: Fields whose movement is bookkeeping rather than an amendment. Reporting
#: "modified changed" to somebody asking what moved is noise that buries the
#: line they needed.
NOISE = {
	"modified", "modified_by", "docstatus", "idx", "_seen", "_comments",
	"_assign", "_liked_by", "naming_series", "amended_from",
	"last_post_approval_edit_by", "last_post_approval_edit_on",
	"total_activities", "total_man_days",
}

#: When each doctype counts as approved: the states that mean approved, and the
#: fields that say when -- a precise timestamp first, a day-granular date second.
#:
#: The order matters. `approval_date` is a Date and `Version.creation` is a
#: datetime, so comparing them as strings reads EVERY same-day edit as
#: post-approval, including ones made minutes before the approval. The approve
#: action stamps `custom_approved_at` for exactly this, and the date is the
#: fallback for records approved before it did.
APPROVED_AT = {
	"Work Management Planner": (("custom_approved_at", "approval_date"), ("Approved",)),
	"Work Management Master Plan": (("gm_approved_on",), ("Approved",)),
}

#: The newest N entries of a trail, with a count of what is older. Twenty is
#: about a screenful; the number matters less than there being one, because an
#: unbounded trail on a busy record is a page nobody scrolls.
TRAIL_LIMIT = 20


def approved_on(doctype, name, doc=None):
	"""When this record was approved, or None if it has not been.

	Returns a string timestamp, because that is what Version.creation compares
	against and converting both ways invites a timezone argument nobody wants.
	"""
	fields, states = APPROVED_AT.get(doctype, ((), ()))
	if not fields:
		return None
	row = doc or frappe.db.get_value(doctype, name,
		["workflow_state"] + list(fields), as_dict=True)
	if not row or row.get("workflow_state") not in states:
		return None
	for field in fields:
		value = str(row.get(field) or "")
		if not value:
			continue
		if len(value) <= 10:
			# A date with no time. Anything that day is ambiguous, so the day
			# itself is excluded rather than swept in: under-reporting an
			# amendment is recoverable, claiming one that never happened is not.
			return value + " 23:59:59"
		return value
	return None


def _label(doctype, fieldname):
	"""A field's label, or its fieldname when the meta has nothing to say."""
	try:
		field = frappe.get_meta(doctype).get_field(fieldname)
		if field and field.label:
			return field.label
	except Exception:
		pass
	return fieldname


def _readable(value):
	if value is None or value == "":
		return "empty"
	return str(value)


def version_changes(doctype, name, since=None):
	"""Every field change on this record, newest first, as flat dicts.

	`since` filters to versions written after a timestamp -- the approval, when
	the caller wants amendments rather than history.
	"""
	filters = {"ref_doctype": doctype, "docname": name}
	rows = frappe.db.get_all("Version", filters=filters,
		fields=["name", "owner", "creation", "data"], order_by="creation desc",
		limit=200)
	out = []
	for row in rows:
		if since and str(row.creation) <= str(since):
			continue
		try:
			payload = json.loads(row.data or "{}")
		except Exception:
			continue
		for field, old, new in (payload.get("changed") or []):
			if field in NOISE:
				continue
			out.append({
				"when": str(row.creation), "who": row.owner,
				"field": field, "label": _label(doctype, field),
				"old": _readable(old), "new": _readable(new),
				"what": "%s %s → %s" % (_label(doctype, field),
					_readable(old), _readable(new)),
			})
		# Child rows are rebuilt by both editors, so Frappe reports the old one
		# removed and a new one added rather than matching them up.
		for table, _row in (payload.get("added") or []):
			out.append({"when": str(row.creation), "who": row.owner,
				"field": table, "label": _label(doctype, table),
				"old": None, "new": None,
				"what": "a row was added to %s" % _label(doctype, table)})
		for table, _row in (payload.get("removed") or []):
			out.append({"when": str(row.creation), "who": row.owner,
				"field": table, "label": _label(doctype, table),
				"old": None, "new": None,
				"what": "a row was removed from %s" % _label(doctype, table)})
		for table, _idx, field, old, new in (payload.get("row_changed") or []):
			out.append({"when": str(row.creation), "who": row.owner,
				"field": field, "label": _label(doctype, table),
				"old": _readable(old), "new": _readable(new),
				"what": "%s: %s %s → %s" % (_label(doctype, table), field,
					_readable(old), _readable(new))})
	return out


def fallback_change(doctype, name):
	"""The amendment a record can prove without any Version at all.

	Tracking starts when it is switched on; nothing is backfilled. But both
	doctypes already snapshot the approved figure -- `original_qty` on a Planner
	request and on a Master Plan Activity row -- so a record amended before
	tracking existed can still say so, from its own fields.
	"""
	if doctype == "Work Management Planner":
		row = frappe.db.get_value(doctype, name,
			["quantity", "original_qty"], as_dict=True)
		if row and frappe.utils.flt(row.original_qty) and \
				abs(frappe.utils.flt(row.quantity) - frappe.utils.flt(row.original_qty)) > 0.005:
			return {
				"field": "quantity", "label": _label(doctype, "quantity"),
				"old": _readable(frappe.utils.flt(row.original_qty)),
				"new": _readable(frappe.utils.flt(row.quantity)),
				"what": "%s %s → %s" % (_label(doctype, "quantity"),
					frappe.utils.flt(row.original_qty), frappe.utils.flt(row.quantity)),
				"who": None, "when": None,
			}
	if doctype == "Work Management Master Plan":
		rows = frappe.db.sql("""
			SELECT task, original_qty, work_qty FROM `tabWork Management Master Plan Activity`
			WHERE parent = %(p)s AND IFNULL(original_qty, 0) != 0
			  AND ABS(IFNULL(work_qty,0) - original_qty) > 0.005
			ORDER BY idx LIMIT 1
		""", {"p": name}, as_dict=True)
		if rows:
			row = rows[0]
			return {
				"field": "work_qty", "label": str(row.task),
				"old": _readable(frappe.utils.flt(row.original_qty)),
				"new": _readable(frappe.utils.flt(row.work_qty)),
				"what": "%s %s → %s" % (row.task, frappe.utils.flt(row.original_qty),
					frappe.utils.flt(row.work_qty)),
				"who": None, "when": None,
			}
	return None


@frappe.whitelist()
def amended_summary(doctype, name, doc=None):
	"""One line saying this approved record has moved, or None.

	None for a record that is not approved, or one nobody has touched since --
	so a caller can render it unconditionally and get a banner only when there
	is something to say. Pre-approval edits are the normal course of drafting a
	plan and are deliberately not reported.
	"""
	# Whitelisted for the desk Client Scripts, so the doctype is checked rather
	# than trusted: this reads Versions and Comments, and a caller naming any
	# doctype at all could read the trail of a document this app knows nothing
	# about and whose permissions it has not checked.
	if doctype not in APPROVED_AT:
		return None
	if not frappe.has_permission(doctype, "read", doc=name):
		frappe.throw(frappe._("Not permitted to read {0}").format(name),
			frappe.PermissionError)
	fields, states = APPROVED_AT.get(doctype, ((), ()))
	row = doc or frappe.db.get_value(doctype, name,
		["workflow_state"] + list(fields), as_dict=True)
	if not row or row.get("workflow_state") not in states:
		return None
	since = approved_on(doctype, name, doc=row)
	changes = version_changes(doctype, name, since=since) if since else []
	if changes:
		first = changes[0]
		# COUNT EDITS, NOT FIELDS. One target adjustment moves quantity, cost,
		# the crew and the man-days -- reporting that as "and 5 other changes"
		# makes one decision sound like six, which is the opposite of what a
		# banner is for. Saves share a timestamp, so that is the grouping.
		edits = len({str(c["when"]) for c in changes})
		more = edits - 1
		return ("Edited after approval: %s by %s on %s%s" % (
			first["what"], (first["who"] or "somebody").split("@")[0],
			str(first["when"])[:16],
			(" (and %d earlier edit%s)" % (more, "" if more == 1 else "s")) if more else ""))
	# No Version to go on -- either the change predates tracking, the approval
	# left no timestamp to measure from, or it was written below the document
	# layer. The snapshot fields still know.
	fallback = fallback_change(doctype, name)
	if fallback:
		return "Edited after approval: %s" % fallback["what"]
	return None


def change_trail(doctype, name, limit=TRAIL_LIMIT):
	"""Versions and audit comments as one list, newest first.

	Merged because they are two halves of one story: the Versions say what a
	field became, the comments say what somebody decided and why -- a rejection
	reason, a target adjustment, a post-approval edit. Read either alone and the
	record looks like it changed for no reason, or was discussed and never
	changed.
	"""
	entries = list(version_changes(doctype, name))
	for row in frappe.db.get_all("Comment",
			filters={"reference_doctype": doctype, "reference_name": name,
				"comment_type": "Comment"},
			fields=["owner", "creation", "content"], order_by="creation desc",
			limit=200):
		entries.append({
			"when": str(row.creation), "who": row.owner,
			"field": None, "label": None, "old": None, "new": None,
			"what": frappe.utils.strip_html(row.content or "").strip(),
			"is_note": 1,
		})
	entries.sort(key=lambda e: str(e.get("when") or ""), reverse=True)
	return {
		"entries": entries[:limit],
		"total": len(entries),
		"older": max(0, len(entries) - limit),
	}
