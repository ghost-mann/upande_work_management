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

SOURCES is every Link field the app ships pointing at Work Management Farm,
plus the two Custom Fields (Employee, Warehouse) that aren't in the app's own
doctype JSON. test_sections.py walks the shipped JSON and fails loudly, listing
every gap, if a future field is added there and forgotten here. Scanning a
superset costs nothing: farms_in_use() skips any doctype or field missing from
a given site, and execute() skips any farm that already has a record.
"""

import frappe

from work_management import migrating

# (doctype, fieldname) pairs that carry a farm name.
SOURCES = (
	("Employee", "custom_farm"),
	("Warehouse", "custom_farm"),
	("WM Farm", "farm"),
	("Work Management Actuals", "farm"),
	("Work Management Assigner", "farm"),
	("Work Management Master Plan", "farm"),
	("Work Management Payment", "farm"),
	("Work Management Planner", "farm"),
	("Work Management Section", "farm"),
	("Work Management Stage Approver", "scope"),
	("Work Payment Line", "farm"),
	("Work Rate Recalc Run", "farm"),
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


def create_missing(farms, configured, create):
	"""Create a record for every farm that has none, surviving one that will not.

	The insert is passed in rather than called here, so the loop can be tested
	without a site and so a farm the field will not accept -- a legacy value
	longer than the column, a name that trips the unique constraint, a farm
	whose company was deleted -- costs that one farm instead of the migrate.
	Nothing here creates the farms this app plans against; those come from
	Settings. Every record it creates is a link somebody else's data already
	points at, so skipping one leaves exactly the dangling link that was there
	before, which is a smaller problem than a site stuck half-upgraded.

	Returns (created, notes).
	"""
	return migrating.each_without_aborting(
		farms,
		lambda farm: create(farm, should_disable(farm, configured)),
		"create the farm record for",
	)


def _insert(farm, disabled):
	frappe.get_doc({
		"doctype": "Work Management Farm",
		"farm_name": farm,
		"disabled": 1 if disabled else 0,
	}).insert(ignore_permissions=True)


def execute():
	if not frappe.db.exists("DocType", "Work Management Farm"):
		return

	settings = frappe.get_doc("Work Management Settings")
	configured = {r.farm for r in (settings.get("farms") or []) if r.farm}
	configured |= set(frappe.get_all("Work Management Farm", filters={"disabled": 0}, pluck="name"))

	missing = [
		farm for farm in sorted(farms_in_use())
		if not frappe.db.exists("Work Management Farm", farm)
	]
	created, skipped = create_missing(missing, configured, _insert)

	frappe.db.commit()
	print(f"Work Management: created {created} farm record(s) for values already in use")
	if skipped:
		print(
			f"Work Management: {len(skipped)} farm(s) skipped and left dangling, "
			"named above and in the Error Log"
		)
