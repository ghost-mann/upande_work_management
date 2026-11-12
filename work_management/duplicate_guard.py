"""One worker, one day, one task -- for saves that do not come through the screens.

The Actuals screen refuses a second payable row for a worker on a date (see
wmg_guard_err in api/actuals.py). The desk form, data import and any other
caller of doc.save() never pass through that endpoint, so the same rule is
held here, on validate, where every save lands.
"""

import frappe
from frappe import _


def clashes(doc):
	"""[(employee, date, other_actuals)] for payable rows on `doc` that another
	live actuals record already holds."""
	pairs = {}
	for row in doc.get("employees") or []:
		if not (row.employee and row.work_date):
			continue
		if (row.actual_quantity or 0) <= 0 and (row.amount or 0) <= 0:
			continue
		pairs[(row.employee, str(row.work_date))] = 1
	if not pairs:
		return []
	emps = tuple({p[0] for p in pairs})
	days = tuple({p[1] for p in pairs})
	found = []
	seen = set()
	for r in frappe.db.sql(
		"""
		SELECT we.employee, we.work_date, ac.name
		FROM `tabWork Actuals Employee` we
		INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
		WHERE we.parenttype = 'Work Management Actuals'
		  AND IFNULL(ac.workflow_state, '') != 'Rejected' AND ac.docstatus < 2
		  AND (IFNULL(we.actual_quantity, 0) > 0 OR IFNULL(we.amount, 0) > 0)
		  AND ac.name != %s AND we.employee IN %s AND we.work_date IN %s
		""",
		(doc.name or "__new__", emps, days),
	):
		key = (r[0], str(r[1]))
		if key in pairs and key not in seen:
			seen.add(key)
			found.append((r[0], str(r[1]), r[2]))
	return found


def recompute(doc):
	"""Desk and REST saves never re-derived the amount, so a typed amount or an
	edited quantity went to payroll as entered. Each payable row is amount =
	quantity x rate, to the cent; a value within 1% is kept, so the Actuals
	screen's wage rounding survives a later desk save."""
	rate = float(doc.get("rate") or 0)
	total_qty = total_pay = 0.0
	for row in doc.get("employees") or []:
		qty = float(row.actual_quantity or 0)
		if qty < 0:
			frappe.throw(_("A quantity cannot be negative ({0} on {1}).").format(row.employee, row.work_date))
		want = round(qty * rate, 2) if row.count_in_payroll else 0.0
		have = float(row.amount or 0)
		if abs(have - want) > max(0.01, 0.01 * want):
			row.amount = want
		total_qty += qty
		total_pay += float(row.amount or 0)
	doc.total_actual_qty = total_qty
	doc.total_payment = round(total_pay, 2)


def dates_err(doc):
	"""Rows dated outside the record's own dates, or after today."""
	today = str(frappe.utils.today())
	f, t = str(doc.get("from_date") or ""), str(doc.get("to_date") or "")
	bad = []
	for row in doc.get("employees") or []:
		d = str(row.work_date or "")
		if not d:
			continue
		if d > today or (f and d < f) or (t and d > t):
			bad.append("{0} on {1}".format(row.employee, d))
	return bad


def locked_by(doc):
	"""The payroll check that has locked this record's dates on its farm, if any."""
	if not frappe.db.exists("DocType", "Work Management Payroll Check"):
		return None
	days = sorted({str(r.work_date) for r in doc.get("employees") or [] if r.work_date})
	if not days or not doc.get("farm"):
		return None
	for name, f, t in frappe.db.sql(
		"""
		SELECT pc.name, pc.period_from, pc.period_to FROM `tabWork Management Payroll Check` pc
		WHERE pc.status NOT IN ('Cancelled', 'Sent') AND pc.period_from <= %(t)s AND pc.period_to >= %(f)s
		  AND (pc.status IN ('HR Review', 'GM Review', 'Approved')
		       OR EXISTS (SELECT 1 FROM `tabWork Management Payroll Check Farm` cf
		                  WHERE cf.parent = pc.name AND cf.farm = %(farm)s AND cf.status = 'Approved'))
		""",
		{"f": days[0], "t": days[-1], "farm": doc.farm},
	):
		if any(str(f) <= d <= str(t) for d in days):
			return name
	return None


def validate_actuals(doc, method=None):
	"""Refuse a save that would pay one worker twice for one day; on desk and REST
	saves also re-derive amounts, refuse impossible dates, and respect a payroll
	check's lock. Saves from the Actuals screen (flags.wm_screen) have already
	been through all of that, with the screen's own wage rounding."""
	if (doc.get("workflow_state") or "") == "Rejected" or doc.docstatus == 2:
		return
	if not doc.flags.get("wm_screen"):
		recompute(doc)
		bad = dates_err(doc)
		if bad:
			frappe.throw(_("Work dated after today or outside this record's dates: {0}").format(", ".join(bad[:8])))
		lock = locked_by(doc)
		if lock:
			frappe.throw(_("These dates are locked by payroll check {0}. Ask HR or the GM to send it back first.").format(lock))
	desk_step_check(doc)
	found = clashes(doc)
	if found:
		lines = ", ".join("{0} on {1} ({2})".format(e, d, other) for e, d, other in found[:8])
		frappe.throw(
			_("One worker, one day, one task. Already recorded elsewhere: {0}").format(lines),
			title=_("Worker already recorded for that day"),
		)


# Which approver field each step's approval fills, keyed by the state it leaves.
STEP_FIELDS = {
	"Pending Farm Manager": ("fm_approved_by", "fm_approval_date"),
	"Pending HR Head": ("hr_approved_by", "hr_approval_date"),
	"Pending GM": ("gm_approved_by", "gm_approval_date"),
}


def _desk_transition(doc):
	"""(old_state, new_state) when this save moves the workflow outside the screens."""
	if doc.flags.get("wm_screen"):
		return None
	before = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
	if not before:
		return None
	old, new = before.get("workflow_state"), doc.get("workflow_state")
	if old == new or old not in STEP_FIELDS:
		return None
	return old, new


def desk_step_check(doc):
	"""Approving on the desk form follows the same two-pairs-of-eyes rule as the
	screens: not the person who entered the record, nor whoever took the step
	before. A System Manager is the break-glass, as on the screens."""
	moved = _desk_transition(doc)
	if not moved or moved[1] == "Rejected":
		return
	me = frappe.session.user
	others = {doc.get("entered_by") or doc.get("owner")}
	if moved[0] == "Pending HR Head":
		others.add(doc.get("fm_approved_by"))
	if moved[0] == "Pending GM":
		others.add(doc.get("hr_approved_by"))
	if me in others and "System Manager" not in frappe.get_roles():
		frappe.throw(_("You entered this record or took the step before, so somebody else must approve it."))


def on_actuals_update(doc, method=None):
	"""Record who took a step on the desk. The screens always wrote
	fm/hr/gm_approved_by; the desk workflow buttons never did, which is how
	161 records reached CONFIRMED since 1 Oct with only a GM on them."""
	moved = _desk_transition(doc)
	if not moved or moved[1] == "Rejected":
		return
	who_field, date_field = STEP_FIELDS[moved[0]]
	if doc.meta.get_field(who_field):
		doc.db_set(who_field, frappe.session.user, update_modified=False)
	if doc.meta.get_field(date_field):
		doc.db_set(date_field, frappe.utils.today(), update_modified=False)
