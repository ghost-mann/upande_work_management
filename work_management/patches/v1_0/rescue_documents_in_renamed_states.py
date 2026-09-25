"""Move documents waiting under a step's old state name to the step's new one.

**Why.** On this branch the catalogue's internal names are Altura's (see
approvals.CATALOGUE). Five steps changed state or action from the upstream
names every existing site was built with -- and a document carries its state
BY NAME. Regenerate the workflows without moving the documents and every one
sitting in a renamed state falls out of its workflow: no pill, no queue, no
button. That is exactly the fault this change exists to end; the patch must not
reintroduce it for one deploy.

**What.** By stage key, old upstream state -> catalogue state:

    Work Management Actuals      Pending Farm Manager -> Pending Approval
    Work Management Actuals      Pending HR Head      -> Pending Manager
    Work Management Assigner     Pending Farm Manager -> Pending Manager
    Work Management Master Plan  Pending GM           -> Pending Manager

(masterplan_submit only changed its action, so nothing waits under a new name.)

**Order, in ONE transaction** -- a patch is committed as a whole, so no reader
ever sees documents in a state their workflow lacks:

    1. the stage rows take the catalogue's state and action   (db-level)
    2. the documents move, each one printed and commented
    3. their open Workflow Action to-dos move with them
    4. the five workflows are rebuilt from the rows written in 1
    5. anything still outside its workflow is printed, and left alone

It runs in post_model_sync, before after_migrate. after_migrate's seed_stages()
and build_workflows() then find nothing to change and save nothing.

Db-level in 1 rather than a Settings save: saving Settings runs its whole
validation, and a Stage Approver row key_stage_approvers_by_stage could not key
is refused there by design -- which would take this migrate down with it.

**Idempotent.** A second run finds no document in an old state and writes
nothing. Only the old names listed below are moved, and only within their own
document type: `Pending GM` still means the GM step on the Assigner and Actuals.
"""

import frappe

SETTINGS = "Work Management Settings"
STAGE_TABLE = "Work Management Approval Stage"

#: stage key -> the upstream (state, action) it was built with
UPSTREAM = {
	"masterplan_submit": ("Draft", "Send for Consultant Review"),
	"masterplan_gm": ("Pending GM", "GM Approve"),
	"assigner_farm_manager": ("Pending Farm Manager", "FM Approve"),
	"actuals_farm_manager": ("Pending Farm Manager", "FM Approve"),
	"actuals_hr_head": ("Pending HR Head", "HR Approve"),
}


def moves():
	"""[(document_type, old_state, new_state, key)] -- the renames that move documents."""
	from work_management import approvals

	shipped = {stage.key: stage for stage in approvals.CATALOGUE}
	out = []
	for key, (old_state, _old_action) in UPSTREAM.items():
		stage = shipped.get(key)
		if stage and stage.state and stage.state != old_state:
			out.append((stage.document_type, old_state, stage.state, key))
	return out


def execute():
	if not frappe.db.table_exists(STAGE_TABLE):
		return
	from work_management import approvals

	# 1. the rows take the catalogue's names
	shipped = {stage.key: stage for stage in approvals.CATALOGUE}
	for row in frappe.get_all(STAGE_TABLE, filters={"parent": SETTINGS, "parenttype": SETTINGS},
			fields=["name", "stage", "state", "action"]):
		stage = shipped.get(row.stage)
		if stage and (row.state != stage.state or row.action != stage.action):
			frappe.db.set_value(STAGE_TABLE, row.name,
				{"state": stage.state, "action": stage.action}, update_modified=False)
			print(f"Approval stage {row.stage}: {row.state} / {row.action} -> "
				f"{stage.state} / {stage.action}")
	frappe.clear_cache(doctype=SETTINGS)

	# 2 + 3. the documents, and their open to-dos
	moved = 0
	for doctype, old, new, key in moves():
		if not frappe.db.table_exists(doctype):
			continue
		names = frappe.get_all(doctype, filters={"workflow_state": old}, pluck="name")
		for name in names:
			frappe.db.set_value(doctype, name, "workflow_state", new, update_modified=False)
			frappe.get_doc({
				"doctype": "Comment", "comment_type": "Info",
				"reference_doctype": doctype, "reference_name": name,
				"content": f"Workflow state renamed {old} → {new} (step {key}); nothing "
					"else about this document changed.",
			}).insert(ignore_permissions=True)
			print(f"{doctype} {name}: {old} -> {new}")
			moved += 1
		if names and frappe.db.table_exists("Workflow Action"):
			frappe.db.sql("""UPDATE `tabWorkflow Action` SET workflow_state = %s
				WHERE reference_doctype = %s AND workflow_state = %s AND status = 'Open'""",
				(new, doctype, old))

	# 4. the workflows, from the rows written in 1
	settings = frappe.get_doc(SETTINGS)
	rebuilt = approvals.build_workflows(settings)
	print(f"Moved {moved} document(s); rebuilt {', '.join(rebuilt) or 'no workflow (unchanged)'}")

	# 5. whatever is still outside its workflow is reported, never moved
	for doctype, name, state in stranded():
		print(f"NOT MOVED -- {doctype} {name} is in {state!r}, which its workflow does not "
			"have. Move it by hand.")


def stranded():
	"""[(document_type, name, state)] for documents in a state their workflow lacks."""
	from work_management import approvals

	out = []
	for doctype, ends in approvals.CHAIN_ENDS.items():
		if not frappe.db.table_exists(doctype) or not frappe.db.exists("Workflow", ends["workflow"]):
			continue
		states = set(frappe.get_all("Workflow Document State",
			filters={"parent": ends["workflow"]}, pluck="state"))
		for row in frappe.get_all(doctype, filters={"workflow_state": ["is", "set"]},
				fields=["name", "workflow_state"]):
			if row.workflow_state not in states:
				out.append((doctype, row.name, row.workflow_state))
	return out
