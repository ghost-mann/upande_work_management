"""Give every farm value in use a record, so no link dangles.

Making Employee.custom_farm and Warehouse.custom_farm links to Work Management
Farm assumed the farms in Settings were the only ones in use. They are not: the
site this app came from carries fourteen distinct values and Settings names
four, so ten links point at records that do not exist.

The other ten appear only on Employee and Warehouse, never on a plan, an
assignment or a payment -- they are the wider organisation. They are created
disabled: the link resolves, while get_config(), the pickers and the
stranded-farm guard still see only the farms this module plans work against.
That last one matters, because fourteen active farms with approvers configured
for four would refuse to save Settings.
"""

import frappe

# (doctype, fieldname) pairs that carry a farm name.
SOURCES = (
	("Employee", "custom_farm"),
	("Warehouse", "custom_farm"),
	("Work Management Planner", "farm"),
	("Work Management Assigner", "farm"),
	("Work Management Actuals", "farm"),
	("Work Management Payment", "farm"),
	("Work Management Master Plan", "farm"),
)


def should_disable(farm, configured):
	"""Farms outside Settings are created disabled -- unless nothing is configured.

	On a site that has configured nothing, disabling every discovered farm would
	leave the module with none at all, which is worse than offering them.
	"""
	if not configured:
		return False
	return farm not in configured


def farms_in_use():
	"""Every distinct, non-empty farm value across the doctypes that carry one."""
	found = set()
	for doctype, fieldname in SOURCES:
		if not frappe.db.exists("DocType", doctype):
			continue
		if not frappe.get_meta(doctype).get_field(fieldname):
			continue
		table = f"tab{doctype}"
		rows = frappe.db.sql(
			f"select distinct `{fieldname}` from `{table}` where ifnull(`{fieldname}`, '') != ''"
		)
		found.update((r[0] or "").strip() for r in rows if (r[0] or "").strip())
	return found


def execute():
	if not frappe.db.exists("DocType", "Work Management Farm"):
		return

	settings = frappe.get_doc("Work Management Settings")
	configured = {r.farm for r in (settings.get("farms") or []) if r.farm}
	configured |= set(frappe.get_all("Work Management Farm", filters={"disabled": 0}, pluck="name"))

	created = 0
	for farm in sorted(farms_in_use()):
		if frappe.db.exists("Work Management Farm", farm):
			continue
		frappe.get_doc({
			"doctype": "Work Management Farm",
			"farm_name": farm,
			"disabled": 1 if should_disable(farm, configured) else 0,
		}).insert(ignore_permissions=True)
		created += 1

	frappe.db.commit()
	print(f"Work Management: created {created} farm record(s) for values already in use")
