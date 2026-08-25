"""Turn the level above the farm on where a site is already using it.

`Work Management Farm.business_unit` shipped visible, with no flag governing
it. `tax_bu_enabled` came later and defaults to off, and the field is now
hidden while the level is off -- which is right for the projects that have
never heard of business units, and wrong for the ones that had already started
filling the field in. For them the next migrate would take a populated field
off the form with nothing to say where it went.

So the data decides. A farm carrying a business unit is a site saying the
level exists; this turns the flag on once, and `apply_business_unit_visibility`
(after_migrate, which runs after patches) reveals the field again.

It runs once. An admin who turns the level off afterwards is not overruled.
"""

import frappe


def should_enable(farms_with_a_unit, already_enabled):
	"""Whether to turn the level on: it is in use, and nobody has said so yet.

	Not "in use and off" alone -- rewriting a flag that is already on would be
	a pointless write, and the return value is what the caller reports.
	"""
	return bool(farms_with_a_unit) and not already_enabled


def execute():
	if not frappe.db.exists("DocType", "Work Management Farm"):
		return
	if not frappe.get_meta("Work Management Farm").get_field("business_unit"):
		return

	in_use = frappe.db.count("Work Management Farm", {"business_unit": ["!=", ""]})
	already = bool(frappe.db.get_single_value("Work Management Settings", "tax_bu_enabled"))
	if not should_enable(in_use, already):
		return

	frappe.db.set_single_value("Work Management Settings", "tax_bu_enabled", 1)
	frappe.db.commit()
	print(
		f"Work Management: {in_use} farm(s) already carry a business unit, so the level "
		"above the farm has been switched on and its field stays on the form"
	)
