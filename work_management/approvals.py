"""Approval stages, and the workflows generated from them.

The approval chain used to live in `fixtures/workflow.json`, with Kaitet's farm
names spelled into transition conditions and one role per farm hardcoded. That
made the app unshippable: a new project could not change who approves what
without editing the app.

Now the chain is described once, here, as a catalogue of stages. Which stages
are on, which role takes each step and which people hold that role are read from
Work Management Settings. `build_workflows()` turns that configuration into
ordinary role-based Frappe Workflow documents, so approvers keep the workflow
action buttons, the notifications and the awaiting-approval inbox that Frappe
already gives them.

Everything here is idempotent. It runs on `after_migrate` and whenever Settings
is saved.
"""

from collections import namedtuple

import frappe
from frappe import _

# The field every pipeline doctype scopes work by. Farm-scoped stages compare
# against it in generated transition conditions.
SCOPE_FIELD = "farm"

Stage = namedtuple(
	"Stage",
	"key label document_type kind state action role scoped required",
)


def _stage(key, label, document_type, kind, state, action, role, scoped=False, required=False):
	return Stage(key, label, document_type, kind, state, action, role, scoped, required)


# Order matters: within a document type these are the steps of the chain, and a
# stage approves into the next enabled one.
#
# kind:
#   Submit   -- moves a draft into the chain. Cannot be switched off.
#   Approval -- a step with an approve action and a reject action.
#   Gate     -- not a workflow transition at all. A screen-level check that
#               reads its approvers from the same table.
CATALOGUE = [
	_stage("masterplan_submit", "Master Plan: Submit", "Work Management Master Plan",
		"Submit", "Draft", "Send for Consultant Review", "Farm Manager", required=True),
	_stage("masterplan_consultant", "Master Plan: Consultant", "Work Management Master Plan",
		"Approval", "Pending Consultant", "Send to GM", "System Manager"),
	_stage("masterplan_gm", "Master Plan: GM", "Work Management Master Plan",
		"Approval", "Pending GM", "GM Approve", "General Manager"),

	_stage("planner_submit", "Planner: Submit", "Work Management Planner",
		"Submit", "Draft", "Submit for Approval", "Production Section Head", required=True),
	_stage("planner_farm_approval", "Planner: Farm Approval", "Work Management Planner",
		"Approval", "Pending Approval", "Approve", "Farm Manager", scoped=True),
	_stage("planner_weekly_consultant", "Planner: Weekly Consultant", "Work Management Planner",
		"Gate", None, None, "System Manager"),

	_stage("assigner_submit", "Assigner: Submit", "Work Management Assigner",
		"Submit", "Draft", "Submit for Approval", "HR User", required=True),
	_stage("assigner_farm_manager", "Assigner: Farm Manager", "Work Management Assigner",
		"Approval", "Pending Farm Manager", "FM Approve", "Farm Manager", scoped=True),
	_stage("assigner_hr_head", "Assigner: HR Head", "Work Management Assigner",
		"Approval", "Pending HR Head", "HR Approve", "HOD HR"),
	_stage("assigner_gm", "Assigner: GM", "Work Management Assigner",
		"Approval", "Pending GM", "GM Approve", "General Manager"),

	_stage("actuals_submit", "Actuals: Submit", "Work Management Actuals",
		"Submit", "Draft", "Submit for Approval", "HR Clerk", required=True),
	_stage("actuals_farm_manager", "Actuals: Farm Manager", "Work Management Actuals",
		"Approval", "Pending Farm Manager", "FM Approve", "Farm Manager", scoped=True),
	_stage("actuals_hr_head", "Actuals: HR Head", "Work Management Actuals",
		"Approval", "Pending HR Head", "HR Approve", "HOD HR"),
	_stage("actuals_gm", "Actuals: GM", "Work Management Actuals",
		"Approval", "Pending GM", "GM Approve", "General Manager"),

	_stage("payment_accounts", "Payment: Accounts", "Work Management Payment",
		"Approval", "Unpaid", "Mark Paid", "Accounts Manager", required=True),
]

# Where each chain ends, and where a rejection lands. Taken from the workflows
# that ran on the live site, so a generated workflow behaves as the hand-built
# one did.
CHAIN_ENDS = {
	"Work Management Master Plan": {
		"workflow": "Work Management Master Plan Approval",
		"terminal": ("Approved", 0),
		"reject": "Rejected",
		"resubmit": "Re-submit",
	},
	"Work Management Planner": {
		"workflow": "Work Management Planner Approval",
		"terminal": ("Approved", 1),
		"reject": "Rejected",
		"resubmit": "Re-submit",
	},
	"Work Management Assigner": {
		"workflow": "Work Management Assigner Approval",
		"terminal": ("Assigned", 1),
		"reject": "Rejected",
		"resubmit": "Re-submit",
	},
	"Work Management Actuals": {
		"workflow": "Work Management Actuals Approval",
		"terminal": ("CONFIRMED", 1),
		"reject": "Rejected",
		"resubmit": "Re-submit",
	},
	"Work Management Payment": {
		"workflow": "Work Management Payment Approval",
		"terminal": ("Paid", 0),
		"reject": "Cancelled",
		"resubmit": None,
		# Accounts called it cancelling, not rejecting, and a payment already
		# marked paid could still be cancelled. Both kept.
		"reject_action": "Cancel",
		"cancel_from_terminal": True,
	},
}

DEFAULT_REJECT_ACTION = "Reject"


# ---------------------------------------------------------------- catalogue


def by_key(key):
	for stage in CATALOGUE:
		if stage.key == key:
			return stage
	return None


def by_label(label):
	for stage in CATALOGUE:
		if stage.label == label:
			return stage
	return None


def stage_labels():
	"""Select options for Work Management Stage Approver.stage_label."""
	return [stage.label for stage in CATALOGUE]


def chain_for(document_type):
	"""The workflow steps of one document type, in order. Gates are not steps."""
	return [
		stage for stage in CATALOGUE
		if stage.document_type == document_type and stage.kind in ("Submit", "Approval")
	]


# ------------------------------------------------------------------ settings


def _settings():
	return frappe.get_cached_doc("Work Management Settings")


def seed_stages(settings=None, save=True):
	"""Ensure Settings holds one row per catalogue stage, in catalogue order.

	Existing rows keep the role and the on/off flag someone chose. Rows for
	stages that no longer exist are dropped. Called on install and on every
	migrate, so adding a stage to the catalogue is all it takes to ship it.
	"""
	settings = settings or frappe.get_doc("Work Management Settings")
	existing = {row.stage: row for row in (settings.get("approval_stages") or [])}

	rows = []
	for stage in CATALOGUE:
		previous = existing.get(stage.key)
		rows.append({
			"stage": stage.key,
			"stage_label": stage.label,
			"document_type": stage.document_type,
			"kind": stage.kind,
			"enabled": 1 if stage.required else (previous.enabled if previous else 1),
			"role": (previous.role if previous and previous.role else stage.role),
		})

	settings.set("approval_stages", [])
	for row in rows:
		settings.append("approval_stages", row)

	if save:
		settings.flags.ignore_permissions = True
		settings.flags.skip_approval_sync = True
		settings.save()
	return settings


def stage_rows(settings=None):
	"""{stage key: settings row}, for the stages the catalogue still knows."""
	settings = settings or _settings()
	rows = {}
	for row in settings.get("approval_stages") or []:
		if by_key(row.stage):
			rows[row.stage] = row
	return rows


def is_enabled(stage, rows):
	if stage.required:
		return True
	row = rows.get(stage.key)
	return bool(row.enabled) if row else True


def stage_role(stage, rows):
	row = rows.get(stage.key)
	return (row.role if row and row.role else stage.role)


def approvers_for(key, settings=None):
	"""Approver rows configured for one stage."""
	stage = by_key(key)
	if not stage:
		return []
	settings = settings or _settings()
	return [
		row for row in (settings.get("stage_approvers") or [])
		if row.stage_label == stage.label
	]


def approver_users(key, scope=None, settings=None):
	"""Emails configured to act at one stage, optionally for one farm.

	A row with no farm acts on every farm, so it is always included.
	"""
	users = []
	for row in approvers_for(key, settings=settings):
		if scope and row.scope and row.scope != scope:
			continue
		if row.user and row.user not in users:
			users.append(row.user)
	return users


# ------------------------------------------------------- transition grouping


def transition_groups(stage, rows, settings):
	"""The (scope, role) pairs a stage's transitions are generated for.

	An unscoped stage yields one pair per distinct role among its approvers, or
	the stage role when nobody is listed. A farm-scoped stage yields one pair per
	farm that has an approver, plus an unscoped pair for approvers listed without
	a farm. `scope` of None means the transition carries no condition and so
	applies to every farm.
	"""
	default_role = stage_role(stage, rows)
	approvers = approvers_for(stage.key, settings=settings)

	if not approvers:
		return [(None, default_role)]

	pairs = []
	for row in approvers:
		scope = row.scope if stage.scoped else None
		role = row.role or default_role
		if (scope, role) not in pairs:
			pairs.append((scope, role))
	return pairs


# ------------------------------------------------------- workflow generation


def _ensure_workflow_vocabulary(states, actions):
	"""Frappe validates state and action names as links, so they must exist."""
	for state in states:
		if state and not frappe.db.exists("Workflow State", state):
			frappe.get_doc({
				"doctype": "Workflow State",
				"workflow_state_name": state,
				"style": "Success" if state in ("Approved", "Assigned", "CONFIRMED", "Paid") else "",
			}).insert(ignore_permissions=True)
	for action in actions:
		if action and not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc({
				"doctype": "Workflow Action Master",
				"workflow_action_name": action,
			}).insert(ignore_permissions=True)


def plan_workflow(document_type, rows=None, settings=None):
	"""The states and transitions a document type's workflow should hold.

	Pure: it reads configuration and returns a plan. `build_workflows()` writes
	it. Keeping the two apart is what makes the chain logic testable without a
	database.
	"""
	settings = settings or _settings()
	rows = rows if rows is not None else stage_rows(settings)
	ends = CHAIN_ENDS[document_type]
	terminal_state, terminal_docstatus = ends["terminal"]
	reject_state = ends["reject"]
	reject_action = ends.get("reject_action", DEFAULT_REJECT_ACTION)

	chain = [stage for stage in chain_for(document_type) if is_enabled(stage, rows)]
	if not chain:
		return None

	submit_role = stage_role(chain[0], rows)

	states = []
	seen_states = set()

	def add_state(state, doc_status, allow_edit):
		if state in seen_states:
			return
		seen_states.add(state)
		states.append({"state": state, "doc_status": doc_status, "allow_edit": allow_edit})

	for stage in chain:
		add_state(stage.state, 0, stage_role(stage, rows))
	add_state(terminal_state, terminal_docstatus, stage_role(chain[-1], rows))
	add_state(reject_state, 0, submit_role)

	transitions = []

	def add_transition(state, action, next_state, allowed, condition=None):
		entry = {
			"state": state,
			"action": action,
			"next_state": next_state,
			"allowed": allowed,
			"condition": condition or "",
			"allow_self_approval": 1,
		}
		if entry not in transitions:
			transitions.append(entry)

	for index, stage in enumerate(chain):
		next_state = chain[index + 1].state if index + 1 < len(chain) else terminal_state
		for scope, role in transition_groups(stage, rows, settings):
			condition = f'doc.{SCOPE_FIELD} == "{scope}"' if scope else None
			add_transition(stage.state, stage.action, next_state, role, condition)
			if stage.kind == "Approval":
				add_transition(stage.state, reject_action, reject_state, role, condition)

	# A rejection goes back to the first approval step, not to the draft state:
	# the document has already been submitted once.
	if ends["resubmit"] and len(chain) > 1:
		add_transition(reject_state, ends["resubmit"], chain[1].state, submit_role)

	# Payments could be cancelled after being marked paid. Nothing else can be
	# undone once its chain has finished.
	if ends.get("cancel_from_terminal"):
		for _, role in transition_groups(chain[-1], rows, settings):
			add_transition(terminal_state, reject_action, reject_state, role)

	return {
		"workflow_name": ends["workflow"],
		"document_type": document_type,
		"states": states,
		"transitions": transitions,
	}


def build_workflows(settings=None):
	"""Write the generated plan onto the five Workflow documents.

	Updated in place, never deleted and recreated -- deleting a Workflow that
	documents are sitting in mid-approval orphans them.
	"""
	settings = settings or _settings()
	rows = stage_rows(settings)
	built = []

	for document_type in CHAIN_ENDS:
		if not frappe.db.exists("DocType", document_type):
			continue
		plan = plan_workflow(document_type, rows=rows, settings=settings)
		if not plan:
			continue

		_ensure_workflow_vocabulary(
			[state["state"] for state in plan["states"]],
			[transition["action"] for transition in plan["transitions"]],
		)

		name = plan["workflow_name"]
		if frappe.db.exists("Workflow", name):
			workflow = frappe.get_doc("Workflow", name)
		else:
			workflow = frappe.new_doc("Workflow")
			workflow.workflow_name = name

		workflow.document_type = document_type
		workflow.workflow_state_field = "workflow_state"
		workflow.is_active = 1
		workflow.override_status = 0
		workflow.send_email_alert = 0

		workflow.set("states", [])
		for state in plan["states"]:
			workflow.append("states", state)
		workflow.set("transitions", [])
		for transition in plan["transitions"]:
			workflow.append("transitions", transition)

		workflow.flags.ignore_permissions = True
		workflow.save()
		built.append(name)

	return built


# ------------------------------------------------------------- role syncing


def managed_roles(settings=None):
	"""Every role this module hands out, so revoking never touches others."""
	settings = settings or _settings()
	rows = stage_rows(settings)
	roles = {stage.role for stage in CATALOGUE}
	roles |= {row.role for row in rows.values() if row.role}
	roles |= {row.role for row in (settings.get("stage_approvers") or []) if row.role}
	return {role for role in roles if role}


def _desired_grants(settings):
	"""{user: {role}} the configuration asks for."""
	rows = stage_rows(settings)
	grants = {}
	for approver in settings.get("stage_approvers") or []:
		stage = by_label(approver.stage_label)
		if not stage or not approver.user:
			continue
		role = approver.role or stage_role(stage, rows)
		if not role:
			continue
		grants.setdefault(approver.user, set()).add(role)
	return grants


def sync_roles(settings=None, previous=None):
	"""Grant each approver the role their stage runs on, and revoke on removal.

	Revocation is deliberately narrow. Only a role this module manages is ever
	removed, and only from a user who was listed before and is not listed for it
	now. A role someone was given by hand, or holds for another reason, is left
	alone.
	"""
	settings = settings or _settings()
	desired = _desired_grants(settings)
	previously = _desired_grants(previous) if previous else {}
	# The previous state matters as much as the current one. A role that was only
	# ever named by the row just deleted is no longer "managed" by the new
	# configuration, and revocation would skip the very role it needs to remove.
	manageable = managed_roles(settings)
	if previous:
		manageable |= managed_roles(previous)

	granted, revoked = [], []

	for user, roles in desired.items():
		if not frappe.db.exists("User", user):
			continue
		user_doc = frappe.get_doc("User", user)
		held = {row.role for row in user_doc.get("roles") or []}
		missing = roles - held
		if not missing:
			continue
		for role in sorted(missing):
			if frappe.db.exists("Role", role):
				user_doc.append("roles", {"role": role})
				granted.append((user, role))
		user_doc.flags.ignore_permissions = True
		user_doc.save()

	for user, roles in previously.items():
		stale = {role for role in roles - desired.get(user, set()) if role in manageable}
		if not stale or not frappe.db.exists("User", user):
			continue
		user_doc = frappe.get_doc("User", user)
		keep = [row for row in user_doc.get("roles") or [] if row.role not in stale]
		if len(keep) == len(user_doc.get("roles") or []):
			continue
		user_doc.set("roles", [])
		for row in keep:
			user_doc.append("roles", {"role": row.role})
		user_doc.flags.ignore_permissions = True
		user_doc.save()
		revoked.extend((user, role) for role in sorted(stale))

	return {"granted": granted, "revoked": revoked}


# -------------------------------------------------------------- validation


def validate_configuration(settings):
	"""Refuse a configuration that would strand a document.

	A farm-scoped stage with per-farm approvers generates one conditional
	transition per farm. A farm nobody approves for has no transition at all, so
	its documents would sit in that state with no way out. Better to say so on
	save than to discover it when a plan cannot be approved.
	"""
	rows = stage_rows(settings)
	farms = frappe.get_all(
		"Work Management Farm", filters={"disabled": 0}, pluck="name",
	) if frappe.db.exists("DocType", "Work Management Farm") else []
	if not farms:
		return

	for stage in CATALOGUE:
		if not stage.scoped or stage.kind != "Approval" or not is_enabled(stage, rows):
			continue
		approvers = approvers_for(stage.key, settings=settings)
		if not approvers:
			# Nobody configured: the stage role covers every farm. Fine.
			continue
		if any(not row.scope for row in approvers):
			# Someone approves every farm. Fine.
			continue
		covered = {row.scope for row in approvers if row.scope}
		missing = [farm for farm in farms if farm not in covered]
		if missing:
			frappe.throw(
				_("{0} has approvers for some farms but not {1}. Work for those farms would have nobody to approve it — add an approver, or leave one approver's Farm empty to cover every farm.").format(
					frappe.bold(stage.label), frappe.bold(", ".join(missing)),
				),
				title=_("Approval stage would strand a farm"),
			)


# ------------------------------------------------------------------- hooks


def after_migrate():
	"""Keep the seeded stages and the generated workflows in step with the code."""
	if not frappe.db.exists("DocType", "Work Management Settings"):
		return
	seed_stages()
	frappe.clear_cache(doctype="Work Management Settings")
	build_workflows()
	frappe.db.commit()
