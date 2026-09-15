"""Make every approval-stage row's `kind` a value the doctype still offers.

A deploy to alturablooms.upande.com died here, in Migrate Site::

    work_management.patches.v1_0.move_farms_to_upande_core
      ...move_farms_to_upande_core.py, line 139, in execute
        settings.save(ignore_permissions=True)
    frappe.exceptions.ValidationError: Row #6: Kind cannot be "Gate".
      It should be one of "Submit", "Approval"

**Why it had never happened before.** `kind` used to offer a third value.
`Gate` meant "not a workflow transition at all, a screen-level check"; nothing
ever read it, `chain_for()` filtered Gates straight out, and the one Gate stage
shipped -- `planner_weekly_consultant`, a weekly consultant review on the
planner -- was inert. It was dropped from the catalogue and from the Select.
Rows already written kept the value, because `seed_stages()` carries every row
the catalogue does not know **verbatim, `kind` included** -- which is the whole
point of a configurable chain and is exactly right. The doctype simply stopped
agreeing with them, and it stopped agreeing on the deploy that shipped the
narrowed Select, not on the one that wrote the row.

**Why any save dies, not just that one.** `settings.save()` re-validates every
child row of the whole document, so a single legacy value in one grid takes down
any code that touches Settings at all. Three separate places do:

    move_farms_to_upande_core     the one that failed
    merge_farms_in_use_into_farms two patches later, same document, same wall
    approvals.after_migrate       seed_stages(), on EVERY migrate, always

So this runs before all three, and db-level -- `frappe.db.set_value` on the child
table, no document, no validation. There is nothing to validate against: the
value is wrong precisely because the schema that would judge it has moved on.

**Gate becomes Approval, switched off.** Approval is the only sane landing
place; `Submit` is the step that starts a chain and there is exactly one per
document type. But a Gate row was INERT -- filtered out of the chain by kind --
and an enabled Approval row is a live step in a real workflow. Turning one into
the other during a hotfix deploy would quietly add an approval to somebody's
pipeline. So converted rows are disabled, which is what "inert" means once the
kind no longer says it. `planner_weekly_consultant` is deleted a few patches
later by `drop_dead_consultant_controls` regardless; anything else a site has
added survives, visible in the Settings grid, switched off, for a human to
decide about.

**The audit.** Any Select or Link value in any of Settings' child grids can fail
the same save the same way, and `Gate` is only the one we have hit. Every grid is
scanned read-only and anything that would fail is printed into the migrate log.
Nothing else is changed: one proven failure, one fix.
"""

import frappe

#: The grid that failed, and the column in it.
TABLE = "Work Management Approval Stage"
FIELD = "kind"

#: What the doctype offers now.
VALID = ("Submit", "Approval")

#: Where anything else lands. Not `Submit`: that is the step that moves a draft
#: into the chain, there is one per document type, and a second would be a
#: second beginning.
FALLBACK = "Approval"

PARENT = "Work Management Settings"


def replacement(kind):
	"""The value to write for `kind`, or None to leave the row alone. Pure."""
	if kind in VALID:
		return None
	return FALLBACK


def failing_values(rows, options):
	"""Which of `rows` hold a Select value the doctype no longer offers. Pure.

	`rows` is [{"name":, "<field>":}], `options` the list the Select offers. An
	empty value is not a failure -- Frappe only checks a Select that has one.
	"""
	allowed = set(options)
	return [row for row in rows
		if (row.get(FIELD) or "") and row.get(FIELD) not in allowed]


def _select_options(doctype, fieldname):
	"""What the Select offers on THIS site, Property Setters included."""
	field = frappe.get_meta(doctype).get_field(fieldname)
	if not field or not field.options:
		return []
	return [line.strip() for line in field.options.split("\n")]


def audit():
	"""Read-only: every child value of Settings that would fail a full save.

	Printed rather than fixed. The migrate log is where whoever runs the deploy
	is already looking, and a second legacy value found here is a second patch,
	not a bigger one.
	"""
	meta = frappe.get_meta(PARENT)
	found = 0
	for table_field in meta.get_table_fields():
		child = table_field.options
		if not child or not frappe.db.table_exists(child):
			continue
		child_meta = frappe.get_meta(child)
		checked = [df for df in child_meta.fields if df.fieldtype in ("Select", "Link")]
		if not checked:
			continue
		names = [df.fieldname for df in checked]
		rows = frappe.db.get_all(child, filters={"parenttype": PARENT},
			fields=["name", "idx"] + names)
		for df in checked:
			if df.fieldtype == "Select":
				allowed = set(_select_options(child, df.fieldname))
				bad = [r for r in rows if (r.get(df.fieldname) or "")
					and r.get(df.fieldname) not in allowed]
				for row in bad:
					found += 1
					print("Work Management: AUDIT %s row #%s %s = %r, not one of %s"
						% (child, row.idx, df.fieldname, row.get(df.fieldname),
						   ", ".join(sorted(allowed)) or "(nothing)"))
			else:
				target = df.options
				if not target or not frappe.db.exists("DocType", target):
					continue
				seen = {}
				for row in rows:
					value = row.get(df.fieldname)
					if not value:
						continue
					if value not in seen:
						seen[value] = frappe.db.exists(target, value)
					if not seen[value]:
						found += 1
						print("Work Management: AUDIT %s row #%s %s = %r, "
							"which is not a %s that exists"
							% (child, row.idx, df.fieldname, value, target))
	if found:
		print("Work Management: AUDIT found %d value(s) that would fail a full "
			"save of %s. Only `kind` is fixed by this patch." % (found, PARENT))
	return found


def execute():
	if not frappe.db.table_exists(TABLE):
		return

	options = _select_options(TABLE, FIELD) or list(VALID)
	rows = frappe.db.get_all(TABLE, filters={"parenttype": PARENT},
		fields=["name", "idx", "stage", FIELD, "enabled"])
	bad = failing_values(rows, options)

	for row in bad:
		was = row.get(FIELD)
		frappe.db.set_value(TABLE, row.name,
			{FIELD: replacement(was), "enabled": 0}, update_modified=False)
		print("Work Management: stage %r row #%s had kind %r, which the doctype no "
			"longer offers -- written as %r and switched off"
			% (row.get("stage") or "(unnamed)", row.idx, was, replacement(was)))

	if bad:
		frappe.db.commit()
		print("Work Management: normalised %d legacy stage kind(s)" % len(bad))

	audit()
