"""Install hooks.

Two jobs:

1. before_install — "adopt" the doctypes if they already exist on the site as
   *custom* doctypes (the situation on kaitet-group.upande.com, where the whole
   system was built in the UI). Flipping custom=0 and pointing the module at
   this app lets `bench migrate` sync the JSON definitions over the existing
   tables without dropping any data.

2. after_install — create the custom fields this app needs on core doctypes
   (Employee, Warehouse, Task), then seed the approval stage catalogue and
   generate the workflows from it. Link fields degrade gracefully to Data
   fields when the link target doctype is not installed on the site.
"""

import frappe

WM_DOCTYPES = [
	"Work Management Planner",
	"Work Management Assigner",
	"Work Management Actuals",
	"Work Management Payment",
	"Work Planner Block",
	"Work Assignment Employee",
	"Work Actuals Employee",
	"Work Payment Line",
	"Work Management Task",
]

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
	for name in WM_DOCTYPES:
		if not frappe.db.exists("DocType", name):
			continue
		is_custom = frappe.db.get_value("DocType", name, "custom")
		if is_custom:
			frappe.db.set_value(
				"DocType",
				name,
				{"custom": 0, "module": "Work Management"},
				update_modified=False,
			)
			print(f"Adopted existing custom DocType: {name}")
	frappe.db.commit()


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


def upgrade_business_unit_link():
	"""Make Work Management Farm.business_unit a Link where the target exists.

	`Business Unit` belongs to upande_core. The field ships as Data so this app
	installs on a site without it; where the doctype is present, a property
	setter turns it into a proper link so the existing records are reachable.
	This mirrors the Link-to-Data degradation create_core_custom_fields() does
	for the fields on Employee and Warehouse.
	"""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	if not frappe.db.exists("DocType", "Business Unit"):
		return False
	current = frappe.db.get_value(
		"Property Setter",
		{"doc_type": "Work Management Farm", "field_name": "business_unit",
		 "property": "fieldtype"},
		"value",
	)
	if current == "Link":
		return True
	make_property_setter("Work Management Farm", "business_unit", "fieldtype", "Link", "Data",
		validate_fields_for_doctype=False)
	make_property_setter("Work Management Farm", "business_unit", "options", "Business Unit", "Text",
		validate_fields_for_doctype=False)
	frappe.clear_cache(doctype="Work Management Farm")
	return True


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
