# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Settle master plan activities stranded by a switched-off consultant step.

On a site with `masterplan_consultant` off, nothing ever moves an activity off
`consultant_state = 'Pending'` -- so an approved budget offers the planner no
activities, its task picker is empty, and `headroom` finds nothing to draw
against. Altura hit this on 2026-09-22 and twenty rows were repaired by hand in
System Console; this is the same repair, by the same rule, for any site.

The rule lives in `work_management/consultant.py` and is applied from three
places now -- a validate hook, and the two approval actions that write past the
document -- so this patch only has to catch what is already there.

Idempotent twice over: it no-ops entirely where the step is ON, and where it is
off it only touches rows still saying `Pending`. Running it again does nothing,
which is what makes it safe to leave in patches.txt.
"""

import frappe

from work_management import consultant


def execute():
	if not frappe.db.exists("DocType", consultant.ACTIVITY):
		return
	if consultant.is_on():
		# The step is part of this chain, so a Pending line is a line waiting for
		# somebody -- exactly what it should say. Repairing it here would clear a
		# review nobody has done.
		return

	plans = consultant.plans_needing_settling()
	if not plans:
		return

	rows = 0
	for plan in plans:
		rows += consultant.settle_and_note(plan)
	frappe.db.commit()
	print("settled %d activit%s across %d master plan%s with no consultant step"
		% (rows, "y" if rows == 1 else "ies", len(plans), "" if len(plans) == 1 else "s"))
