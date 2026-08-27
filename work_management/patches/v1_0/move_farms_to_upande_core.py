"""Hand the farms over to Upande Core, and take our own doctype out.

Farms are records of "Farm", which belongs to Upande Core. This app kept its own
`Work Management Farm` alongside it, and on the one site carrying both they had
drifted: Core had SIMO, Greenville and cheptiret; this app had Kabarak. Thirteen
names were common, and the site's own data -- 3,241 Employees, 528 Warehouses --
was already pointing at Core's list while this app's field definitions still
claimed the other one.

Nothing here rewrites a farm value. The ten Link fields hold farm *names*, the
names match, and the app's JSON already ships the new `options`; what this patch
does is carry across what Core does not track, clear the references Core cannot
resolve, and delete the doctype.

Two rules about touching `Farm`, both of which this patch obeys by never writing
to it at all:

  - every row on the live site is missing `farm_type`, which Core marks reqd, so
    a saved Farm document would be rejected by Core's own validation
  - it is another app's doctype, and this app adds nothing to it

So a farm Core has not got is not created here. It is cleared from whatever
referenced it and named in the log, because a farm nobody can resolve is a
dangling link either way -- and inventing one would mean guessing a company, a
farm type and an abbreviation on Core's behalf.
"""

import frappe

from work_management import install
from work_management.patches.v1_0.backfill_farms_in_use import SOURCES

OLD = "Work Management Farm"


def rows_to_carry(farms, already=None):
	"""Settings rows for the farms whose project or area is worth keeping.

	`farms` is [{name, project, area_ha}]. A farm with neither is skipped: on
	kaitet.local that is every one of the fourteen, and fourteen rows carrying
	two empty columns would make the Settings table look configured when nothing
	has been. A farm already on the table is left as it is -- what somebody
	typed there beats what this app's doctype happened to hold.
	"""
	already = already or set()
	rows = []
	for farm in farms:
		name = (farm.get("name") or "").strip()
		if not name or name in already:
			continue
		project = farm.get("project") or None
		area = frappe.utils.flt(farm.get("area_ha"))
		if not project and not area:
			continue
		rows.append({"farm": name, "project": project, "area_ha": area})
	return rows


def orphans(in_use, core_farms):
	"""Farm names something still points at that Upande Core has not got.

	Sorted, so the log reads the same on every run and a second run can be
	compared with the first.
	"""
	return sorted(name for name in in_use if name not in core_farms)


def _farms_in_use():
	"""{farm name: [what holds it]} across every field that carries one."""
	held = {}
	for doctype, fieldname in SOURCES:
		if not frappe.db.exists("DocType", doctype):
			continue
		if not frappe.get_meta(doctype).get_field(fieldname):
			continue
		rows = frappe.db.sql(
			f"select name, `{fieldname}` from `tab{doctype}` "
			f"where ifnull(`{fieldname}`, '') != ''",
			as_dict=True,
		)
		for row in rows:
			value = (row.get(fieldname) or "").strip()
			if value:
				held.setdefault(value, []).append((doctype, row["name"]))
	return held


def _clear(doctype, name, fieldname):
	"""Blank one reference without running document validation.

	set_value rather than a saved document: several of these doctypes are
	submitted, and a submitted Planner will not accept a save at all. The farm
	it named does not exist, so there is nothing for validation to protect.
	"""
	frappe.db.set_value(doctype, name, fieldname, None, update_modified=False)


def execute():
	if not frappe.db.exists("DocType", OLD):
		return

	settings = frappe.get_doc("Work Management Settings")
	already = {row.farm for row in (settings.get("farms") or []) if row.farm}
	old_farms = frappe.get_all(OLD, fields=["name", "project", "area_ha"], order_by="creation asc")

	carried = rows_to_carry(old_farms, already)
	for row in carried:
		settings.append("farms", row)
	if carried:
		settings.save(ignore_permissions=True)
		print(
			f"Work Management: carried {len(carried)} farm(s) into Settings -> "
			+ ", ".join(row["farm"] for row in carried)
		)

	held = _farms_in_use()
	core_farms = set(frappe.get_all("Farm", pluck="name"))
	fieldname_of = dict(SOURCES)
	for name in orphans(set(held), core_farms):
		where = held[name]
		for doctype, docname in where:
			_clear(doctype, docname, fieldname_of[doctype])
		print(
			f"Work Management: no Farm named {name!r} in Upande Core -- cleared "
			+ ", ".join(f'{doctype} "{docname}"' for doctype, docname in where)
		)

	install.drop_stale_link_options()

	for kind, filters in (
		("Property Setter", {"doc_type": OLD}),
		("Custom Field", {"dt": OLD}),
	):
		for leftover in frappe.get_all(kind, filters=filters, pluck="name"):
			frappe.delete_doc(kind, leftover, force=True, ignore_permissions=True)

	frappe.delete_doc("DocType", OLD, force=True, ignore_permissions=True)
	frappe.db.commit()
	print(f"Work Management: {OLD} retired; farms are Upande Core's records now")
