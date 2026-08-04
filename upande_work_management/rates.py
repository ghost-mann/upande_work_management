# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Effective-dated task rates.

``Work Task Rate`` holds one row per task per rate period and is the history
layer. ``Task.custom_rate`` / ``custom_uom`` / ``custom_daily_target`` stay
exactly where they are and keep being read by the planner — they are mirrored
from whichever period is active today, so every existing query keeps working.

The mirroring is two-way:

* writing a rate period pushes the active values onto the Task;
* editing the Task writes a rate period, effective from today.

A Task-list edit can only ever mean "from today". Backdated changes go through
the rate card import.
"""

import frappe
from frappe.utils import add_days, flt, getdate, nowdate

#: Rate fields mirrored between Task and Work Task Rate.
TASK_RATE_FIELDS = ("custom_rate", "custom_uom", "custom_daily_target")

#: The daily wage in force before the 2026-07-21 rate card.
LEGACY_DAILY_WAGE = 340.0

#: Within this fraction of the wage, a rate is treated as wage-derived outright.
EXACT_BAND = 0.01

#: Within this fraction, it is borderline and needs a human decision. The old
#: 1% band silently excluded Planting grass (4.6 x 75 = 345/day) which really is
#: 340-derived — the true rate is 340/75 = 4.5333 and someone rounded up.
REVIEW_BAND = 0.10

#: Band comparisons are inclusive; this absorbs float representation error at
#: the exact edge (340 * 1.10 == 374.00000000000006).
BAND_EPSILON = 1e-6


# --------------------------------------------------------------------- lookup


def get_period(task, on_date=None):
	"""The rate period covering ``on_date`` for ``task``, or None."""
	on_date = getdate(on_date or nowdate())
	rows = frappe.db.sql(
		"""
		SELECT name, task, valid_from, valid_to, rate, uom, daily_target,
		       daily_wage_basis, derived, source
		FROM `tabWork Task Rate`
		WHERE task = %(task)s
		  AND valid_from <= %(on_date)s
		  AND (valid_to IS NULL OR valid_to >= %(on_date)s)
		ORDER BY valid_from DESC
		LIMIT 1
		""",
		{"task": task, "on_date": on_date},
		as_dict=True,
	)
	return rows[0] if rows else None


def get_periods(tasks, on_date=None):
	"""``get_period`` for many tasks at once -> {task: period}."""
	if not tasks:
		return {}
	on_date = getdate(on_date or nowdate())
	rows = frappe.db.sql(
		"""
		SELECT name, task, valid_from, valid_to, rate, uom, daily_target,
		       daily_wage_basis, derived, source
		FROM `tabWork Task Rate`
		WHERE task IN %(tasks)s
		  AND valid_from <= %(on_date)s
		  AND (valid_to IS NULL OR valid_to >= %(on_date)s)
		ORDER BY valid_from ASC
		""",
		{"tasks": tuple(tasks), "on_date": on_date},
		as_dict=True,
	)
	# ascending order means the latest-starting period wins the key
	return {row.task: row for row in rows}


# ----------------------------------------------------------------- forward sync


def sync_task_from_periods(task):
	"""Mirror the currently-active period onto the Task rate fields.

	``frappe.db.set_value`` bypasses the document lifecycle, so this cannot
	re-trigger :func:`task_on_update`. The flag is belt-and-braces for any
	future caller that switches to ``doc.save()``.
	"""
	if not task:
		return None

	period = get_period(task)
	if not period:
		return None

	current = frappe.db.get_value("Task", task, TASK_RATE_FIELDS, as_dict=True)
	if not current:
		return None

	wanted = {
		"custom_rate": flt(period.rate),
		"custom_uom": period.uom,
		"custom_daily_target": flt(period.daily_target),
	}
	changed = {
		field: value
		for field, value in wanted.items()
		if not _same(current.get(field), value)
	}
	if not changed:
		return period

	frappe.flags.wm_rate_sync = True
	try:
		frappe.db.set_value("Task", task, changed)
	finally:
		frappe.flags.wm_rate_sync = False
	return period


def _same(a, b):
	if isinstance(a, (int, float)) or isinstance(b, (int, float)):
		return abs(flt(a) - flt(b)) < 0.0000005
	return (a or "") == (b or "")


def sync_active_periods():
	"""Daily scheduler: activate periods that start today or ended yesterday.

	Without this a rate card loaded in advance would never take effect —
	nothing else would fire on its start date.
	"""
	today = getdate(nowdate())
	tasks = frappe.db.sql_list(
		"""
		SELECT DISTINCT task FROM `tabWork Task Rate`
		WHERE valid_from = %(today)s OR valid_to = %(yesterday)s
		""",
		{"today": today, "yesterday": add_days(today, -1)},
	)
	for task in tasks:
		sync_task_from_periods(task)
	if tasks:
		frappe.db.commit()
	return len(tasks)


# ----------------------------------------------------------------- reverse hook


def task_on_update(doc, method=None):
	"""Record a rate period whenever a Task's rate fields change.

	The period starts today: an edit in the Task list cannot express a
	backdated change. If a period already starts today it is amended in place,
	so repeated edits on one day don't try to close a period at a date before
	it began.
	"""
	if frappe.flags.get("wm_rate_sync"):
		return
	if not flt(doc.get("custom_rate")):
		return

	before = doc.get_doc_before_save()
	if before:
		changed = any(not _same(before.get(field), doc.get(field)) for field in TASK_RATE_FIELDS)
		if not changed:
			return

	today = getdate(nowdate())
	target = flt(doc.get("custom_daily_target"))
	rate = flt(doc.get("custom_rate"))
	verdict, _implied = classify(rate, target)

	existing = frappe.db.sql_list(
		"""
		SELECT name FROM `tabWork Task Rate`
		WHERE task = %(task)s AND valid_from = %(today)s AND valid_to IS NULL
		LIMIT 1
		""",
		{"task": doc.name, "today": today},
	)
	existing = existing[0] if existing else None
	if existing:
		frappe.db.set_value(
			"Work Task Rate",
			existing,
			{
				"rate": rate,
				"uom": doc.get("custom_uom"),
				"daily_target": target,
				"derived": 1 if verdict == "derived" else 0,
				"source": "Task list edit",
			},
		)
		return

	# A rate card may already be queued ahead of today. The edit applies only up
	# to the day that card takes over — otherwise this period would run open
	# alongside a future one and trip the no-overlap rule with a message that
	# means nothing to someone editing a Task.
	upcoming = frappe.db.sql_list(
		"""
		SELECT valid_from FROM `tabWork Task Rate`
		WHERE task = %(task)s AND valid_from > %(today)s
		ORDER BY valid_from ASC LIMIT 1
		""",
		{"task": doc.name, "today": today},
	)

	period = frappe.new_doc("Work Task Rate")
	period.update(
		{
			"task": doc.name,
			"valid_from": today,
			"valid_to": add_days(getdate(upcoming[0]), -1) if upcoming else None,
			"rate": rate,
			"uom": doc.get("custom_uom"),
			"daily_target": target,
			"daily_wage_basis": LEGACY_DAILY_WAGE if verdict == "derived" else None,
			"derived": 1 if verdict == "derived" else 0,
			"source": "Task list edit",
		}
	)
	period.flags.ignore_permissions = True
	period.insert(ignore_permissions=True)


# -------------------------------------------------------------- classification


def classify(rate, daily_target, wage=LEGACY_DAILY_WAGE):
	"""Is this rate governed by the daily wage?

	Returns ``(verdict, implied_daily_wage)`` where verdict is one of
	``derived`` / ``borderline`` / ``not_derived`` / ``unknown``.

	``borderline`` is never decided automatically. The stored data is noisy —
	337.50, 339.99, 340.05, 340.50, 345.00 all appear — and no numeric rule
	separates rounding drift from a genuinely different wage, so those go to a
	human once and the answer is recorded on the period.
	"""
	rate = flt(rate)
	daily_target = flt(daily_target)
	if not rate or not daily_target:
		return "unknown", None

	implied = rate * daily_target
	drift = abs(implied - wage)
	# Bands are inclusive. The epsilon matters: 340 * 1.10 evaluates to
	# 374.00000000000006, so an exact-boundary task would otherwise fall out of
	# the band on float error alone.
	if drift <= wage * EXACT_BAND + BAND_EPSILON:
		return "derived", implied
	if drift <= wage * REVIEW_BAND + BAND_EPSILON:
		return "borderline", implied
	return "not_derived", implied


# -------------------------------------------------------------------- backfill


def default_epoch():
	"""Earliest planner date — where rate history has to begin.

	Anything earlier would sit outside all periods, and the recalc refuses to
	touch work it cannot price.
	"""
	earliest = frappe.db.sql_list(
		"SELECT MIN(from_date) FROM `tabWork Management Planner` WHERE from_date IS NOT NULL"
	)
	return getdate(earliest[0]) if earliest and earliest[0] else getdate(nowdate())


def backfill_from_task_master(epoch=None, wage=LEGACY_DAILY_WAGE, dry_run=True):
	"""Give every rated Task one open period holding its current values.

	The legacy rate is preserved exactly as stored, including its rounding —
	that is what was actually used to pay people, and rewriting it would
	falsify history. Borderline tasks are created with ``derived = 0`` and a
	note, so nothing is silently classified.
	"""
	epoch = getdate(epoch or default_epoch())
	tasks = frappe.db.sql(
		"""
		SELECT name, custom_rate, custom_uom, custom_daily_target
		FROM `tabTask`
		WHERE IFNULL(custom_rate, 0) > 0
		""",
		as_dict=True,
	)
	already = set(frappe.db.sql_list("SELECT DISTINCT task FROM `tabWork Task Rate`"))

	created, skipped = 0, 0
	counts = {"derived": 0, "borderline": 0, "not_derived": 0, "unknown": 0}
	for task in tasks:
		if task.name in already:
			skipped += 1
			continue
		verdict, implied = classify(task.custom_rate, task.custom_daily_target, wage)
		counts[verdict] += 1
		if dry_run:
			created += 1
			continue

		note = None
		if verdict == "borderline":
			note = (
				"Borderline: implied daily wage {0:.2f} against {1:.2f}. "
				"Confirm whether this rate is wage-derived before recalculating.".format(
					implied, wage
				)
			)
		elif verdict == "not_derived":
			note = (
				"Not wage-derived: implied daily wage {0:.2f}. "
				"Excluded from wage recalculations.".format(implied)
			)

		period = frappe.new_doc("Work Task Rate")
		period.update(
			{
				"task": task.name,
				"valid_from": epoch,
				"rate": flt(task.custom_rate),
				"uom": task.custom_uom,
				"daily_target": flt(task.custom_daily_target),
				"daily_wage_basis": wage if verdict == "derived" else None,
				"derived": 1 if verdict == "derived" else 0,
				"source": "backfill from Task master",
				"notes": note,
			}
		)
		period.flags.ignore_permissions = True
		period.insert(ignore_permissions=True)
		created += 1
		if created % 200 == 0:
			frappe.db.commit()

	if not dry_run:
		frappe.db.commit()

	return {
		"epoch": str(epoch),
		"dry_run": 1 if dry_run else 0,
		"tasks_considered": len(tasks),
		"periods_created": created,
		"tasks_already_covered": skipped,
		"classification": counts,
	}
