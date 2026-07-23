"""Install hooks.

Two jobs:

1. before_install — "adopt" the doctypes if they already exist on the site as
   *custom* doctypes (the situation on kaitet-group.upande.com, where the whole
   system was built in the UI). Flipping custom=0 and pointing the module at
   this app lets `bench migrate` sync the JSON definitions over the existing
   tables without dropping any data.

2. after_install — create the custom fields this app needs on core doctypes
   (Employee, Warehouse, Task). Link fields degrade gracefully to Data fields
   when the link target doctype (e.g. "Farm" from the upande_kaitet app) is
   not installed on the site.
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
	("Employee", "custom_farm", "Unit/Division", "Link", "Farm", "department", {}),
	("Employee", "custom_business_unit", "Business Unit", "Link", "Business Unit", "custom_farm", {}),
	(
		"Employee",
		"custom_group_name",
		"Location",
		"Select",
		"Ravine\nKaren\nLokitela\nEndebess\nSaboti",
		"custom_business_unit",
		{},
	),
	("Warehouse", "custom_farm", "Farm", "Link", "Farm", "warehouse_name", {}),
	("Warehouse", "custom_area_ha", "Area (HA)", "Float", None, "custom_farm", {}),
	("Warehouse", "custom_cost_center", "Cost Center", "Link", "Cost Center", "custom_area_ha", {}),
	("Task", "custom_uom", "UoM", "Link", "UOM", "subject", {}),
	("Task", "custom_daily_target", "Daily Target", "Float", None, "custom_uom", {}),
	("Task", "custom_rate", "Rate", "Float", None, "custom_daily_target", {}),
]


def before_install():
	adopt_existing_custom_doctypes()


def after_install():
	create_core_custom_fields()


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
