"""Install hooks.

Two jobs:

1. before_install, and again on every after_migrate — "adopt" the doctypes if
   they already exist on the site as *custom* doctypes (the situation on
   kaitet-group.upande.com, where the whole system was built in the UI: nine of
   them sit under erpnext's Projects module with custom=1). Flipping custom=0
   and pointing the module at this app lets the JSON definitions sync over the
   existing tables without dropping any data.

   A custom doctype lives only in the database -- no app file, nothing that
   `export-fixtures` produces -- so it deploys nowhere, and the app's own copy
   never reaches a site that already has one. Worse, the mismatch is silent:
   `import_file.py` skips a DocType whose content hash matches its last
   import, and flipping custom in the database does not change the file, so
   `bench migrate` exits 0 having done nothing. Hence the force-import here,
   the same move desk.py makes for workspaces.

2. after_install — create the custom fields this app needs on core doctypes
   (Employee, Warehouse, Task), then seed the approval stage catalogue and
   generate the workflows from it. Link fields degrade gracefully to Data
   fields when the link target doctype is not installed on the site.
"""

import glob
import json
import os

import frappe

MODULE = "Work Management"
HERE = os.path.dirname(os.path.abspath(__file__))
DOCTYPE_DIR = os.path.join(HERE, "work_management", "doctype")


def scrub(name):
	"""A doctype's folder name, the way Frappe derives it."""
	return name.replace(" ", "_").replace("-", "_").lower()


def doctype_json(name):
	"""Where this app keeps the shipped definition of one doctype."""
	slug = scrub(name)
	return os.path.join(DOCTYPE_DIR, slug, f"{slug}.json")


def shipped_doctypes():
	"""Every DocType this app ships, read from its own files.

	This was a hand-written list of nine, frozen when the app had nine. It
	ships twenty-one, and the twelve added since -- Farm, Settings, Section and
	the rest -- had no adoption path at all: a site owning one of them as a
	custom doctype kept it, silently, for good. Reading the folder means the
	next doctype added cannot be forgotten the same way.
	"""
	names = []
	for path in glob.glob(os.path.join(DOCTYPE_DIR, "*", "*.json")):
		with open(path) as handle:
			doc = json.load(handle)
		if doc.get("doctype") == "DocType":
			names.append(doc["name"])
	return sorted(names)


def shipped_fieldnames(name):
	"""The fieldnames the app's own definition of a doctype carries."""
	path = doctype_json(name)
	if not os.path.exists(path):
		return []
	with open(path) as handle:
		doc = json.load(handle)
	return [f["fieldname"] for f in doc.get("fields", []) if f.get("fieldname")]


def extra_fieldnames(existing, shipped):
	"""Fieldnames the site's own copy carries that this app does not define.

	A custom doctype keeps every field on the DocType record itself rather than
	as separate Custom Field records, so force-importing the app's definition
	takes any of these off the form. The column and its data stay in the table
	and a Custom Field puts it back, but nobody can act on that without being
	told, so adoption prints them.
	"""
	return sorted(set(existing) - set(shipped))

# (dt, fieldname, label, fieldtype, options, insert_after, extras)
CORE_CUSTOM_FIELDS = [
	# Declared exactly as upande_kaitet declares it -- same label, same target,
	# same position -- because both apps ship this field and whichever migrates
	# last writes it. Disagreeing was the bug: ours said "Work Management Farm"
	# after `department`, theirs says "Farm" after `grade`, and once this app's
	# definitions became authoritative the next migrate would have moved the box
	# and repointed 3,241 employees at a farm list missing three names in use.
	("Employee", "custom_farm", "Unit/Division", "Link", "Farm", "grade", {}),
	("Employee", "custom_business_unit", "Business Unit", "Link", "Business Unit", "custom_farm", {}),
	# Options are left empty on purpose: each project fills in its own
	# locations. A Select with someone else's sites in it is worse than a blank.
	("Employee", "custom_group_name", "Location", "Select", "", "custom_business_unit", {}),
	# Warehouse.custom_farm is deliberately absent: it is Upande Core's field.
	# Core ships it, exports it as the fixture `Warehouse-custom_farm`, hooks
	# warehouse_hooks.py to it, orders the Warehouse form around it in its own
	# install, and Row, Section and Bed all fetch_from it. We only read it --
	# which is also why it is still a safe anchor for the field below.
	("Warehouse", "custom_area_ha", "Area (HA)", "Float", None, "custom_farm", {}),
	("Warehouse", "custom_cost_center", "Cost Center", "Link", "Cost Center", "custom_area_ha", {}),
	("Task", "custom_uom", "UoM", "Link", "UOM", "subject", {}),
	("Task", "custom_daily_target", "Daily Target", "Float", None, "custom_uom", {}),
	("Task", "custom_rate", "Rate", "Float", None, "custom_daily_target", {"precision": "4"}),
	# What the weekly payroll feed writes: this pay week's total for one worker,
	# actuals plus the off-day bonus. A colleague owns the Salary Structure whose
	# Basic component fetches it, which is why the FIELDNAME is fixed -- the feed
	# must write exactly this one, and that wiring is deliberately out of scope
	# here. read_only because nothing typed into it survives the next feed.
	("Employee", "custom_basic_pay", "Basic Pay", "Currency", None, "salary_mode",
		{"read_only": 1, "description": "Weekly total written by Work Management: "
			"confirmed unpaid actuals for the fed pay week, plus the weekly off-day "
			"bonus where it was earned."}),
	# Which week the figure above is for. Without it a second feed of the same
	# week would overwrite the first with the same number and no way to tell,
	# and a feed of the WRONG week would be invisible. The existing payment flow
	# stamps payment_ref / paid for the same reason.
	("Employee", "custom_basic_pay_week", "Basic Pay — week fed", "Data", None,
		"custom_basic_pay", {"read_only": 1, "description": "The pay week the "
			"figure above covers, as from → to. Re-feeding the same week is a no-op."}),
]


def before_install():
	# stashed for after_install: once adoption has run there is no way left to
	# tell a migrated site from a fresh one, and the two need different patching
	frappe.flags.wm_adopted = adopt_existing_custom_doctypes()
	release_module_def()


def should_release_module_def(module_def_exists, in_install):
	"""Whether to hand the app's Module Def back to Frappe's installer.

	Only in the install path, and only if something already created it. At
	after_migrate the module is the live one and nothing is about to recreate
	it, so deleting it there would strand every DocType pointing at it.
	"""
	return bool(module_def_exists and in_install)


def release_module_def():
	"""Delete the Module Def adoption created, so the installer can make its own.

	frappe.installer.add_module_defs() inserts this app's module with
	ignore_if_duplicate=False, so a Module Def already sitting there aborts
	`bench install-app` outright and half-installed:

	    DuplicateEntryError: ('Module Def', 'Work Management')

	Adoption is what puts it there. Force-importing a doctype whose module the
	site has not got makes Frappe create the module on the spot, and adoption
	runs at before_install -- so this app creates the module, and then the
	installer refuses to create it again. A fresh site adopts nothing and so
	never creates it, which is why this only ever bit a site that already had
	these doctypes as custom ones: exactly the site being migrated onto.

	Deleting it costs nothing. The installer recreates it under the same name
	moments later, and that name is the primary key every DocType.module points
	at -- so the link is restored rather than repaired. force=True because those
	links exist while it goes.
	"""
	if not should_release_module_def(frappe.db.exists("Module Def", MODULE), frappe.flags.in_install):
		return False
	frappe.delete_doc("Module Def", MODULE, force=True, ignore_permissions=True,
	                  ignore_missing=True)
	frappe.db.commit()
	print(f"Handed the {MODULE} Module Def back to the installer to create")
	return True


def shadowed_custom_fields(custom_fieldnames, shipped):
	"""Custom Fields whose fieldname this app now ships as its own DocField.

	The Custom Field wins in the meta, so while one of these sits there the
	app's definition of that field never takes effect -- and nothing says so.
	A field the app does not ship is somebody's own and is left alone.
	"""
	return sorted(set(custom_fieldnames) & set(shipped))


def drop_shadowing_custom_fields():
	"""Take back the fields this app defines, on every doctype it ships.

	A site built in the UI carries Custom Fields for fields this app has since
	shipped as DocFields of its own. Both describe the same column, but the
	Custom Field is applied on top, so the app's version of that field is frozen
	at whatever the site drew -- silently, and for good.

	That is not theoretical. The app added "Completed" to the plan close-state
	options; after migrate the DocField carried it and the meta still refused
	the value, because a Custom Field of the same fieldname sat on top with the
	old three. 591 of the live site's plans hold that value.

	This is its own step rather than part of adoption, because adoption skips a
	doctype it already owns: a site adopted months ago would never revisit
	these. Deleting them costs no data -- Frappe's Custom Field.on_trash does
	not drop columns, and the DocField keeps the column regardless.
	"""
	dropped = []
	for name in shipped_doctypes():
		if not frappe.db.exists("DocType", name):
			continue
		shipped = shipped_fieldnames(name)
		if not shipped:
			continue
		existing = frappe.get_all("Custom Field", filters={"dt": name},
		                         fields=["name", "fieldname"])
		by_fieldname = {row.fieldname: row.name for row in existing}
		for fieldname in shadowed_custom_fields(by_fieldname, shipped):
			frappe.delete_doc("Custom Field", by_fieldname[fieldname],
			                  force=True, ignore_permissions=True)
			dropped.append(f"{name}.{fieldname}")
	if dropped:
		frappe.db.commit()
		frappe.clear_cache()
		print(
			f"Took back {len(dropped)} field(s) a Custom Field was shadowing, so this "
			f"app's own definition applies: {', '.join(dropped)}"
		)
	return dropped


def after_install():
	create_core_custom_fields()
	drop_stale_link_options()
	seed_approvals()
	sync_desk_surfaces()
	drop_shadowing_custom_fields()
	run_data_patches(frappe.flags.get("wm_adopted") or [])


def data_patches():
	"""Every patch this app ships, read from patches.txt.

	Read rather than listed, so a patch added to the file cannot be left out of
	the migration by someone forgetting a second list.
	"""
	path = os.path.join(HERE, "patches.txt")
	if not os.path.exists(path):
		return []
	with open(path) as handle:
		return [
			line.strip() for line in handle
			if line.strip() and not line.startswith(("#", "["))
		]


def should_run_data_patches(adopted):
	"""Whether this install has to run its own patches by hand.

	frappe.installer.install_app() calls set_all_patches_as_completed(), so
	installing records every patch as done without running one. On a genuinely
	fresh site that is right: there is no legacy data for a patch to fix.

	On a site being migrated onto it is exactly backwards. The site arrives full
	of the data these patches were written to reconcile, and marking them
	applied skips the reconciliation for good -- the next migrate sees them in
	the Patch Log and moves on. Rehearsed on a 16.27 restore of the live site
	that left no Work Management Farm records at all, for 441 planners and 402
	assigners whose farm link had nothing to point at.

	Adopting a doctype is the signal: it means the site already had this app's
	data under its own custom definition.
	"""
	return bool(adopted)


def run_data_patches(adopted):
	"""Run the shipped patches on a site that brought its own data.

	Each is written to be safe to run twice -- backfill skips a farm that
	already has a record, seeding skips a block some section already claims --
	so running them here costs nothing on a site where they would have run
	anyway, and a patch that raises is reported rather than left to abort the
	install.
	"""
	if not should_run_data_patches(adopted):
		return []

	import importlib

	ran = []
	for patch in data_patches():
		try:
			importlib.import_module(patch).execute()
			frappe.db.commit()
			ran.append(patch)
		except Exception as exc:
			frappe.db.rollback()
			print(f"Could not run {patch} on this site: {exc}")
			frappe.log_error(title="Work Management: patch skipped on install")
	print(
		f"Ran {len(ran)} shipped patch(es) by hand: the installer had marked them "
		f"applied, but this site brought {len(adopted)} doctype(s) of its own data"
	)
	return ran


def adopt_existing_custom_doctypes():
	"""Take ownership of any doctype this app ships that the site owns as a
	custom one, and put the app's definition on it.

	Runs at before_install, where the sync that follows carries the definition,
	and again at every after_migrate, where that sync has already been and gone
	-- so here it force-imports, or the doctype would end up owned by this app
	and still shaped the way the site drew it.

	Returns the names it adopted.
	"""
	from frappe.modules.import_file import import_file_by_path

	adopted = []
	for name in shipped_doctypes():
		if not frappe.db.exists("DocType", name):
			continue
		if not frappe.db.get_value("DocType", name, "custom"):
			continue

		lost = extra_fieldnames(
			[f.fieldname for f in frappe.get_meta(name).fields], shipped_fieldnames(name)
		)
		frappe.db.set_value(
			"DocType", name, {"custom": 0, "module": MODULE}, update_modified=False
		)
		path = doctype_json(name)
		if os.path.exists(path):
			import_file_by_path(path, force=True)
		adopted.append(name)
		print(f"Adopted existing custom DocType: {name}")
		if lost:
			print(
				f"  {name} carried {len(lost)} field(s) this app does not define, now off "
				f"the form (the data is still in the table): {', '.join(lost)}"
			)
	if adopted:
		frappe.db.commit()
		frappe.clear_cache()
	return adopted


def create_core_custom_fields():
	from frappe.custom.doctype.custom_field.custom_field import create_custom_field

	for dt, fieldname, label, fieldtype, options, insert_after, extras in CORE_CUSTOM_FIELDS:
		if frappe.db.exists("Custom Field", f"{dt}-{fieldname}"):
			continue
		if not frappe.db.exists("DocType", dt):
			continue
		ftype, fopts = fieldtype, options
		if fieldtype == "Link" and options and not frappe.db.exists("DocType", options):
			# Link target app not installed on this site — keep the data, lose the link.
			ftype, fopts = "Data", None
		df = {
			"fieldname": fieldname,
			"label": label,
			"fieldtype": ftype,
			"options": fopts,
			"insert_after": insert_after if frappe.get_meta(dt).get_field(insert_after) else None,
		}
		df.update(extras)
		create_custom_field(dt, df)
		print(f"Created custom field {dt}.{fieldname} ({ftype})")
	frappe.db.commit()


def is_stale_link_option(is_link_field, value, target_exists):
	"""Does this `options` override leave a Link field pointing at nothing?

	Pulled out of drop_stale_link_options() so the decision can be tested without
	a site. An override on a Select is that
	field's option list and none of this app's business; an override naming a real
	doctype is a deliberate repoint. Only the third case -- a Link aimed at a
	doctype that does not exist -- is the leftover worth deleting.
	"""
	if not is_link_field:
		return False
	if not (value or "").strip():
		return True
	return not target_exists


def drop_stale_link_options():
	"""Delete `options` overrides that leave one of this app's Link fields dangling.

	A field that used to be a Select listing farm names by hand, and is now a Link
	to Work Management Farm, keeps whatever `options` Property Setter someone wrote
	against the old shape. On a Select that string is the option list. On a Link it
	is the target doctype, so the override silently repoints the field at a doctype
	that was never a doctype:

	    Work Management Planner-farm-options = "\nKentrout"

	Every save of a Work Management Planner then died with
	`DocType \nKentrout not found` -- a 404 that reached the person as nothing more
	than a failed Save button. Nothing in this app writes these; they are leftovers
	from before the farms became records, and migrating the field shape does not
	take them with it.

	Deliberately narrow -- this app's own doctypes, `options` only, Link fields
	only, and only where the target does not exist.
	"""
	dropped = []
	for doctype in shipped_doctypes():
		path = doctype_json(doctype)
		if not os.path.exists(path):
			continue
		with open(path) as handle:
			shipped = json.load(handle)
		links = {
			field["fieldname"]
			for field in shipped.get("fields", [])
			if field.get("fieldtype") == "Link" and field.get("fieldname")
		}
		here = []
		for setter in frappe.get_all(
			"Property Setter",
			filters={"doc_type": doctype, "property": "options"},
			fields=["name", "field_name", "value"],
		):
			target = (setter.value or "").strip()
			if not is_stale_link_option(
				setter.field_name in links, target, bool(frappe.db.exists("DocType", target))
			):
				continue
			frappe.delete_doc("Property Setter", setter.name, force=True, ignore_permissions=True)
			here.append(setter.name)
		if here:
			frappe.clear_cache(doctype=doctype)
			dropped.extend(here)
	return dropped


def drop_farmless_settings_rows():
	"""Delete Settings farm rows that name no farm, so Settings can be saved.

	`WM Farm.farm` has been reqd since this app's first commit, so no validated
	save can produce a row without one -- but kentrout.local carried one anyway,
	written out of band (no Version row, no Activity Log entry, zero area, no
	project). A row like that says nothing, and cannot: the project and area it
	could hold belong to a farm it does not name.

	What it does do is refuse every save of Work Management Settings, because
	_validate_mandatory() walks the children. That took out after_migrate ->
	seed_stages(), which saves Settings on every migrate, so one unattributable
	row made `bench migrate` unrunnable until somebody deleted it by hand.

	SQL rather than a document, for the same reason: loading Settings and saving
	it is exactly what the bad row prevents. Narrow -- this one child table, this
	one parent, and only rows whose farm is empty.
	"""
	if not frappe.db.table_exists("WM Farm"):
		return []
	rows = frappe.db.sql(
		"""
		SELECT name, project, area_ha FROM `tabWM Farm`
		WHERE parenttype = 'Work Management Settings' AND parentfield = 'farms'
		  AND IFNULL(farm, '') = ''
		""",
		as_dict=True,
	)
	if not rows:
		return []
	frappe.db.delete(
		"WM Farm", {"name": ("in", [row["name"] for row in rows])}
	)
	frappe.clear_cache(doctype="Work Management Settings")
	# Named on the way out. A row with a project or an area held something, even
	# if there was no farm to attach it to, and this print is the only record.
	for row in rows:
		held = ", ".join(
			f"{label} {value!r}"
			for label, value in (("project", row["project"]), ("area_ha", row["area_ha"]))
			if value
		)
		print(
			f"Work Management: dropped a Settings farm row naming no farm"
			+ (f" (it held {held})" if held else "")
		)
	return [row["name"] for row in rows]


def seed_approvals():
	"""Fill the approval stage catalogue and generate the workflows from it.

	A fresh install therefore arrives with the full chain wired to the module's
	default roles and nobody named. Naming people is the one thing an
	administrator has to do, and Settings says so.
	"""
	from work_management import approvals

	approvals.seed_stages()
	frappe.clear_cache(doctype="Work Management Settings")
	built = approvals.build_workflows()
	frappe.db.commit()
	for name in built:
		print(f"Generated workflow: {name}")


def sync_desk_surfaces():
	"""Repair the workspace if a same-named one already shadowed ours.

	Has to run after the app's files have been synced, not in before_install:
	the import is what gets skipped, so there is nothing to repair until it has
	had its chance.
	"""
	from work_management import desk

	desk.sync()
	frappe.db.commit()
