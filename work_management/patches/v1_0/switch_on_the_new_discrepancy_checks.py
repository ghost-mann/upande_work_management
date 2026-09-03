"""Switch on the three hours checks, which arrive off through no choice of anyone's.

A `default` on a doctype field applies to a NEW document. Work Management
Settings is a Single that already exists on every site, so adding a Check field
to it writes `'0'` into tabSingles -- not null, and not the field's default.

The audit reads each check's toggle with `get_single_value` and treats it as a
real answer, so all three arrived switched off:

    disc_dup_day        stored=1    an existing flag
    disc_long_day       stored=0    disabled=1
    disc_short_day      stored=0    disabled=1
    disc_hours_vs_qty   stored=0    disabled=1

Three new checks, shipped invisible. Nothing in the code was wrong -- the field
says default 1, the audit honours the toggle, and the toggle honestly reports
what is stored.

This is the second time the same trap has cost something in this release: the
standard-hours fields came out as {0, 0, 0} the same way and made every man-day
zero. Worth knowing when adding the next field to a Single: whatever its
default says, an existing site gets 0.

Only these three, and only where the stored value is 0. They are new, so no site
can have deliberately switched one off yet -- which is exactly why this can run
now and could not run later. A `disc_*` field turned off by hand looks identical
to one that was never set, and correcting those indiscriminately would override
somebody's decision.
"""

import frappe

# The three added with the hours work. Named individually on purpose -- see above.
NEW_CHECKS = ("disc_long_day", "disc_short_day", "disc_hours_vs_qty")


def execute():
	if not frappe.db.exists("DocType", "Work Management Settings"):
		return
	meta = frappe.get_meta("Work Management Settings")
	switched = []
	for field in NEW_CHECKS:
		if not meta.get_field(field):
			# the field has not arrived yet; the next migrate will bring both
			continue
		try:
			stored = frappe.db.get_single_value("Work Management Settings", field)
		except Exception:
			stored = None
		if frappe.utils.cint(stored):
			continue
		frappe.db.set_single_value("Work Management Settings", field, 1)
		switched.append(field)
	if switched:
		frappe.db.commit()
		frappe.clear_cache(doctype="Work Management Settings")
		print("switched on: %s" % ", ".join(switched))
	else:
		print("the new discrepancy checks are already on")
