# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""A request's target may be raised after approval — by an approver, upward only.

`quantity` carries `allow_on_submit`, because raising a target mid-flight is the
whole point of the `raise_target` action: a week approved for 500 that the crew
can clearly finish at 700 should not need a second trip through the chain for
work already under way, and editing the request instead sends an approved plan
back to Draft and throws its approval away.

But `allow_on_submit` is a property of the FIELD, not of the action. It opens the
desk form too, and there the action's gate does not run — so an approved target
would be editable by anybody holding write permission, in either direction, with
nothing recorded. That is the hole this closes: the rule lives on the document,
so it is true of every path that reaches it.

Two things are refused:

**Downward.** The actuals cap and the completion gate both read this figure live
at save time. Cut it below what is already recorded and recorded work exceeds its
own target, while the plan can never reach 100% and so can never be submitted.
`check_cut_allowed()` refuses the same move on a master plan line for the same
reason. Upward is always safe: nothing already recorded stops being valid.

**By anyone who could not have approved it.** Raising your own approved target is
approving your own request, one step later and with nobody looking. So it takes
one of the roles the configured chain names for this document type, or the
general manager, or System Manager as the usual unstick-the-pipeline bypass.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from work_management import approvals

#: What the target may differ by before it counts as changed. Matches the
#: tolerance the master plan's cap arithmetic uses.
TOLERANCE = 0.005


def approver_roles():
	"""The roles the configured chain lets decide a Planner request.

	Read from the chain rather than named here, so a site that adds an approval
	step gets its holders too and one that renames a role does not have to come
	back and edit this.
	"""
	return sorted({
		step["role"] for step in approvals.effective_chain(document_type="Work Management Planner")
		if step.get("kind") == "Approval" and step.get("on") and step.get("role")
	})


def may_raise_target(user_roles, user=None):
	"""May somebody holding `user_roles` raise an approved request's target?

	Pure apart from its inputs, so the rule can be tested without a site. The
	general manager is a bypass HERE — unlike a chain step, where GM taking the HR
	Head's decision would erase the separation the chain expresses. This is not a
	step: it is a spend increase managers agree offline, and the GM is exactly who
	agrees it.
	"""
	if user == "Administrator":
		return True
	held = set(user_roles or [])
	if "System Manager" in held or "General Manager" in held:
		return True
	return bool(held & set(approver_roles()))


class WorkManagementPlanner(Document):
	def on_update_after_submit(self):
		"""Guard the one field `allow_on_submit` makes editable after approval."""
		before = self.get_doc_before_save()
		if not before:
			return
		was = frappe.utils.flt(before.quantity)
		now = frappe.utils.flt(self.quantity)
		if abs(now - was) <= TOLERANCE:
			return
		if now < was - TOLERANCE:
			frappe.throw(
				_(
					"An approved request's target can be raised, not lowered: this one "
					"is at {0} and {1} is less. Recorded work reads the target live, so "
					"lowering it would put work already done over its own target and "
					"leave the plan unable to complete."
				).format(was, now),
				title=_("Target cannot be lowered"),
			)
		if not may_raise_target(frappe.get_roles(), frappe.session.user):
			roles = approver_roles()
			frappe.throw(
				_(
					"Raising an approved target is the approver's decision. {0}You hold "
					"none of them."
				).format(
					_("Only {0} or the general manager may take it. ").format(", ".join(roles))
					if roles
					else ""
				),
				title=_("Not yours to raise"),
			)
