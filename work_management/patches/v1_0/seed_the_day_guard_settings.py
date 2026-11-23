"""Give the two day-guard Settings their values on a site that already exists.

The trap the closed-short and new-discrepancy patches describe: a `default` on
a field of a Single reaches a FRESH install only. Added to an existing Work
Management Settings, a Check arrives as 0 and a Float as nothing.

* `disc_multi_standard` -- "More than one day's standard on one date" in
  Payment -> Discrepancies. Arriving off would ship it invisible. New, so no
  site can have switched it off deliberately yet: switched on where 0.
* `max_hours_per_day` -- the ceiling day_guard refuses hour-based rows over.
  The code already reads empty as 8, so nothing about what is refused moves;
  this only writes the 8 where the box is empty, so the figure in force is the
  figure Settings shows. A value somebody typed is never touched.
"""

import frappe

SETTINGS = "Work Management Settings"
NEW_CHECKS = ("disc_multi_standard",)
DEFAULTS = {"max_hours_per_day": 8}


def execute():
	if not frappe.db.exists("DocType", SETTINGS):
		return
	meta = frappe.get_meta(SETTINGS)
	written = []
	for field in NEW_CHECKS:
		if meta.get_field(field) and not frappe.utils.cint(frappe.db.get_single_value(SETTINGS, field)):
			frappe.db.set_single_value(SETTINGS, field, 1)
			written.append(field)
	for field, value in DEFAULTS.items():
		if meta.get_field(field) and not frappe.utils.flt(frappe.db.get_single_value(SETTINGS, field)):
			frappe.db.set_single_value(SETTINGS, field, value)
			written.append(field)
	if written:
		frappe.clear_cache(doctype=SETTINGS)
		print("Work Management: day-guard settings seeded: " + ", ".join(written))
