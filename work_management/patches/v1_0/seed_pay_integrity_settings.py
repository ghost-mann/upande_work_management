"""Give the 2026-11-12 pay-integrity Settings their defaults on running sites.

A field added to an already-saved Single reads 0 until somebody saves it, and
0 is not a usable value for any of these: a 0x quantity multiple refuses
every entry, and 0 backdate days refuses everything not entered today.
"""

import frappe

DEFAULTS = {"qty_flag_multiple": 2, "qty_refuse_multiple": 3, "max_backdate_days": 7}


def execute():
	if not frappe.db.exists("DocType", "Work Management Settings"):
		return
	for field, value in DEFAULTS.items():
		have = frappe.db.get_single_value("Work Management Settings", field)
		if not have:
			frappe.db.set_single_value("Work Management Settings", field, value)
