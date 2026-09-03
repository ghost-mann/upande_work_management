"""Clear submit/cancel/amend from this app's DocPerms that have no write.

Frappe refuses that combination -- "Cannot set Submit, Cancel, Amend without
Write" (doctype.py:1899) -- and it refuses it whenever *anything* saves the
doctype's permissions, not when the bad grant is added. So one row makes every
later permission write on that doctype fail, and the message names whichever row
Frappe reached first, which is rarely the only one.

`Work Management Planner` shipped it for four roles from the app's first commit,
meaning approve-but-do-not-edit. Frappe has no way to express that, and the app
does not need it to: api/planner.py sets docstatus with frappe.db.set_value and
never consults the grant, so who may approve is decided by the stage's configured
role and the farm check beside it. What these rows give up is the desk form's own
Submit button.

The shipped JSON and seed.kaitet are corrected, which settles a new site. This
patch is for the sites that already have the row, where neither correction
reaches: once a doctype has Custom DocPerms, Frappe reads those and ignores the
shipped permissions entirely, and restore_docperms() skips a doctype/role that
already has a row. kaitet.local carries two, for Accounts Manager and General
Manager.

Bounded to this app's own doctypes, deliberately and tested. The same site has
eighteen more invalid rows on Pick List, Stock Entry, BOM, Purchase Invoice,
Tractor Daily Task and others -- the same defect, belonging to other apps.
Rewriting another app's permissions during this app's migrate would be a worse
bug than the one being fixed, so those are reported by the log and left alone.
"""

import frappe

from work_management import install

# In this order, so a second run's log reads the same as the first.
DEPENDENT = ("submit", "cancel", "amend")


def rights_to_clear(row):
	"""Which of submit/cancel/amend this row holds illegally.

	Empty when the row has `write`: the combination is legal then, and that is
	what every other submittable doctype in this app grants these roles.

	A missing key counts as absent, because the shipped JSON omits a right rather
	than setting it to 0.
	"""
	if row.get("write"):
		return []
	return [right for right in DEPENDENT if row.get(right)]


def is_ours(doctype, shipped):
	"""Whether this app ships the doctype, and may therefore repair its grants."""
	return doctype in shipped


def execute():
	shipped = set(install.shipped_doctypes())
	repaired, outside = [], []

	for kind in ("Custom DocPerm", "DocPerm"):
		if not frappe.db.exists("DocType", kind):
			continue
		for row in frappe.get_all(
			kind,
			filters={"permlevel": 0},
			fields=["name", "parent", "role", "submit", "cancel", "amend", "write"],
		):
			clear = rights_to_clear(row)
			if not clear:
				continue
			if not is_ours(row.parent, shipped):
				outside.append(f"{row.parent} ({row.role})")
				continue
			for right in clear:
				# Straight to the row: writing it as a document would re-run the
				# doctype's permission validation, which is the very thing this
				# row is currently making fail.
				frappe.db.set_value(kind, row.name, right, 0, update_modified=False)
			repaired.append(f'{row.parent} ({row.role}): cleared {"/".join(clear)}')

	if repaired:
		frappe.clear_cache()
		print("Work Management: repaired %d DocPerm(s) that granted submit "
			"without write -> %s" % (len(repaired), "; ".join(sorted(repaired))))
	if outside:
		# Named rather than fixed. Somebody has to know they are there, and the
		# app that owns them is the one that should decide what they become.
		print("Work Management: %d DocPerm(s) with the same fault belong to other "
			"apps and were left alone -> %s"
			% (len(outside), "; ".join(sorted(set(outside)))))
	frappe.db.commit()
