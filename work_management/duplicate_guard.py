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


def validate_actuals(doc, method=None):
	"""Refuse a save that would pay one worker twice for one day."""
	if (doc.get("workflow_state") or "") == "Rejected" or doc.docstatus == 2:
		return
	found = clashes(doc)
	if found:
		lines = ", ".join("{0} on {1} ({2})".format(e, d, other) for e, d, other in found[:8])
		frappe.throw(
			_("One worker, one day, one task. Already recorded elsewhere: {0}").format(lines),
			title=_("Worker already recorded for that day"),
		)
