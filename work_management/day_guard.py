# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""One worker, one date: the captures that cannot both be paid.

On 2026-11-05 a back-fill of 30 Oct on Altura created CONFIRMED actuals that paid
the same people twice for that date -- Michael Njoroge Maina 3 x 8 h on one task,
five Bed Making workers twice in WMAC-01956 and WMAC-01972. The screen had a
duplicate check, but it only looked at OTHER assignments, it travelled inside
the attendance-override dialog, and anybody could click through it.

So the rule now lives here, once, and is enforced wherever a day-row is
written or a document moves towards payment:

* **Refused -- the same work twice.** A day-row for an employee and `work_date`
  that already has a row, in another counted document, on the **same
  assignment** or on the **same task and block**. Also a worker entered twice on
  one date inside one document. No override: one of the two is wrong.
* **Refused -- more hours than the day holds.** An employee's hour-based rows
  (the plan's UOM is Hours, so the quantity IS the hours) on one date may not
  add up to more than `max_hours_per_day` in Settings, 8 unless a site says
  otherwise, across every counted document.
* **Flagged, not refused -- more than one day's standard.** An 8 h task and a
  bed made on the same date are each a full day's target. That can be a real
  split day, so it goes through, and Payment -> Discrepancies lists it
  (`standard_share`).

"Counted" is every document the pipeline means to pay: Draft, every approval
step and the terminal state -- paid rows included. Rejected is not counted: a
rejected document is checked again when it is resubmitted (the screen rewrites
its rows, and approval re-checks), so a correction captured in a new document
is not blocked by the rejected one it replaces.

Where it is enforced:

    Actuals controller validate    screen save, approver edit-in-place, desk,
                                   Data Import -- every path that writes rows
    act_submit                     the same check before anything is written,
                                   so the screen gets a sentence, not a trace
    act_approve (single and bulk)  approvals write state with db.set_value and
    act_close_confirm              never run validate, so they ask again here

The core (`conflicts`, `standard_share`) is pure: rows in, findings out.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from work_management import split_day

ACTUALS_DT = "Work Management Actuals"
ROW_DT = "Work Actuals Employee"
SETTINGS = "Work Management Settings"

#: Altura's ceiling and the default for a site that has not set one.
DEFAULT_MAX_HOURS = 8.0

#: Matches the tolerance every money and hours comparison in this app uses.
TOLERANCE = 0.005

#: How many refusals one message lists before saying "and N more".
LIST_AT_MOST = 8

DUPLICATE = "duplicate"
HOURS = "hours"


# ------------------------------------------------------------------ the rule


def is_hourly(uom):
	return str(uom or "").strip().lower() in split_day.HOURLY_UOMS


def _same_work(a, b):
	"""Same assignment, or same task and block. Returns the reason, or None."""
	if a.get("assignment") and a.get("assignment") == b.get("assignment"):
		return "same assignment"
	if a.get("task") and a.get("task") == b.get("task") and \
			(a.get("block") or "") == (b.get("block") or ""):
		return "same task and block"
	return None


def _key(row):
	return (str(row.get("employee") or ""), str(row.get("work_date") or "")[:10])


def _doc_label(row):
	label = str(row.get("doc") or "")
	bits = [b for b in (row.get("state"), "paid" if cint(row.get("paid")) else None) if b]
	return label + (" (" + ", ".join(bits) + ")" if bits else "")


def conflicts(new_rows, others, max_hours=DEFAULT_MAX_HOURS):
	"""What refuses `new_rows`, given the counted rows of other documents.

	Each row is a dict: employee, employee_name, work_date, qty, assignment,
	task, block, uom, doc -- plus state and paid on `others`. Rows with no
	quantity are ignored on both sides. Returns a list of findings
	``{employee, employee_name, work_date, kind, docs, message}``, one per
	employee, date and kind.
	"""
	max_hours = flt(max_hours) or DEFAULT_MAX_HOURS
	new_rows = [r for r in new_rows or [] if flt(r.get("qty")) > 0]
	others = [r for r in others or [] if flt(r.get("qty")) > 0]
	by_key = {}
	for r in others:
		by_key.setdefault(_key(r), []).append(r)

	found = []
	seen = set()

	def add(row, kind, docs, message):
		k = _key(row) + (kind,)
		if k in seen:
			return
		seen.add(k)
		found.append({
			"employee": row.get("employee"),
			"employee_name": row.get("employee_name") or row.get("employee"),
			"work_date": _key(row)[1],
			"kind": kind,
			"docs": docs,
			"message": message,
		})

	# the same worker twice on one date inside the document being written
	inside = {}
	for r in new_rows:
		inside.setdefault(_key(r), []).append(r)
	for k, rows in inside.items():
		if len(rows) > 1:
			r = rows[0]
			add(r, DUPLICATE, [],
				_("{0} is entered {1} times for {2} in this document.").format(
					r.get("employee_name") or r.get("employee"), len(rows), k[1]))

	for r in new_rows:
		for o in by_key.get(_key(r), []):
			why = _same_work(r, o)
			if why:
				add(r, DUPLICATE, [o.get("doc")],
					_("{0} already has {1} recorded on {2} in {3} ({4}). The same work "
						"cannot be captured twice.").format(
						r.get("employee_name") or r.get("employee"), o.get("task") or _("this task"),
						_key(r)[1], _doc_label(o), why))
				break

	for k, rows in inside.items():
		mine = sum(flt(r.get("qty")) for r in rows if is_hourly(r.get("uom")))
		if mine <= 0:
			continue
		theirs = [o for o in by_key.get(k, []) if is_hourly(o.get("uom"))]
		total = mine + sum(flt(o.get("qty")) for o in theirs)
		if total > max_hours + TOLERANCE:
			r = rows[0]
			elsewhere = ", ".join(
				"{0} h in {1}".format(_num(o.get("qty")), _doc_label(o)) for o in theirs)
			add(r, HOURS, [o.get("doc") for o in theirs],
				_("{0} would have {1} hours on {2}, more than the {3} a day allows{4}.").format(
					r.get("employee_name") or r.get("employee"), _num(total), k[1],
					_num(max_hours),
					(" -- " + _("already {0}").format(elsewhere)) if elsewhere else ""))
	return found


def standard_share(rows):
	"""{(employee, date): share} -- how many days' standard each worker-day holds.

	A row's share is its quantity over its plan's daily target: 8 h on an 8 h
	task is 1.0, one bed on a one-bed target is 1.0, 4 h is 0.5. Rows whose plan
	has no daily target contribute nothing: there is no standard to compare to.
	"""
	out = {}
	for r in rows or []:
		target = flt(r.get("daily_target"))
		qty = flt(r.get("qty"))
		if target <= 0 or qty <= 0:
			continue
		k = _key(r)
		out[k] = out.get(k, 0) + qty / target
	return out


def over_one_standard(share):
	return flt(share) > 1 + TOLERANCE


def _num(value):
	value = flt(value, 2)
	return str(int(value)) if value == int(value) else str(value)


# --------------------------------------------------------------- the database


def max_hours():
	try:
		value = flt(frappe.db.get_single_value(SETTINGS, "max_hours_per_day"))
	except Exception:
		value = 0
	return value or DEFAULT_MAX_HOURS


def counted_states():
	"""Draft, every approval step and the terminal state -- never Rejected."""
	from work_management import approvals

	try:
		ends = approvals.pipeline_states(document_type=ACTUALS_DT)
	except Exception:
		ends = {}
	states = set(ends.get("entered") or []) | {"Draft", "CONFIRMED"}
	states.discard(ends.get("reject") or "Rejected")
	states.discard("Rejected")
	return sorted(s for s in states if s)


def other_rows(employees, dates, exclude=None):
	"""Counted day-rows of other documents for these employees on these dates.
	`exclude` is a document name or a list of them."""
	if isinstance(exclude, (list, tuple, set)):
		exclude = tuple(x for x in exclude if x) or ("__none__",)
	else:
		exclude = (exclude or "__none__",)
	employees = tuple(sorted({e for e in employees or [] if e}))
	dates = tuple(sorted({str(d)[:10] for d in dates or [] if d}))
	if not employees or not dates:
		return []
	return frappe.db.sql("""
		SELECT we.name row_name, we.employee, we.employee_name, we.work_date,
		       we.actual_quantity qty, we.hours, IFNULL(we.paid, 0) paid, we.amount,
		       ac.name doc, ac.workflow_state state, ac.assignment,
		       COALESCE(ac.task, a.task) task,
		       COALESCE(ac.block_section, a.block_section) block,
		       p.uom, p.daily_target
		FROM `tabWork Actuals Employee` we
		INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
		LEFT JOIN `tabWork Management Assigner` a ON ac.assignment = a.name
		LEFT JOIN `tabWork Management Planner` p
		       ON p.name = COALESCE(ac.planner_request, a.planner_request)
		WHERE we.parenttype = %(dt)s
		  AND ac.workflow_state IN %(states)s
		  AND ac.name NOT IN %(exclude)s
		  AND we.actual_quantity > 0
		  AND we.employee IN %(emps)s AND we.work_date IN %(dates)s
	""", {"dt": ACTUALS_DT, "states": tuple(counted_states()), "exclude": exclude,
		"emps": employees, "dates": dates}, as_dict=True)


def context_of(assignment=None, doc=None):
	"""The assignment, task, block and plan unit a document's rows belong to."""
	ctx = {"assignment": assignment, "task": None, "block": None, "uom": None,
		"daily_target": None, "doc": None}
	if doc is not None:
		ctx["assignment"] = doc.get("assignment") or assignment
		ctx["task"] = doc.get("task")
		ctx["block"] = doc.get("block_section")
		ctx["doc"] = doc.name if not doc.is_new() else None
	planner = doc.get("planner_request") if doc is not None else None
	if ctx["assignment"]:
		a = frappe.db.get_value("Work Management Assigner", ctx["assignment"],
			["task", "block_section", "planner_request"], as_dict=True)
		if a:
			ctx["task"] = ctx["task"] or a.task
			ctx["block"] = ctx["block"] or a.block_section
			planner = planner or a.planner_request
	if planner:
		p = frappe.db.get_value("Work Management Planner", planner,
			["uom", "daily_target"], as_dict=True)
		if p:
			ctx["uom"] = p.uom
			ctx["daily_target"] = p.daily_target
	return ctx


def rows_for(ctx, cells):
	"""Rows in the core's shape from (employee, work_date, qty[, name]) cells."""
	out = []
	for c in cells:
		row = dict(ctx)
		row.update({"employee": c[0], "work_date": str(c[1])[:10], "qty": flt(c[2])})
		if len(c) > 3:
			row["employee_name"] = c[3]
		out.append(row)
	return out


def check(ctx, cells):
	"""Findings for `cells` written under `ctx`, against every other counted document."""
	rows = rows_for(ctx, cells)
	live = [r for r in rows if flt(r["qty"]) > 0]
	if not live:
		return []
	others = other_rows([r["employee"] for r in live], [r["work_date"] for r in live],
		exclude=ctx.get("doc"))
	found = conflicts(live, others, max_hours())
	_name_people(found)
	return found


def _name_people(found):
	missing = {f["employee"] for f in found if f["employee_name"] == f["employee"]}
	if not missing:
		return
	names = dict(frappe.db.get_all("Employee", filters={"name": ["in", list(missing)]},
		fields=["name", "employee_name"], as_list=True))
	for f in found:
		if f["employee_name"] == f["employee"] and names.get(f["employee"]):
			nm = names[f["employee"]]
			f["message"] = f["message"].replace(f["employee"], nm, 1)
			f["employee_name"] = nm


def message(found, plain=False):
	"""The findings as one message: HTML lines for frappe.throw, or plain text
	for a screen that escapes what it prints."""
	lines = [f["message"] for f in found[:LIST_AT_MOST]]
	if len(found) > LIST_AT_MOST:
		lines.append(_("... and {0} more.").format(len(found) - LIST_AT_MOST))
	if plain:
		return " ".join(lines)
	return "<br>".join(frappe.utils.escape_html(x) for x in lines)


def check_document(name):
	"""Findings for a saved document's rows -- what approval asks before it moves it."""
	doc = frappe.get_doc(ACTUALS_DT, name)
	return check(context_of(doc=doc), [
		(r.employee, r.work_date, r.actual_quantity, r.employee_name) for r in doc.get("employees") or []])


def refusal_for_document(name):
	"""The sentence an approval returns instead of moving the document, or None.
	Plain text: the screens print `out.error` escaped."""
	found = check_document(name)
	if not found:
		return None
	return (_("{0} cannot move on: it pays the same worker-day twice or for more hours "
		"than the day holds. Reject one of the documents named and correct it.")
		.format(name) + " " + message(found, plain=True))


# --------------------------------------------------------------- controller


def _row_sig(row):
	return (str(row.get("employee") or ""), str(row.get("work_date") or "")[:10],
		flt(row.get("actual_quantity")))


def rows_to_check(doc):
	"""The rows this save writes or changes. All of them on a new document, or on
	one moving from an uncounted state (Rejected) into a counted one; otherwise
	only rows that are new or whose employee, date or quantity changed -- so a
	note typed on a document already in the chain is not refused for a conflict
	that approval will catch anyway."""
	rows = list(doc.get("employees") or [])
	if doc.is_new():
		return rows
	before = doc.get_doc_before_save()
	if not before:
		return rows
	counted = set(counted_states())
	if before.workflow_state not in counted and doc.workflow_state in counted:
		return rows
	old = {r.name: _row_sig(r) for r in before.get("employees") or []}
	return [r for r in rows if not r.name or old.get(r.name) != _row_sig(r)]


def validate(doc):
	"""Actuals controller hook: refuse a save that would double-capture a day."""
	if doc.flags.get("skip_day_guard"):
		return
	changed = rows_to_check(doc)
	if not changed:
		return
	ctx = context_of(doc=doc)
	all_rows = [(r.employee, r.work_date, r.actual_quantity, r.employee_name)
		for r in doc.get("employees") or []]
	found = check(ctx, all_rows)
	keys = {(str(r.employee or ""), str(r.work_date or "")[:10]) for r in changed}
	found = [f for f in found if (str(f["employee"] or ""), f["work_date"]) in keys]
	if found:
		frappe.throw(message(found), title=_("Already captured"))


# ------------------------------------------------------------------- the grid


def grid_context(assignment, employees, from_date, to_date, exclude=None):
	"""What the entry grid needs to warn per cell before anything is submitted.

	{"max_hours", "this": {uom, daily_target, hourly}, "cells": {"emp~date":
	[{doc, state, paid, task, block, qty, uom, hourly, share, same}]}} -- `same`
	set when the other row is the same work (refused on submit).
	"""
	ctx = context_of(assignment=assignment)
	out = {"max_hours": max_hours(), "cells": {}, "this": {
		"uom": ctx["uom"], "daily_target": flt(ctx["daily_target"]),
		"hourly": 1 if is_hourly(ctx["uom"]) else 0}}
	employees = [e for e in employees or [] if e]
	if not employees or not from_date or not to_date:
		return out
	dates = []
	d = frappe.utils.getdate(from_date)
	end = frappe.utils.getdate(to_date)
	while d <= end and len(dates) < 400:
		dates.append(str(d))
		d = frappe.utils.add_days(d, 1)
	for o in other_rows(employees, dates, exclude=exclude):
		target = flt(o.daily_target)
		out["cells"].setdefault(o.employee + "~" + str(o.work_date), []).append({
			"doc": o.doc, "state": o.state, "paid": cint(o.paid), "task": o.task,
			"block": o.block, "qty": flt(o.qty), "uom": o.uom,
			"hourly": 1 if is_hourly(o.uom) else 0,
			"share": (flt(o.qty) / target) if target > 0 else 0,
			"same": _same_work(ctx, o) or "",
		})
	return out
