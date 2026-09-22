# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""The consultant gate, when there is no consultant step.

Every activity on a master plan carries `consultant_state`. A consultant
settles each line -- OK, Edit work, Rejected -- and the planner only offers
activities marked OK. That is the control that works, and it is deliberately
not the approval chain: `approvals.py` says so where the dead `Gate` kind used
to be.

But the line's default is `Pending`, and the only things that ever move it off
`Pending` are the consultant's own actions. So on a site that switches
`masterplan_consultant` OFF, nothing ever settles a line:

  * `gm_approve` counts lines marked OK before it will approve, finds none, and
    refuses with *"Every activity was rejected, so there is nothing to
    approve"* -- about a plan on which nothing was rejected at all.
  * a plan approved from the desk instead (which is the workaround Altura was
    using) reaches `Approved` with every line still `Pending`, so the planner's
    `budgets` counts 0 activities, the task picker is empty, and `headroom`
    finds nothing to draw against. A farm with an approved budget can plan no
    work.

Altura hit both on 2026-09-22 and twenty rows were repaired by hand in System
Console. This is that repair, made a rule.

**Switching the step off means the gate is satisfied, not that it is unmet.**
A project that does not review activities individually has not thereby refused
them all. So the rows are stamped OK -- at source, once, where they are
written -- rather than every reader learning to treat `Pending` as OK when a
setting says so. One approach, in one place:

  * `settle_doc()` runs on validate, so a master plan saved from the desk or
    from the screen settles as it saves;
  * `settle()` runs after the writes that bypass the document (the screens use
    `frappe.db.set_value` throughout);
  * the patch does exactly the same thing to the rows already on a site.

`consultant_by` is left empty on purpose. Nobody decided these lines, and
stamping a name would put a decision in the audit trail that no person made.
The plan's comment history records that they were settled and why.
"""

import frappe

#: The catalogue key of the step this gate belongs to.
STAGE = "masterplan_consultant"

#: What a line says before anybody looks at it, and what it says once somebody
#: has approved it. The two ends of the one transition this module performs.
PENDING = "Pending"
SETTLED = "OK"

ACTIVITY = "Work Management Master Plan Activity"
PLAN = "Work Management Master Plan"

#: What goes on the plan's history the first time its lines are settled this way.
NOTE = ("Consultant review is switched off for this project, so {0} activit{1} "
	"settled automatically. Nobody reviewed them individually; switching the "
	"step back on in Work Management Settings restores the line-by-line review.")


def is_on(settings=None):
	"""Is the consultant step part of this installation's chain?

	Read through `approvals`, so there is one answer to "is this step enabled"
	and it is the same one the workflow generator and the screens get. A site
	mid-install, with no Settings document yet, falls back to the shipped
	catalogue -- where the step is on -- and so changes nothing.
	"""
	from work_management import approvals

	# Resolved ONCE and passed to both calls. `stage_rows()` distinguishes "you
	# did not say" from "there is no configuration" by its own sentinel, so a
	# literal None means no rows -- and a stage with no row reads as ENABLED,
	# which is the opposite of what a caller passing None meant.
	settings = settings if settings is not None else approvals._settings_or_none()
	stage = approvals.by_key(STAGE, settings)
	if not stage:
		# The step has been removed from the chain outright, which is a stronger
		# statement than switching it off. Nothing routes there and nothing
		# should wait for it.
		return False
	return bool(approvals.is_enabled(stage, approvals.stage_rows(settings)))


def settle_doc(doc, method=None):
	"""Stamp this master plan's pending lines, in memory, before it saves.

	A `validate` hook, so it covers the desk form as well as the screen -- and
	the desk form is what Altura was actually using while this was broken.
	Returns how many rows it changed, for the patch and the tests.
	"""
	if is_on():
		return 0
	changed = 0
	for row in doc.get("activities") or []:
		if (row.consultant_state or PENDING) == PENDING:
			row.consultant_state = SETTLED
			changed += 1
	return changed


def settle(plan, settings=None):
	"""Stamp one saved plan's pending lines. Idempotent.

	For the callers that write with `frappe.db.set_value` and so never build a
	document for `settle_doc()` to see -- which is every approval action on the
	master plan screen.
	"""
	if not plan or is_on(settings):
		return 0
	names = frappe.db.get_all(ACTIVITY,
		filters={"parent": plan, "parenttype": PLAN, "consultant_state": PENDING},
		pluck="name")
	for name in names:
		frappe.db.set_value(ACTIVITY, name, "consultant_state", SETTLED,
			update_modified=False)
	return len(names)


def settle_and_note(plan, settings=None):
	"""`settle()`, and say so on the plan's own history when it did anything.

	The note is the audit trail's answer to "who approved these lines" -- nobody
	did, and the record says which setting is why.
	"""
	changed = settle(plan, settings=settings)
	if changed:
		try:
			frappe.get_doc(PLAN, plan).add_comment(
				"Comment", NOTE.format(changed, "y was" if changed == 1 else "ies were"))
		except Exception:
			# A comment is the nice half. Failing to write one must not undo the
			# repair, which is the half a farm's whole week depends on.
			pass
	return changed


def plans_needing_settling(limit=None):
	"""Plans with a pending line while the step is off. For the patch.

	Ordered, and read as plan names rather than row names, so the repair can
	report per plan and write one comment each.
	"""
	if is_on():
		return []
	rows = frappe.db.get_all(ACTIVITY,
		filters={"parenttype": PLAN, "consultant_state": PENDING},
		fields=["parent"], group_by="parent", order_by="parent asc",
		limit_page_length=limit or 0)
	return [row.parent for row in rows if row.parent]
