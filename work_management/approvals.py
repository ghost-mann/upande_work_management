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
	"key label document_type kind state action role scoped required default_off",
)


def _stage(key, label, document_type, kind, state, action, role, scoped=False, required=False,
		default_off=False):
	return Stage(key, label, document_type, kind, state, action, role, scoped, required,
		default_off)


# The default chain a fresh install starts with -- the seed, not the chain: see
# configured_stages(). Every step defaults to System Manager, deliberately. This
# app used to default to Kaitet's own job titles and ship five Roles as fixtures
# so they would exist, which meant installing at any company created that
# company's hierarchy for them. A default has to name a role that exists, because
# a Workflow Transition's role is a Link; System Manager is the only one Frappe
# guarantees. So a fresh install arrives with every approval sitting with System
# Manager -- visible, safe, and obviously not final -- and the project points each
# step at its own role. An existing deployment is untouched: seed_stages() keeps
# whatever role was configured.
#
# Order matters: within a document type these are the steps of the chain, and a
# stage approves into the next enabled one.
#
# kind:
#   Submit   -- moves a draft into the chain. Cannot be switched off.
#   Approval -- a step with an approve action and a reject action.
#
# There used to be a third, `Gate`: "not a workflow transition at all, a
# screen-level check". Nothing ever read it. The one Gate stage shipped -- a
# weekly consultant review on the planner -- was inert, and so was the Settings
# checkbox that promised the same rule. Both are gone. The consultant control that
# works is `consultant_state` on each Master Plan Activity: a consultant settles
# individual activities and the planner only offers ones marked OK.
# ON THE `altura` BRANCH THESE ARE ALTURA'S NAMES. The state a document waits in
# and the action that leaves it are the workflow's INTERNAL vocabulary: every
# document carries the state by name, so renaming one strands whatever sits in
# it. They are fixed here, by key, and locked in the Settings grid -- a step is
# relabelled through its label, never through these. seed_stages() writes them
# onto the rows on every migrate, which is what keeps them fixed. The fork exists
# for this client, so its defaults are this client's words; master keeps the
# upstream names. Changed from upstream: masterplan_submit's action, masterplan_gm,
# assigner_farm_manager, actuals_farm_manager and actuals_hr_head (state and
# action). The patch rescue_documents_in_renamed_states moves documents that
# were waiting under the old names.
CATALOGUE = [
	_stage("masterplan_submit", "Master Plan: Submit", "Work Management Master Plan",
		"Submit", "Draft", "Send for Review", "System Manager", required=True),
	_stage("masterplan_consultant", "Master Plan: Consultant", "Work Management Master Plan",
		"Approval", "Pending Consultant", "Send to GM", "System Manager"),
	_stage("masterplan_gm", "Master Plan: GM", "Work Management Master Plan",
		"Approval", "Pending Manager", "Manager Approve", "System Manager"),

	_stage("planner_submit", "Planner: Submit", "Work Management Planner",
		"Submit", "Draft", "Submit for Approval", "System Manager", required=True),
	_stage("planner_farm_approval", "Planner: Farm Approval", "Work Management Planner",
		"Approval", "Pending Approval", "Approve", "System Manager", scoped=True),
	# A SECOND planner approval, shipped OFF.
	#
	# The Planner was the one chain with a single approval step, and Altura wants
	# two: the section head raises, the farm manager approves, HR approves after
	# them. Every other chain could express its target by switching steps off and
	# swapping roles; this one had nothing to switch on.
	#
	# `default_off` because a catalogue entry reaches every installation. seed_stages()
	# gives a row it has never seen before `enabled = 1`, which is right for the
	# fourteen steps that describe how this pipeline has always run and wrong for a
	# step nobody has asked for: an existing site would migrate and discover a new
	# approval standing between its planners and their work. Off, it costs those
	# sites nothing -- effective_chain() relinks Farm Approval straight to Approved,
	# exactly as before -- and Altura turns it on in Settings.
	#
	# The role is System Manager like every other shipped step, NOT HOD HR. The brief
	# asked for HOD HR and it cannot be shipped: it is one of the five job titles this
	# app was deliberately stopped from inventing (see test_no_shipped_roles), and a
	# Workflow Transition's role is a Link, so defaulting to a role the site may not
	# have breaks the generated workflow's save. Altura points the step at HOD HR in
	# Settings, which is where the rest of its chain is configured too.
	_stage("planner_hr_approval", "Planner: HR Approval", "Work Management Planner",
		"Approval", "Pending HR Approval", "HR Approve", "System Manager", default_off=True),

	_stage("assigner_submit", "Assigner: Submit", "Work Management Assigner",
		"Submit", "Draft", "Submit for Approval", "System Manager", required=True),
	_stage("assigner_farm_manager", "Assigner: Farm Manager", "Work Management Assigner",
		"Approval", "Pending Manager", "Approve", "System Manager", scoped=True),
	_stage("assigner_hr_head", "Assigner: HR Head", "Work Management Assigner",
		"Approval", "Pending HR Head", "HR Approve", "System Manager"),
	_stage("assigner_gm", "Assigner: GM", "Work Management Assigner",
		"Approval", "Pending GM", "GM Approve", "System Manager"),

	_stage("actuals_submit", "Actuals: Submit", "Work Management Actuals",
		"Submit", "Draft", "Submit for Approval", "System Manager", required=True),
	# Two steps, one action name: Frappe tells transitions apart by (state,
	# action), and nothing in this app resolves a step by its action.
	_stage("actuals_farm_manager", "Actuals: Farm Manager", "Work Management Actuals",
		"Approval", "Pending Approval", "Approve", "System Manager", scoped=True),
	_stage("actuals_hr_head", "Actuals: HR Head", "Work Management Actuals",
		"Approval", "Pending Manager", "Approve", "System Manager"),
	_stage("actuals_gm", "Actuals: GM", "Work Management Actuals",
		"Approval", "Pending GM", "GM Approve", "System Manager"),

	_stage("payment_accounts", "Payment: Accounts", "Work Management Payment",
		"Approval", "Unpaid", "Mark Paid", "System Manager", required=True),
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

# Distinguishes "you did not say" from "there is no configuration". The first
# reads Settings; the second falls back to the shipped chain without touching a
# database -- which is what an unconfigured install needs, and what lets the pure
# helpers below be tested without a site.
_UNSET = object()


# ------------------------------------------------------- the configured chain


def configured_stages(settings=None):
	"""The chain this installation runs, read from Settings, in its own order.

	CATALOGUE used to *be* the chain. Settings looked like it held it -- fifteen
	editable rows -- but only rows whose key the code recognised were honoured and
	seed_stages() deleted the rest, so a step somebody added was thrown away by
	the next migrate. Switching a step off was configuration; adding one was a
	release. That is the wall this app hits at a second company.

	Now the catalogue is the seed and this is the chain. A row with a key the code
	has never heard of is a step like any other: it carries its own state, action,
	kind and role, which is everything the workflow generator needs.

	Order is the rows' own order, so dragging a row in the grid moves the step.
	A row with no key is skipped rather than raising -- a half-typed row in an
	open grid must not take a migrate down. No rows at all means a site mid-install,
	which falls back to the shipped chain so workflows can still be generated.
	"""
	rows = (settings.get("approval_stages") if settings else None) or []
	shipped = {stage.key: stage for stage in CATALOGUE}
	stages = []
	for row in sorted(rows, key=lambda r: r.get("idx") or 0):
		key = (row.get("stage") or "").strip()
		if not key:
			continue
		# A blank column on a row whose key the catalogue knows falls back to the
		# shipped value, the way the role already does. seed_stages() writes these
		# in, so a blank one is a half-filled row rather than an intention -- and a
		# step with no state is not a step, it is a hole the chain resolves through
		# to nothing. The role fallback set this precedent; these follow it.
		default = shipped.get(key)
		stages.append(Stage(
			key=key,
			label=(row.get("stage_label") or (default.label if default else key)),
			document_type=(row.get("document_type")
				or (default.document_type if default else None)),
			kind=(row.get("kind") or (default.kind if default else "Approval")),
			state=(row.get("state") or (default.state if default else None)),
			action=(row.get("action") or (default.action if default else None)),
			role=row.get("role"),
			scoped=bool(row.get("scoped")),
			required=bool(row.get("required")),
			# not a row field: it only decides what a row gets the first time
			# seed_stages() writes one. Once the row exists, `enabled` is the answer.
			default_off=bool(default.default_off) if default else False,
		))
	return stages or list(CATALOGUE)


# ---------------------------------------------------------------- catalogue


def _given_or_stored(settings):
	"""The settings a caller handed in, else the stored ones.

	`is None` rather than `or`: a caller validating an in-progress Settings doc,
	or a test building the shipped configuration on a relabelled site, is asking
	about THAT configuration. Swapping in the stored one answered a different
	question -- plan_workflow(settings=<shipped>) came back in the site's labels.
	"""
	return _settings_or_none() if settings is None else settings


def by_key(key, settings=None):
	for stage in configured_stages(_given_or_stored(settings)):
		if stage.key == key:
			return stage
	return None


def by_label(label, settings=None):
	for stage in configured_stages(_given_or_stored(settings)):
		if stage.label == label:
			return stage
	return None


def stage_labels(settings=None):
	"""Every configured step's name, in chain order."""
	return [stage.label for stage in configured_stages(_given_or_stored(settings))]


def stage_keys(settings=None):
	"""Select options for Work Management Stage Approver.stage -- the step keys."""
	return [stage.key for stage in configured_stages(_given_or_stored(settings))]


def duplicate_stage_labels(labels):
	"""The labels used more than once, or None. Pure.

	The picker stores a *label*, so two steps sharing one make it ambiguous: an
	approver row would resolve to whichever step sorted first, and nothing would
	say so. Cheap to refuse on save; impossible to diagnose later.
	"""
	seen = set()
	twice = []
	for label in labels:
		name = (label or "").strip()
		if not name:
			continue
		if name in seen and name not in twice:
			twice.append(name)
		seen.add(name)
	return ", ".join(twice) if twice else None


# The approver row names its step by KEY. It stored the step's label, so renaming
# a step silently detached every approver row pointing at it: approvers_for()
# stopped matching, transition_groups() fell back to one unconditional
# transition on the stage role -- any holder of it approved every farm -- and the
# next Settings save was refused with "Stage cannot be ..." against a picker
# that no longer offered the old name. A key does not move when a name does.
PICKER = ("Work Management Stage Approver", "stage")


def apply_stage_picker_options(settings=None):
	"""Offer every configured step in the picker that names who takes it.

	The Select ships with the fifteen catalogue keys compiled into its JSON. Once
	a step can be added, that Select lies: the step exists, drives a real
	transition, and cannot be chosen in the one table that names its approvers.
	The keys are the stored values; the Settings form shows each as the step's
	current name (work_management_settings.js), so renaming a step needs no
	setter at all.

	A Property Setter rather than an edit to the shipped JSON, following what
	taxonomy.apply_labels() does -- the app's own files stay identical on every
	site, and a site whose chain is the shipped one carries no setter at all.

	Returns the options written, or None when nothing needed changing.
	"""
	import frappe
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	doctype, fieldname = PICKER
	if not frappe.db.exists("DocType", doctype):
		return None

	keys = stage_keys(settings)
	if not keys:
		return None
	wanted = "\n".join(keys)

	shipped = "\n".join(stage.key for stage in CATALOGUE)
	filters = {"doc_type": doctype, "field_name": fieldname, "property": "options"}
	existing = frappe.db.get_value("Property Setter", filters, ["name", "value"], as_dict=True)

	if wanted == shipped:
		# the chain is the shipped one, so the JSON already says this. Remove the
		# setter rather than writing the original back over it -- a site that never
		# added a step ends up carrying nothing, which is how the taxonomy does it.
		if existing:
			frappe.delete_doc("Property Setter", existing.name, force=True,
				ignore_permissions=True)
			frappe.clear_cache(doctype=doctype)
			return None
		return None

	if existing and existing.value == wanted:
		return keys

	make_property_setter(doctype, fieldname, "options", wanted, "Text",
		validate_fields_for_doctype=False)
	frappe.clear_cache(doctype=doctype)
	return keys


def effective_chain(settings=_UNSET, rows=None, document_type=None):
	"""Every configured step, in order, each knowing where approving it leads.

	One rule, two callers. `plan_workflow()` builds the desk workflow from this
	and `get_config()` hands it to the five web screens, so the two cannot
	disagree about what follows a step -- which they did, and which stranded
	documents: the workflow skipped a disabled step while the screen still wrote
	that step's state, a state the regenerated workflow no longer contained.

	Plain dicts, not the Stage namedtuple, because this travels through
	`get_config()` into a Server Script where it has to survive serialising:

	    {"key", "label", "document_type", "kind", "state", "action",
	     "next_state", "on", "role", "scoped"}

	A **disabled** step is still returned, with `on` false. The screens need to
	know it exists so its action can refuse, rather than writing a state nothing
	is waiting in. Its `next_state` points forward all the same, so a document
	somehow sitting in it can still be moved on rather than being stuck because
	its step was switched off underneath it.

	`next_state` for the last enabled step of a document type is that type's
	terminal state, from CHAIN_ENDS -- so a screen never needs to know how a
	chain finishes, only what comes next.
	"""
	settings = _settings_or_none() if settings is _UNSET else settings
	rows = rows if rows is not None else stage_rows(settings)

	out = []
	for doctype in CHAIN_ENDS:
		if document_type and doctype != document_type:
			continue
		steps = [
			stage for stage in configured_stages(settings)
			if stage.document_type == doctype and stage.kind in ("Submit", "Approval")
		]
		if not steps:
			continue
		terminal_state = CHAIN_ENDS[doctype]["terminal"][0]
		enabled = [stage for stage in steps if is_enabled(stage, rows)]

		for stage in steps:
			# Where the chain goes from here: the first ENABLED step positioned
			# after this one, or the end of the chain. Computed by position in the
			# full list rather than the enabled list, so a disabled step resolves
			# to the same place its enabled neighbour would.
			position = steps.index(stage)
			following = [s for s in enabled if steps.index(s) > position]
			out.append({
				"key": stage.key,
				"label": stage.label,
				"document_type": doctype,
				"kind": stage.kind,
				"state": stage.state,
				"action": stage.action,
				"next_state": following[0].state if following else terminal_state,
				"on": 1 if is_enabled(stage, rows) else 0,
				# who may take this step -- the configured role, or the shipped
				# default. The screens had no access to this at all, so the Role
				# column reached the desk workflow and nothing else.
				"role": stage_role(stage, rows),
				# whether the step is decided per farm. A screen gating an approve
				# button has to know which dimension gates it: a farm-scoped step
				# asks "which farms may you decide", an unscoped one asks "do you
				# hold this step's role", and asking the wrong question either
				# refuses everybody or nobody. Without this the screens had to
				# recognise the step by key, which is the hardcoding the
				# configurable chain exists to remove.
				"scoped": 1 if stage.scoped else 0,
			})
	return out


def may_take_step(step_role, user_roles):
	"""May somebody holding `user_roles` take a step whose role is `step_role`?

	The step's own role passes, and `System Manager` passes -- the bypass the
	farm-scoped check already allowed, because somebody has to be able to unstick
	a pipeline.

	`General Manager` deliberately does NOT bypass. It is a sensible bypass for a
	farm dimension, where the GM oversees every farm, and the wrong one for a
	step: it would let the GM take the HR Head step, which is the separation the
	chain exists to express.

	A step with no role configured refuses everybody. A misconfigured gate must
	close rather than open, and an empty Role in Settings is visible where a
	silently open step is not.
	"""
	if not step_role:
		return False
	held = set(user_roles or [])
	return step_role in held or "System Manager" in held


def pipeline_states(settings=_UNSET, rows=None, document_type=None):
	"""The states of one pipeline, grouped by what a read actually means.

	For reads only, and deliberately not the mirror image of `effective_chain()`.
	Writes follow the enabled chain; reads match every state a document could be
	carrying, the states of switched-off steps included -- otherwise a list filter
	narrows the moment somebody ticks a box, and documents that went through the
	old chain drop out of reports. That would look like data loss caused by a
	setting.

	The union of every *known* state rather than a snapshot of the data: it needs
	no query, and unlike a snapshot it cannot go stale. A state nobody uses costs
	a read nothing -- no row matches it.

	Grouped because the screens' filters mean different things, and a flat list
	would silently widen them:

	    waiting   the approval steps -- somebody has to act
	    active    waiting plus the terminal state -- submitted and not rejected,
	              which is what the screens' `IN (...)` lists have always meant
	    open      draft and rejected as well -- everything still editable
	    all       every state, for a filter that must not exclude anything
	    entered   draft, the approval steps and the terminal state -- recorded
	              and not rejected
	    past_first    every approval step after the first, plus the terminal
	                  state: the first approver has signed it off
	    waiting_past_first   the same without the terminal state
	    draft / terminal / reject   the individual ones, by name

	The three derived groups replace state lists the dispatchers spelled out by
	hand -- `IN ('Pending HR Head','Pending GM','CONFIRMED')` and friends -- which
	stopped matching the moment a step's state was anything else.

	`draft` is the Submit step's own state, since that is where a document sits
	before it enters the chain.
	"""
	settings = _settings_or_none() if settings is _UNSET else settings
	rows = rows if rows is not None else stage_rows(settings)

	steps = effective_chain(settings, rows=rows, document_type=document_type)
	ends = CHAIN_ENDS.get(document_type) if document_type else None

	def uniq(*groups):
		out = []
		for group in groups:
			for state in group:
				if state and state not in out:
					out.append(state)
		return out

	draft = [step["state"] for step in steps if step["kind"] == "Submit"]
	waiting = [step["state"] for step in steps if step["kind"] == "Approval"]
	terminal = [ends["terminal"][0]] if ends else []
	reject = [ends["reject"]] if ends else []

	return {
		"draft": draft[0] if draft else None,
		"terminal": terminal[0] if terminal else None,
		"reject": reject[0] if reject else None,
		"waiting": uniq(waiting),
		"active": uniq(waiting, terminal),
		"open": uniq(draft, reject, waiting),
		"all": uniq(draft, waiting, terminal, reject),
		"entered": uniq(draft, waiting, terminal),
		"past_first": uniq(waiting[1:], terminal),
		"waiting_past_first": uniq(waiting[1:]),
	}


def chain_for(document_type, settings=None):
	"""The workflow steps of one document type, in order."""
	return [
		stage for stage in configured_stages(_given_or_stored(settings))
		if stage.document_type == document_type and stage.kind in ("Submit", "Approval")
	]


# ------------------------------------------------------------------ settings


def _settings():
	return frappe.get_cached_doc("Work Management Settings")


def _settings_or_none():
	"""Settings, or None on a site that has not got it yet.

	configured_stages() is called from module-level helpers that run during
	install, before the single doctype exists. Falling back to the shipped
	catalogue there is correct; raising is not.
	"""
	try:
		return frappe.get_cached_doc("Work Management Settings")
	except Exception:
		return None


def seed_stages(settings=None, save=True):
	"""Ensure Settings holds a row for every shipped step, and **keep the rest**.

	The catalogue is the default chain a fresh install starts with. It is no
	longer the chain: a step somebody added is a step, and this must not delete
	it. It used to -- the table was rebuilt from the catalogue on every migrate,
	so a Finance sign-off added on Monday was gone by Tuesday, silently. That is
	the reason adding a step needed a release.

	So: shipped rows are refreshed in place, keeping the role, the on/off flag and
	the wording somebody chose. Rows the catalogue does not know are left exactly
	as they are, in their own position. Nothing is dropped.
	"""
	settings = settings or frappe.get_doc("Work Management Settings")
	existing = list(settings.get("approval_stages") or [])
	by_stage = {row.stage: row for row in existing if row.stage}
	shipped = {stage.key for stage in CATALOGUE}

	rows = []
	for stage in CATALOGUE:
		previous = by_stage.get(stage.key)
		rows.append({
			"stage": stage.key,
			"stage_label": (previous.stage_label if previous and previous.stage_label
			                else stage.label),
			"document_type": stage.document_type,
			"kind": stage.kind,
			"state": stage.state,
			"action": stage.action,
			"scoped": 1 if stage.scoped else 0,
			"required": 1 if stage.required else 0,
			# A row already here keeps its own answer. A row being written for the
			# first time gets 1, because the shipped catalogue describes how this
			# pipeline runs -- except where the step declares `default_off`, which
			# is how a step can be ADDED to the catalogue without switching itself
			# on across every existing installation.
			"enabled": 1 if stage.required else (
				previous.enabled if previous else (0 if stage.default_off else 1)),
			"role": (previous.role if previous and previous.role else stage.role),
		})

	# every row this app did not ship, in the order it already had
	added = [row for row in existing if row.stage and row.stage not in shipped]
	for row in added:
		rows.append({
			"stage": row.stage,
			"stage_label": row.stage_label,
			"document_type": row.document_type,
			"kind": row.kind,
			"state": row.state,
			"action": row.action,
			"scoped": 1 if row.scoped else 0,
			"required": 1 if row.required else 0,
			"enabled": row.enabled,
			"role": row.role,
		})

	# Nothing to change is nothing to save. It saved on every migrate, so
	# Settings' `modified` moved on every deploy and "did the deploy touch my
	# configuration?" could not be answered by looking.
	if _stage_rows_as(existing) == _stage_rows_as(rows):
		return settings

	settings.set("approval_stages", [])
	for row in rows:
		settings.append("approval_stages", row)

	if save:
		settings.flags.ignore_permissions = True
		settings.flags.skip_approval_sync = True
		settings.save()
	return settings


#: The columns of an approval-stage row this app writes.
STAGE_ROW_FIELDS = ("stage", "stage_label", "document_type", "kind", "state", "action",
	"scoped", "required", "enabled", "role")


def _stage_rows_as(rows):
	"""Rows reduced to what seed_stages() writes, comparable across dict and doc."""
	def norm(value):
		if value is None:
			return ""
		if isinstance(value, bool):
			return int(value)
		return value
	return [tuple(norm((r.get(f) if hasattr(r, "get") else getattr(r, f, None)))
		for f in STAGE_ROW_FIELDS) for r in rows]


#: The Settings checkbox that decides whether a generated workflow carries
#: Frappe's own email alert.
NOTIFY_FIELD = "notify_approvers_by_email"


def email_alerts_on(settings=None):
	"""Does this site email approvers when something reaches their step?

	`build_workflows()` set `send_email_alert = 0` on all five workflows, every
	time, so no approver was ever notified of anything -- and the reason nobody
	noticed is that it was set before the chain was configurable, when the desk's
	awaiting-approval inbox was the only route in. On a site whose approvers live
	on the web screens, "nothing tells me there is work" is the whole experience.

	So it is a setting, and it is OFF unless a site says otherwise: turning it on
	for everybody on migrate would send mail from sites that have never sent any,
	about documents that have been sitting there for months.

	On, the workflow carries Frappe's own alert -- the notification with inline
	Approve and Reject links that `frappe/workflow` already sends, addressed by
	the transition's role. Not a notification layer of this app's own: a second
	implementation of "who should hear about this" is a second answer to it.

	`settings.get(...)` rather than an attribute, so a Settings document saved
	before this field existed reads as off instead of raising.
	"""
	settings = _settings_or_none() if settings is None else settings
	if not settings:
		return False
	return bool(settings.get(NOTIFY_FIELD))


def stage_rows(settings=_UNSET):
	"""{stage key: settings row} for every configured step.

	Every row with a key counts, including one this app never shipped. It used to
	filter against the catalogue, which is what made an added step invisible to
	everything downstream even before the seed deleted it.
	"""
	settings = _settings_or_none() if settings is _UNSET else settings
	rows = {}
	for row in (settings.get("approval_stages") if settings else None) or []:
		if (row.stage or "").strip():
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
	"""Approver rows configured for one stage, matched by the step's key."""
	settings = settings or _settings()
	stage = by_key(key, settings)
	if not stage:
		return []
	return [
		row for row in (settings.get("stage_approvers") or [])
		if row.get("stage") == stage.key
	]


def sync_approver_stages(settings):
	"""Key every approver row, and refresh the name it carries.

	Runs first in Settings.validate, which Frappe calls before its own mandatory
	and Select checks. A row that arrives with only a name -- written by an older
	form or an API caller -- is keyed by that name against THIS configuration,
	then every row's stage_label is rewritten from its key, so the stored name
	follows a rename instead of pinning the row to the old one.

	Returns the rows whose step is not in the chain, as [(idx, key or name)].
	"""
	stages = configured_stages(settings)
	keyed = {stage.key: stage for stage in stages}
	named = {stage.label: stage for stage in stages}
	orphans = []
	for row in settings.get("stage_approvers") or []:
		key = (row.get("stage") or "").strip()
		if not key and row.get("stage_label"):
			stage = named.get(row.get("stage_label"))
			if stage:
				key = stage.key
				row.stage = key
		stage = keyed.get(key)
		if stage:
			row.stage_label = stage.label
		else:
			orphans.append((row.get("idx"), key or row.get("stage_label") or ""))
	return orphans


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

	chain = [stage for stage in chain_for(document_type, settings) if is_enabled(stage, rows)]
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

	# Where each step leads comes from effective_chain(), not from this function's
	# own arithmetic. It used to be resolved here and again -- differently -- by
	# the screens, and that is precisely how a disabled step could vanish from the
	# workflow while a screen still wrote its state.
	leads_to = {
		step["key"]: step["next_state"]
		for step in effective_chain(settings, rows=rows, document_type=document_type)
	}

	for stage in chain:
		next_state = leads_to.get(stage.key, terminal_state)
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
	notify = email_alerts_on(settings)
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
			# Same plan, same flags: leave it alone. Saved unconditionally, every
			# migrate bumped `modified` on all five and wrote a Version row, so
			# nobody could tell a deploy that changed the chain from one that
			# did not.
			if _workflow_as(workflow) == _plan_as(plan, document_type, notify):
				continue
		else:
			workflow = frappe.new_doc("Workflow")
			workflow.workflow_name = name

		workflow.document_type = document_type
		workflow.workflow_state_field = "workflow_state"
		workflow.is_active = 1
		workflow.override_status = 0
		# WHETHER APPROVERS ARE EMAILED. Hardcoded to 0 here, on every workflow,
		# every time this ran -- so a site could name its approvers, generate its
		# chain, and still have nothing tell any of them there was work waiting.
		# Now a Settings checkbox, off unless a site turns it on, and read once
		# above so all five workflows agree. See email_alerts_on().
		workflow.send_email_alert = 1 if notify else 0

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


def _plan_as(plan, document_type, notify):
	"""A plan reduced to what build_workflows() writes onto a Workflow."""
	return (
		(document_type, "workflow_state", 1, 0, 1 if notify else 0),
		[(str(st["state"]), str(st["doc_status"]), st["allow_edit"] or "")
			for st in plan["states"]],
		[(t["state"], t["action"], t["next_state"], t["allowed"], t["condition"] or "",
			int(t["allow_self_approval"] or 0)) for t in plan["transitions"]],
	)


def _workflow_as(workflow):
	"""The same shape, read off a saved Workflow document."""
	return (
		(workflow.document_type, workflow.workflow_state_field, int(workflow.is_active or 0),
			int(workflow.override_status or 0), int(workflow.send_email_alert or 0)),
		[(str(st.state), str(st.doc_status), st.allow_edit or "")
			for st in workflow.get("states") or []],
		[(t.state, t.action, t.next_state, t.allowed, t.condition or "",
			int(t.allow_self_approval or 0)) for t in workflow.get("transitions") or []],
	)


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
		stage = by_key(approver.get("stage"), settings)
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


def steps_switched_off(before, after):
	"""Stage keys that were on and are now off, sorted.

	`before` is the stored configuration and `after` the one being saved, each a
	{stage key: on} mapping. Only the transition from on to off matters: a step
	already off strands nothing new, and checking those would mean one stray
	document in a retired state refuses every future Settings save -- locking
	somebody out of the screen they would use to fix it.

	A first save has no `before` at all, which arrives here as None.
	"""
	# A row DELETED from the table is switched off too -- its state leaves the
	# workflow exactly as a switched-off one does -- so a key that was on and is
	# now absent counts, not only one present and unticked.
	was = before or {}
	now = after or {}
	return sorted(key for key, on in was.items() if on and not now.get(key))


def busy_step_message(blocked):
	"""Why a step could not be switched off. `blocked` is [(label, state, count)]."""
	def one(label, count):
		return _("{0} cannot be switched off while {1} {2} waiting for it").format(
			frappe.bold(label),
			count,
			_("document is") if count == 1 else _("documents are"),
		)

	if len(blocked) == 1:
		label, _state, count = blocked[0]
		return one(label, count) + ". " + _(
			"Approve or reject them first, or leave the step on."
		)
	return (
		_("These steps cannot be switched off yet:")
		+ "\n"
		+ "\n".join("- " + one(label, count) for label, _state, count in blocked)
		+ "\n"
		+ _("Approve or reject them first, or leave those steps on.")
	)


def _waiting_in(document_type, state):
	"""How many documents of this type sit in this state right now."""
	if not state or not frappe.db.exists("DocType", document_type):
		return 0
	if not frappe.db.has_column(document_type, "workflow_state"):
		return 0
	return frappe.db.count(document_type, {"workflow_state": state})


def _enabled_map(settings):
	rows = (settings.get("approval_stages") if settings else None) or []
	out = {}
	for row in rows:
		key = (row.get("stage") or "").strip()
		if key:
			out[key] = 1 if (row.get("required") or row.get("enabled")) else 0
	return out


def validate_switching_off(settings):
	"""Refuse switching off a step that documents are waiting in.

	Removing a step removes its state from the generated workflow, so a document
	sitting there loses its way out. Advancing those documents automatically was
	the alternative and was rejected: it passes an approval nobody gave, and the
	audit trail then shows a step cleared with no approver.
	"""
	previous = _before_save(settings)
	going_off = steps_switched_off(
		_enabled_map(previous) if previous else None,
		_enabled_map(settings),
	)
	if not going_off:
		return

	# a deleted step is only in the stored configuration
	steps = {step["key"]: step for step in effective_chain(previous)} if previous else {}
	steps.update({step["key"]: step for step in effective_chain(settings)})
	blocked = []
	for key in going_off:
		step = steps.get(key)
		if not step:
			continue
		count = _waiting_in(step["document_type"], step["state"])
		if count:
			blocked.append((step["label"], step["state"], count))

	if blocked:
		frappe.throw(busy_step_message(blocked), title=_("Documents are waiting for this step"))


def _before_save(settings):
	"""The stored Settings a save is replacing, or None.

	`callable()` rather than `hasattr()`: a frappe._dict answers every attribute
	with None, so hasattr() is always true on one and the call then fails.
	"""
	getter = getattr(settings, "get_doc_before_save", None)
	return getter() if callable(getter) else None


def fix_stage_names(settings):
	"""Hold every step's internal names still, whatever the save asked for.

	A document carries its workflow state BY NAME, so a step whose state is
	renamed strands every document waiting in it -- which is what happened on
	Altura, where relabelling the Actuals "FM" step in the grid meant typing new
	words into its "Waits In" and "Action" columns too, and the regenerated
	workflow no longer held the state twenty actuals were sitting in. A step is
	renamed through its label, which the screens show; these two are not names
	anybody reads on a screen.

	    catalogue rows   take the catalogue's state, action, kind, document and
	                     flags, by key. seed_stages() does the same on migrate;
	                     doing it here too means an API write cannot slip a
	                     rename in between deploys.
	    added rows       keep the state and action they were given the first
	                     time they were saved. A new one is given a key, a state
	                     and an action now, derived once from its label and never
	                     re-derived: renaming it later changes only the label.

	The grid shows both columns read-only; this is what makes that true.
	"""
	shipped = {stage.key: stage for stage in CATALOGUE}
	previous = _before_save(settings)
	stored = {}
	for row in ((previous.get("approval_stages") if previous else None) or []):
		if (row.get("stage") or "").strip():
			stored[row.get("stage").strip()] = row
	rows = settings.get("approval_stages") or []
	keys = {(r.get("stage") or "").strip() for r in rows} | set(shipped)

	for row in rows:
		key = (row.get("stage") or "").strip()
		stage = shipped.get(key)
		if stage:
			row.document_type = stage.document_type
			row.kind = stage.kind
			row.state = stage.state
			row.action = stage.action
			row.scoped = 1 if stage.scoped else 0
			row.required = 1 if stage.required else 0
			continue
		if key and key in stored:
			old = stored[key]
			row.state = old.get("state") or row.get("state")
			row.action = old.get("action") or row.get("action")
			continue
		# a step being added in this save
		if not key:
			key = _new_stage_key(row.get("stage_label") or row.get("document_type"), keys)
			row.stage = key
			keys.add(key)
		row.kind = row.get("kind") or "Approval"
		if not row.get("state"):
			row.state = _new_stage_state(row, rows)
		if not row.get("action"):
			row.action = "Approve" if row.kind == "Approval" else "Submit for Approval"


def _new_stage_key(label, taken):
	"""`custom_<label>`, made unique. Only ever called once per row."""
	import re

	base = "custom_" + (re.sub(r"[^a-z0-9]+", "_", (label or "").lower()).strip("_") or "step")
	key, n = base, 2
	while key in taken:
		key, n = "%s_%d" % (base, n), n + 1
	return key


def _new_stage_state(row, rows):
	"""`Pending <the label's last part>`, unique within the row's document type."""
	label = row.get("stage_label") or ""
	tail = label.split(": ", 1)[1] if ": " in label else label
	base = "Pending " + (tail.strip() or "Step")
	ends = CHAIN_ENDS.get(row.get("document_type")) or {}
	taken = {r.get("state") for r in rows
		if r is not row and r.get("document_type") == row.get("document_type")}
	taken |= {"Draft", ends.get("reject"), (ends.get("terminal") or (None,))[0]}
	state, n = base, 2
	while state in taken:
		state, n = "%s %d" % (base, n), n + 1
	return state


def validate_configuration(settings):
	"""Refuse a configuration that would strand a document.

	A farm-scoped stage with per-farm approvers generates one conditional
	transition per farm. A farm nobody approves for has no transition at all, so
	its documents would sit in that state with no way out. Better to say so on
	save than to discover it when a plan cannot be approved.

	And two steps may not share a name. Approver rows are keyed by step now, but
	every screen and the approver picker show the name, and a row written with
	only a name is keyed by it -- two steps sharing one cannot be told apart by
	the person choosing. Cheap to refuse here; impossible to diagnose later.

	And every approver row must name a step that exists. See
	sync_approver_stages().
	"""
	clash = duplicate_stage_labels(
		[row.stage_label for row in (settings.get("approval_stages") or [])]
	)
	if clash:
		frappe.throw(
			_("More than one approval step is called {0}. Two steps sharing a name cannot be told apart when choosing who takes each — give each step its own.").format(
				frappe.bold(clash)
			),
			title=_("Two steps with the same name"),
		)

	# Before anything reads a state: the internal names are not the save's to
	# change. See fix_stage_names().
	fix_stage_names(settings)

	# After the names are known to be distinct: a row that arrives with only a
	# name is keyed by it.
	orphans = sync_approver_stages(settings)
	# Refused on a person's save, never on the app's own. seed_stages() and
	# capabilities.seed() save Settings on migrate; refusing there would take the
	# deploy down over a row key_stage_approvers_by_stage deliberately left for a
	# person to pick again.
	if orphans and not (getattr(settings, "flags", None) or {}).get("skip_approval_sync"):
		frappe.throw(
			_("Stage Approvers row {0} names a step that is not in the approval chain ({1}). Pick the step again, or remove the row.").format(
				orphans[0][0], frappe.bold(orphans[0][1] or _("none")),
			),
			title=_("Approver for a step that does not exist"),
		)

	# A step being switched off with documents waiting in it is refused before
	# anything else is checked, because it is the one failure that would strand
	# work rather than merely misconfigure it.
	validate_switching_off(settings)

	rows = stage_rows(settings)
	# Upande Core's Farm, unguarded: hooks.py requires that app, so the doctype is
	# there by definition. `disabled` is not a field Core ships -- respected where
	# a site has added one, ignored where none has.
	#
	# Narrowed to the farms in use, because this check refuses a save that would
	# leave a farm with nobody to approve for it. Core's list is every farm on the
	# site, so without narrowing, a project working four of sixteen would be made
	# to name approvers for twelve it never plans against -- including, on
	# kaitet.local, one called `cheptiret` belonging to a company called `dummy`.
	from work_management.api import config

	filters = {"disabled": 0} if frappe.db.has_column("Farm", "disabled") else {}
	farms = config.farms_in_use(
		frappe.get_all("Farm", filters=filters, pluck="name"),
		[row.farm for row in (settings.get("farms") or []) if row.farm],
		restrict=bool(settings.get("farms_restrict")),
	)
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
	# The capability grid is seeded beside the stages, and for the same reason:
	# an empty table tells a reader nothing about what can be granted.
	from work_management import capabilities

	capabilities.seed()
	frappe.clear_cache(doctype="Work Management Settings")
	build_workflows()
	# the picker that names who takes a step must offer the steps that exist
	apply_stage_picker_options()
	frappe.db.commit()
