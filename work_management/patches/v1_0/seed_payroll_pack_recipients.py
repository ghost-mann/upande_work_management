"""Seed the payroll approval pack recipients, on Kaitet's site only.

The pack carries every worker's pay, so its recipient lists are sensitive. They
are Kaitet's people; every other client's site must come out of this patch with
the fields blank, so it does nothing unless Company "Kaitet Ltd." exists.

Two rules from earlier patches apply:

* A list somebody already set is never overwritten -- only blank fields are filled.
* `payroll_pack_enabled` is always set to 1. A new Check added to a saved Single
  reads 0 whatever its default says (see switch_on_the_new_discrepancy_checks).
"""

SENDER = "notifications@karenroses.com"
TO = "\n".join(
	(
		"bob@karenroses.com",
		"hro@endebesscoffee.com",
		"peter@endebesscoffee.com",
		"pkanda@endebesscoffee.com",
		"koskey@lokitelaorchards.com",
		"ibett@karenroses.com",
	)
)
BCC = "\n".join(("austin@upande.com", "jeniffer@upande.com", "teresia@upande.com"))

FIELDS = {"payroll_pack_sender": SENDER, "payroll_pack_to": TO, "payroll_pack_bcc": BCC}


def seed_values(company_exists, current):
	"""Return the values to write, or None when this is not Kaitet's site."""
	if not company_exists:
		return None
	values = {"payroll_pack_enabled": 1}
	for field, value in FIELDS.items():
		if not (current.get(field) or "").strip():
			values[field] = value
	return values


def execute():
	import frappe

	if not frappe.db.exists("DocType", "Work Management Settings"):
		return
	current = {}
	for field in FIELDS:
		try:
			current[field] = frappe.db.get_single_value("Work Management Settings", field)
		except Exception:
			current[field] = None
	values = seed_values(bool(frappe.db.exists("Company", "Kaitet Ltd.")), current)
	if values is None:
		print("no Kaitet company here; payroll pack recipients left blank")
		return
	for field, value in values.items():
		frappe.db.set_single_value("Work Management Settings", field, value)
	frappe.db.commit()
	frappe.clear_cache(doctype="Work Management Settings")
	print("seeded: %s" % ", ".join(values))
