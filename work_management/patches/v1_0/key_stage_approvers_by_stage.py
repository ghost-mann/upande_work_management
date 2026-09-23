"""Key every Stage Approver row by its step, not by the step's name.

MUST RUN BEFORE ANYBODY RENAMES A STEP AGAIN. It matches each row by the name it
carries, so it can only key the rows whose name still identifies a step. Every
rename made before this runs is a row it may not be able to recover.

**What broke.** `Work Management Stage Approver.stage_label` stored the step's
*label*, and both places that read the table matched on it: approvers_for()
(so transition_groups()) and _desired_grants(). Rename a step in Settings and
every approver row for it silently stopped matching. transition_groups() then
saw "nobody listed" and generated one unconditional transition on the stage
role, so per-farm scoping collapsed -- any holder of that role approved every
farm. And the next Settings save was refused with "Stage cannot be ...",
because the picker's options had moved to the new names and the stored rows had
not. Altura was armed for exactly this: six approver rows and a relabelled chain.

**What this does.** The doctype now has a `stage` column holding the step key,
which does not move when a name does. For each row with no key yet:

    1. its name matches a step's CURRENT name      -> that step
    2. else it matches a SHIPPED catalogue name    -> that step
       (a row written before the site renamed the step carries the old one)
    3. else it is left unkeyed and printed into the migrate log

A row left unkeyed is not deleted -- somebody configured it and should decide.
The next Settings save names it ("row N names a step that is not in the
approval chain") instead of the old "Stage cannot be ...". Pick the step again
in Settings > Stage Approvers.

Db-level, no document save: saving Settings runs sync_roles() and
build_workflows(), which is after_migrate's job, not a patch's.

And the old picker's Property Setter goes: `stage_label` is plain Data now, and
an options setter left on it would name steps by label forever.
"""

import frappe

TABLE = "Work Management Stage Approver"
SETTINGS = "Work Management Settings"


def execute():
	if not frappe.db.table_exists(TABLE) or not frappe.db.table_exists("Work Management Approval Stage"):
		return
	frappe.reload_doc("work_management", "doctype", "work_management_stage_approver")

	from work_management import approvals

	current = {}
	for row in frappe.get_all("Work Management Approval Stage",
			filters={"parent": SETTINGS, "parenttype": SETTINGS},
			fields=["stage", "stage_label"]):
		if row.stage and row.stage_label:
			current.setdefault(row.stage_label.strip(), row.stage)
	shipped = {stage.label: stage.key for stage in approvals.CATALOGUE}
	known = set(current.values()) | set(shipped.values())

	keyed, left = [], []
	for row in frappe.get_all(TABLE,
			filters={"parent": SETTINGS, "parenttype": SETTINGS},
			fields=["name", "idx", "stage", "stage_label", "user"], order_by="idx"):
		if (row.stage or "").strip() in known:
			continue
		label = (row.stage_label or "").strip()
		key = current.get(label) or shipped.get(label)
		if key:
			frappe.db.set_value(TABLE, row.name, "stage", key, update_modified=False)
			keyed.append((row.idx, label, key))
		else:
			left.append((row.idx, label, row.user))

	frappe.db.delete("Property Setter", {
		"doc_type": TABLE, "field_name": "stage_label", "property": "options"})
	frappe.clear_cache(doctype=TABLE)

	for idx, label, key in keyed:
		print(f"Stage Approvers row {idx}: {label!r} -> {key}")
	for idx, label, user in left:
		print(f"Stage Approvers row {idx} ({user}): {label!r} matches no step -- "
			"pick its step again in Work Management Settings")
