# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Cap arithmetic for the Work Management Master Plan.

A master plan line budgets an activity twice over: a quantity of work and the
money it may cost. A weekly plan is refused when either ceiling would be
crossed -- whichever is hit first -- because a rate change can blow the budget
without the quantity moving at all.

Mirrored inline in server_scripts/wm_masterplan.py and wm_planner.py: Frappe's
script sandbox forbids imports, so the two must be kept in step.
"""

#: Money and quantity comparisons tolerate this much, matching wm_payment.
TOLERANCE = 0.005


def line_headroom(work_qty, cost, planned_qty, planned_cost):
	"""What is left on one master plan line."""
	work_qty = float(work_qty or 0)
	cost = float(cost or 0)
	planned_qty = float(planned_qty or 0)
	planned_cost = float(planned_cost or 0)

	remaining_qty = max(0.0, work_qty - planned_qty)
	remaining_cost = max(0.0, cost - planned_cost)
	return {
		"remaining_qty": remaining_qty,
		"remaining_cost": remaining_cost,
		"qty_pct": (planned_qty / work_qty * 100) if work_qty else 100.0,
		"cost_pct": (planned_cost / cost * 100) if cost else 100.0,
		# a line with no budget at all is exhausted, not infinitely available
		"exhausted": remaining_qty <= TOLERANCE or remaining_cost <= TOLERANCE,
	}


def check_plan_allowed(work_qty, cost, planned_qty, planned_cost, new_qty, new_cost):
	"""May a plan for ``new_qty`` / ``new_cost`` be raised against this line?

	Returns ``(allowed, reason)``. The reason names the ceiling, what is
	already committed and what is left -- a bare refusal is useless to whoever
	hit it.
	"""
	h = line_headroom(work_qty, cost, planned_qty, planned_cost)
	new_qty = float(new_qty or 0)
	new_cost = float(new_cost or 0)

	if new_qty > h["remaining_qty"] + TOLERANCE:
		return False, (
			"Over the budgeted quantity: {0:,.2f} left of {1:,.2f}, "
			"this plan asks for {2:,.2f}.".format(h["remaining_qty"], float(work_qty or 0), new_qty)
		)
	if new_cost > h["remaining_cost"] + TOLERANCE:
		return False, (
			"Over the budgeted cost: KES {0:,.2f} left of {1:,.2f}, "
			"this plan costs {2:,.2f}.".format(h["remaining_cost"], float(cost or 0), new_cost)
		)
	return True, None
