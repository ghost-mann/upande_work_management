"""What each level of the hierarchy is called, on this installation.

The module ships knowing the levels but not their names. A project that runs
estates and plots says so here once, and the desk labels and the five screens
follow. Nothing about a level's meaning is configurable -- only its name.
"""

from collections import namedtuple

Level = namedtuple("Level", "key singular plural optional")

# Ordered outermost first. `key` is the prefix of the Settings fields and of the
# keys resolve() returns.
LEVELS = (
	Level("bu", "Business Unit", "Business Units", True),
	Level("top", "Farm", "Farms", False),
	Level("unit", "Block", "Blocks", False),
	# Not a level in the chain: names the cost-centre grouping and its toggle.
	Level("section", "Section", "Sections", True),
)


def _pick(settings, fieldname, default):
	value = (settings.get(fieldname) or "").strip() if settings else ""
	return value or default


def resolve(settings):
	"""{name key: string} for this installation, falling back to the defaults.

	A blank name falls back rather than rendering an empty label, so clearing a
	field in Settings restores the shipped wording instead of breaking a form.
	"""
	names = {}
	for level in LEVELS:
		names[f"{level.key}_singular"] = _pick(settings, f"tax_{level.key}_singular", level.singular)
		names[f"{level.key}_plural"] = _pick(settings, f"tax_{level.key}_plural", level.plural)
	names["bu_enabled"] = bool(settings.get("tax_bu_enabled")) if settings else False
	return names


def label_for(template, names):
	"""Fill a label template. An unknown placeholder is left visible, not raised.

	Labels are cosmetic; a typo in one should look wrong, not stop a migrate.
	"""
	try:
		return template.format(**names)
	except (KeyError, IndexError):
		return template


# (doctype, fieldname, label template). Every field whose label names a level.
#
# Deliberately absent, and guarded by name in test_taxonomy.py so the omission
# has to stay deliberate:
#   - Work Management Settings.att_block_absent, "Check attendance (block
#     employees marked Absent)" -- that "block" is a verb.
#   - Work Management Settings.tax_* -- these fields are where the names are
#     typed. Renaming "Farm level (singular)" to "Estate level (singular)" the
#     moment someone types Estate into it hides the one label that explains
#     what the field does.
FIELD_LABELS = (
	("WM Farm", "farm", "{top_singular}"),
	("Work Management Actuals", "farm", "{top_singular}"),
	("Work Management Actuals", "block_section", "{unit_singular} / {section_singular}"),
	("Work Management Assigner", "farm", "{top_singular}"),
	("Work Management Assigner", "block_section", "{unit_singular} / {section_singular}"),
	("Work Management Master Plan", "farm", "{top_singular}"),
	("Work Management Payment", "farm", "{top_singular}"),
	("Work Management Planner", "farm", "{top_singular}"),
	("Work Management Planner", "sb_blocks", "{unit_plural} / {section_plural}"),
	("Work Management Planner", "block_section", "{unit_singular} / {section_singular}"),
	("Work Management Planner", "extra_blocks", "Additional {unit_plural} / {section_plural}"),
	("Work Management Section", "blocks", "{unit_plural}"),
	("Work Management Section", "farm", "{top_singular}"),
	("Work Management Section", "section_name", "{section_singular}"),
	("Work Management Section Block", "block", "{unit_singular}"),
	("Work Management Settings", "block_exclude", "{unit_singular} Exclude Keywords"),
	("Work Management Settings", "farms", "{top_plural} in use"),
	("Work Management Settings", "tab_farms", "{top_plural}"),
	("Work Management Settings", "farms_restrict", "Only work the {top_plural} listed below"),
	("Work Management Settings", "farms_respect_user_permissions",
		"Only show each person the {top_plural} they are permitted"),
	("Work Management Settings", "farms_section", "{top_plural}"),
	("Work Management Settings", "disc_multi_farm", "Two {top_plural}, one day"),
	("Work Management Settings", "rate_recalc_farm", "{top_singular} Scope"),
	("Work Management Stage Approver", "scope", "{top_singular}"),
	("Work Payment Line", "farm", "{top_singular}"),
	("Work Payment Line", "block", "{unit_singular} / {section_singular}"),
	("Work Planner Block", "block", "{unit_singular} / {section_singular}"),
	("Work Rate Recalc Run", "farm", "{top_singular} Scope"),
)


def shipped_labels():
	"""{doctype: {fieldname: label}} as the app's own JSON ships them.

	Read from the files rather than from frappe.get_meta, which returns the
	label a Property Setter has already overwritten -- comparing against that
	is what made every setter look necessary.
	"""
	import glob
	import json
	import os

	here = os.path.dirname(os.path.abspath(__file__))
	shipped = {}
	for path in glob.glob(os.path.join(here, "work_management", "doctype", "*", "*.json")):
		with open(path) as handle:
			doc = json.load(handle)
		if doc.get("doctype") != "DocType":
			continue
		shipped[doc["name"]] = {
			f["fieldname"]: f.get("label") for f in doc.get("fields", [])
		}
	return shipped


def plan_labels(names, shipped):
	"""{(doctype, fieldname): label or None} -- None meaning "leave the JSON".

	A rendered label equal to the shipped one needs no Property Setter at all.
	Writing one anyway left a site that renamed nothing carrying one record per
	catalogued field, each saying exactly what the JSON says, and left clearing
	a name with the old setter still standing instead of the original label.

	A field the shipped map does not carry is left out entirely rather than
	planned as None: a site mid-migrate has fields the catalogue names and the
	JSON has not reached yet, and "remove its setter" is not the same as
	"nothing to say about it".
	"""
	plan = {}
	for doctype, fieldname, template in FIELD_LABELS:
		if fieldname not in shipped.get(doctype, {}):
			continue
		label = label_for(template, names)
		plan[(doctype, fieldname)] = None if label == shipped[doctype][fieldname] else label
	return plan


def apply_labels(settings=None):
	"""Bring the level-naming labels into line with the template. Idempotent.

	Property Setters rather than edits to the shipped JSON, so the app's files
	stay the same on every site and clearing the template puts the original
	labels back -- which means removing the setter, not writing the original
	label into one. A site that renamed nothing therefore ends up carrying no
	setters at all.

	Returns (written, removed).
	"""
	import frappe
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	if settings is None:
		settings = frappe.get_cached_doc("Work Management Settings")
	plan = plan_labels(resolve(settings), shipped_labels())

	written = removed = 0
	for (doctype, fieldname), label in plan.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		filters = {"doc_type": doctype, "field_name": fieldname, "property": "label"}
		existing = frappe.db.get_value("Property Setter", filters, ["name", "value"], as_dict=True)
		if label is None:
			if not existing:
				continue
			frappe.delete_doc("Property Setter", existing.name, force=True, ignore_permissions=True)
			removed += 1
			continue
		if existing and existing.value == label:
			continue
		make_property_setter(doctype, fieldname, "label", label, "Data",
			validate_fields_for_doctype=False)
		written += 1
	if written or removed:
		frappe.clear_cache()
	return written, removed


def clear_labels():
	"""Remove what this module wrote, restoring the shipped wording."""
	import frappe

	removed = 0
	for doctype, fieldname, _template in FIELD_LABELS:
		for name in frappe.get_all(
			"Property Setter",
			filters={"doc_type": doctype, "field_name": fieldname, "property": "label"},
			pluck="name",
		):
			frappe.delete_doc("Property Setter", name, force=True, ignore_permissions=True)
			removed += 1
	if removed:
		frappe.clear_cache()
	return removed
