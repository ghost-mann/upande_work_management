"""Altura pays casual workers monthly, from the 21st to the 20th.

The `altura` branch is Altura's alone (docs/ALTURA_FORK.md), so this seeds
Altura's answer -- Pay frequency = Monthly, Month start day = 21 -- on whatever
site runs this branch, without keying on a hostname.

INSERT IF MISSING, NEVER OVERWRITE. A field added to a Single arrives with no
row in tabSingles at all (measured on kentrout.local: neither field had one
after the migrate that added them), so "missing" is exactly "no stored row".
A site whose Settings already hold a value -- Weekly chosen on purpose, or a
start day of 20 because the client settled the other reading -- keeps it.
Each field is decided on its own: a site that has chosen Monthly but not yet a
start day still gets 21.

The client has not fully confirmed the cut-off direction. The start day is
therefore a setting and not a constant; changing it to 20 needs no code.
Confirm both values in Settings before the first monthly feed.
"""

import frappe

SEED = (
	("pay_frequency", "Monthly"),
	("pay_month_start_day", 21),
)


def stored(field):
	"""The raw tabSingles row for one field: None when the site never set it."""
	rows = frappe.db.sql(
		"SELECT value FROM `tabSingles` WHERE doctype = %s AND field = %s",
		("Work Management Settings", field),
	)
	if not rows or rows[0][0] in (None, ""):
		return None
	return rows[0][0]


def execute():
	if not frappe.db.exists("DocType", "Work Management Settings"):
		return
	meta = frappe.get_meta("Work Management Settings")
	seeded = []
	for field, value in SEED:
		if not meta.get_field(field):
			# not synced yet; the next migrate brings the field and this with it
			continue
		if stored(field) is not None:
			continue
		frappe.db.set_single_value("Work Management Settings", field, value)
		seeded.append("%s=%s" % (field, value))
	if seeded:
		frappe.db.commit()
		frappe.clear_cache(doctype="Work Management Settings")
		print("seeded: %s" % ", ".join(seeded))
