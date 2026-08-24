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
# Deliberately absent: Work Management Settings.att_block_absent, "Check
# attendance (block employees marked Absent)" -- that "block" is a verb.
FIELD_LABELS = (
	("WM Farm", "farm", "{top_singular}"),
	("Work Management Actuals", "farm", "{top_singular}"),
	("Work Management Actuals", "block_section", "{unit_singular}"),
	("Work Management Assigner", "farm", "{top_singular}"),
	("Work Management Assigner", "block_section", "{unit_singular}"),
	("Work Management Farm", "farm_name", "{top_singular}"),
	("Work Management Master Plan", "farm", "{top_singular}"),
	("Work Management Payment", "farm", "{top_singular}"),
	("Work Management Planner", "farm", "{top_singular}"),
	("Work Management Planner", "block_section", "{unit_singular}"),
	("Work Management Planner", "extra_blocks", "Additional {unit_plural}"),
	("Work Management Settings", "block_exclude", "{unit_singular} Exclude Keywords"),
	("Work Management Settings", "farms", "{top_plural}"),
	("Work Management Settings", "disc_multi_farm", "Two {top_plural}, one day"),
	("Work Management Settings", "rate_recalc_farm", "{top_singular} Scope"),
	("Work Management Stage Approver", "scope", "{top_singular}"),
	("Work Payment Line", "farm", "{top_singular}"),
	("Work Payment Line", "block", "{unit_singular}"),
	("Work Planner Block", "block", "{unit_singular}"),
	("Work Rate Recalc Run", "farm", "{top_singular} Scope"),
)


def apply_labels(settings=None):
	"""Write a Property Setter for each level-naming label. Idempotent.

	Property Setters rather than edits to the shipped JSON, so the app's files
	stay the same on every site and clearing the template puts the original
	labels back.
	"""
	import frappe
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	if settings is None:
		settings = frappe.get_cached_doc("Work Management Settings")
	names = resolve(settings)

	written = 0
	for doctype, fieldname, template in FIELD_LABELS:
		if not frappe.db.exists("DocType", doctype):
			continue
		label = label_for(template, names)
		current = frappe.db.get_value(
			"Property Setter",
			{"doc_type": doctype, "field_name": fieldname, "property": "label"},
			"value",
		)
		if current == label:
			continue
		make_property_setter(doctype, fieldname, "label", label, "Data",
			validate_fields_for_doctype=False)
		written += 1
	if written:
		frappe.clear_cache()
	return written


def clear_labels():
	"""Remove the labels this module wrote, restoring the shipped wording."""
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
