# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""What a recorded worker-day is worth, decided in one place.

A day-row's `amount` is `qty x unit value x holiday multiplier` for a row that
counts in payroll, and 0 for one that does not. Until this module that rule
lived only in `act_save`, so any other way of saving the document -- the desk
form above all -- could change a quantity and leave the money where it was.
WMAC-02035 on Altura is the case: 14 rows edited from 1 to 0 in the desk while
the document was pending approval, each still paying 400.

So the controller re-prices every row and re-sums the document on every save
(`price`), and a document that has left Draft/Rejected refuses a change to its
day-rows (`refuse_row_edits`). Corrections go back through reject -> resubmit.

The unit value is the document's `rate`, snapped to the task's daily wage when
the rate was stored with too few decimals -- the same snap `act_save` has always
applied, moved here so the two cannot disagree (`unit_value`).
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

ACTUALS_DT = "Work Management Actuals"
ROW_DT = "Work Actuals Employee"

# The fields of a day-row that decide money. A change to any of them on a
# document already in the approval chain is refused. `note` and the review tick
# are left editable: they explain a day, they do not price it.
MONEY_FIELDS = ("employee", "work_date", "actual_quantity", "hours",
	"count_in_payroll", "amount", "holiday_multiplier")

# The flag `act_save` sets when an approver edits a pending entry in place from
# the actuals screen. That path re-prices from the grid and is the chain's own
# feature; the desk form is not.
APPROVER_EDIT_FLAG = "wm_approver_edit"


def unit_value(rate, planner=None):
	"""The money one unit of work is worth on a plan.

	`rate` as stored, unless rate x daily_target lands within 1% of the task's
	daily wage without hitting it -- a rate rounded to 2dp -- in which case the
	wage / daily_target. Rates are stored at 6dp since 2026-08-04, so this
	normally returns `rate` unchanged.
	"""
	rate = flt(rate)
	if not planner or rate <= 0:
		return rate
	pinfo = frappe.db.get_value("Work Management Planner", planner,
		["daily_target", "task", "from_date"], as_dict=True)
	if not pinfo or flt(pinfo.daily_target) <= 0:
		return rate
	day_wage = rate * flt(pinfo.daily_target)
	snap_wage = 0
	if pinfo.task:
		wrow = frappe.db.sql("""
			SELECT daily_wage_basis b FROM `tabWork Task Rate`
			WHERE task = %(t)s AND derived = 1
			  AND valid_from <= %(d)s
			  AND (valid_to IS NULL OR valid_to >= %(d)s)
			ORDER BY valid_from DESC LIMIT 1
		""", {"t": pinfo.task, "d": pinfo.from_date or frappe.utils.today()}, as_dict=True)
		if wrow and flt(wrow[0].b) > 0:
			snap_wage = flt(wrow[0].b)
	if not snap_wage:
		snap_wage = 340.0
	if abs(day_wage - snap_wage) <= snap_wage * 0.01 and abs(day_wage - snap_wage) > 0.001:
		return snap_wage / flt(pinfo.daily_target)
	return rate


def row_amount(qty, unit, in_payroll, multiplier):
	"""qty x unit x multiplier, to the cent; 0 for a row outside payroll.

	A row with no multiplier stored was written before public-holiday pay
	existed and is priced at x1, the rule it was written under.
	"""
	if not cint(in_payroll):
		return 0
	return round(flt(qty) * flt(unit) * (flt(multiplier) or 1), 2)


def price(doc):
	"""Re-price every unpaid day-row and re-sum the document's totals.

	A row already paid keeps the amount it was paid at; its quantity is guarded
	in `refuse_row_edits`.
	"""
	planner = doc.planner_request or (doc.assignment and frappe.db.get_value(
		"Work Management Assigner", doc.assignment, "planner_request"))
	unit = unit_value(doc.rate, planner)
	total_qty = total_pay = tw_qty = sal_qty = 0
	people = set()
	pay_people = set()
	for row in doc.get("employees") or []:
		qty = flt(row.actual_quantity)
		if not cint(row.paid):
			row.amount = row_amount(qty, unit, row.count_in_payroll, row.holiday_multiplier)
		total_qty += qty
		if qty > 0:
			people.add(row.employee)
		if cint(row.count_in_payroll):
			total_pay += flt(row.amount)
			tw_qty += qty
			if qty > 0:
				pay_people.add(row.employee)
		else:
			sal_qty += qty
	doc.total_actual_qty = total_qty
	doc.custom_tw_qty = tw_qty
	doc.custom_salaried_qty = sal_qty
	doc.actual_people = len(people)
	doc.payroll_people = len(pay_people)
	doc.total_payment = total_pay
	doc.cost_variance = total_pay - flt(doc.planned_cost)


def editable_states():
	"""The states a document's day-rows may still change in: the Submit step's
	own state (Draft) and Rejected."""
	states = {"Draft", "Rejected"}
	try:
		from work_management import approvals

		ends = approvals.pipeline_states(document_type=ACTUALS_DT)
		for key in ("draft", "reject"):
			if ends.get(key):
				states.add(ends[key])
	except Exception:
		pass
	return states


NUMERIC_FIELDS = ("actual_quantity", "hours", "count_in_payroll", "holiday_multiplier")


def _row_key(row):
	# normalised: the desk sends 1 where the database holds 1.0, and a date as text
	return tuple(
		flt(row.get(f)) if f in NUMERIC_FIELDS else str(row.get(f) or "")
		for f in MONEY_FIELDS if f != "amount")


def refuse_row_edits(doc):
	"""Refuse a change to day-rows once the document is in the approval chain,
	and a change to a paid row's quantity at any time."""
	if doc.is_new():
		return
	before = doc.get_doc_before_save()
	if not before:
		return
	old_rows = {r.name: r for r in before.get("employees") or []}
	new_rows = {r.name: r for r in doc.get("employees") or [] if r.name}

	for name, old in old_rows.items():
		new = new_rows.get(name)
		if cint(old.paid) and (not new or flt(new.actual_quantity) != flt(old.actual_quantity)):
			frappe.throw(_("Row {0} ({1}, {2}) has been paid; its quantity cannot change.")
				.format(old.idx, old.employee, old.work_date), title=_("Paid row"))

	if before.workflow_state in editable_states() or doc.flags.get(APPROVER_EDIT_FLAG):
		return

	changed = set(old_rows) != set(new_rows) or any(
		r.is_new() or not r.name for r in doc.get("employees") or [])
	if not changed:
		for name, old in old_rows.items():
			if _row_key(old) != _row_key(new_rows[name]):
				changed = True
				break
	if changed:
		frappe.throw(_("{0} is {1}: its day-rows cannot be edited. Reject it and correct it "
			"before it is resubmitted.").format(doc.name, before.workflow_state),
			title=_("Work record is in approval"))
