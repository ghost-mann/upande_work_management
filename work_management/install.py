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
	("Employee", "custom_farm", "Unit/Division", "Link", "Work Management Farm", "department", {}),
	("Employee", "custom_business_unit", "Business Unit", "Link", "Business Unit", "custom_farm", {}),
	# Options are left empty on purpose: each project fills in its own
	# locations. A Select with someone else's sites in it is worse than a blank.
	("Employee", "custom_group_name", "Location", "Select", "", "custom_business_unit", {}),
	("Warehouse", "custom_farm", "Farm", "Link", "Work Management Farm", "warehouse_name", {}),
	("Warehouse", "custom_area_ha", "Area (HA)", "Float", None, "custom_farm", {}),
	("Warehouse", "custom_cost_center", "Cost Center", "Link", "Cost Center", "custom_area_ha", {}),
	("Task", "custom_uom", "UoM", "Link", "UOM", "subject", {}),
	("Task", "custom_daily_target", "Daily Target", "Float", None, "custom_uom", {}),
	("Task", "custom_rate", "Rate", "Float", None, "custom_daily_target", {"precision": "4"}),
]


def before_install():
	adopt_existing_custom_doctypes()


def after_install():
	create_core_custom_fields()
	upgrade_business_unit_link()
	seed_approvals()
	sync_desk_surfaces()


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


def plan_business_unit_field(doctype_present, current_fieldtype, current_options):
	"""What to do to Work Management Farm.business_unit, or "noop".

	Pure, so both directions are testable without a site. Gated on both
	properties rather than just `fieldtype`: a migrate can be interrupted
	between the two property-setter writes an upgrade makes (killed, OOM,
	timeout), leaving `fieldtype=Link, options=None` on the site forever if
	only `fieldtype` were checked -- every later run would see "Link" and
	short-circuit, never writing the missing `options`. Checking both lets a
	half-finished upgrade repair itself on the next run.

	Bidirectional because the reverse can happen too: if upande_core is later
	uninstalled, a field left as a Link to a doctype that no longer exists
	breaks desk meta lookups (title fields in list views and reports), so an
	absent doctype always wins and puts the field back to Data.
	"""
	if not doctype_present:
		linked = current_fieldtype == "Link" or current_options == "Business Unit"
		return "downgrade" if linked else "noop"
	if current_fieldtype == "Link" and current_options == "Business Unit":
		return "noop"
	return "upgrade"


def upgrade_business_unit_link():
	"""Make Work Management Farm.business_unit a Link where the target exists.

	`Business Unit` belongs to upande_core. The field ships as Data so this app
	installs on a site without it; where the doctype is present, a property
	setter turns it into a proper link so the existing records are reachable.
	This mirrors the Link-to-Data degradation create_core_custom_fields() does
	for the fields on Employee and Warehouse. Runs at every after_migrate (not
	just after_install), so it also repairs an interrupted upgrade and reverts
	the field if upande_core is later removed from the site.
	"""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	doctype_present = bool(frappe.db.exists("DocType", "Business Unit"))
	filters = {"doc_type": "Work Management Farm", "field_name": "business_unit"}
	current_fieldtype = frappe.db.get_value(
		"Property Setter", {**filters, "property": "fieldtype"}, "value"
	)
	current_options = frappe.db.get_value(
		"Property Setter", {**filters, "property": "options"}, "value"
	)

	plan = plan_business_unit_field(doctype_present, current_fieldtype, current_options)
	if plan == "upgrade":
		make_property_setter("Work Management Farm", "business_unit", "fieldtype", "Link", "Data",
			validate_fields_for_doctype=False)
		make_property_setter("Work Management Farm", "business_unit", "options", "Business Unit", "Text",
			validate_fields_for_doctype=False)
		frappe.clear_cache(doctype="Work Management Farm")
	elif plan == "downgrade":
		for prop in ("fieldtype", "options"):
			name = frappe.db.get_value("Property Setter", {**filters, "property": prop}, "name")
			if name:
				frappe.delete_doc("Property Setter", name, force=True, ignore_permissions=True)
		frappe.clear_cache(doctype="Work Management Farm")
	return doctype_present


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
