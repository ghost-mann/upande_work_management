"""Make the standard day real, then give every actuals row the hours it meant.

TWO JOBS, AND THE ORDER MATTERS

`hours` is new on Work Actuals Employee. Before it, a row said worker, date,
task and how much -- and it meant a whole day, because a day could not be
divided. So the backfill is each row's own date's standard day.

But the standard day has to be true first, and on an existing site it is not.
A `default` on a doctype field applies to a NEW document. Work Management
Settings is a Single that already exists everywhere, so adding the three hours
fields wrote `'0'` into tabSingles for each of them -- not null, not 8. Read
literally that says a working day is zero hours long.

The first version of this patch read them literally. It ran on kaitet.local,
found 7,605 rows needing hours, and set every one to 0.0 -- then logged itself
as done. A patch that records success having written nonsense is worse than one
that fails, so this version seeds the three values before it reads them, and
refuses to write a standard that is not positive.

WHY NOT ONE UPDATE

A Saturday is six hours here, so a blanket eight would invent two hours of
labour on every Saturday row and quietly lower efficiency on every Saturday
ever worked. One UPDATE per weekday group, keyed on DAYOFWEEK, does it in three
statements rather than 30,833.

Only empty cells. A row already carrying hours was typed by somebody and is
right. Zero counts as empty: a row with quantity and no hours is one this field
never reached, and nobody records a day of zero hours against real output.
"""

import frappe

from work_management import split_day

FIELDS = (("weekday", "std_hours_weekday"), ("saturday", "std_hours_saturday"),
	("sunday", "std_hours_sunday"))

#: DAYOFWEEK in MariaDB: 1 = Sunday .. 7 = Saturday
_WEEKDAY_GROUPS = (("saturday", "= 7"), ("sunday", "= 1"), ("weekday", "NOT IN (1, 7)"))


def execute():
	if not frappe.db.exists("DocType", "Work Actuals Employee"):
		return
	model = seed_standard_day()
	if not frappe.db.has_column("Work Actuals Employee", "hours"):
		# The field ships with this release, so post-sync the column is there.
		# Raise rather than return: returning would log this patch as done and
		# leave every row without hours, with nothing to say so.
		frappe.throw("Work Actuals Employee has no `hours` column yet -- "
			"schema sync must run before this patch")
	backfill(model)


def seed_standard_day():
	"""Store the shipped hours wherever the site holds nothing meaningful.

	Once a real figure is stored, a zero typed later is somebody's decision and
	is honoured -- "we do not work Sundays" is a real thing to say. It is only
	the zero that the field's own creation wrote that has to be corrected, and
	the two are indistinguishable by value alone, which is why this runs once
	and now.
	"""
	shipped = dict(split_day.STANDARD_DAY)
	if not frappe.db.exists("DocType", "Work Management Settings"):
		return shipped
	model = {}
	for key, field in FIELDS:
		try:
			stored = frappe.db.get_single_value("Work Management Settings", field)
		except Exception:
			stored = None
		if stored in (None, "") or float(stored) <= 0:
			frappe.db.set_single_value("Work Management Settings", field, shipped[key])
			model[key] = shipped[key]
			print("   standard day: %s was %r, seeded to %s" % (field, stored, shipped[key]))
		else:
			model[key] = float(stored)
	frappe.db.commit()
	frappe.clear_cache(doctype="Work Management Settings")
	return model


def backfill(model):
	"""Fill the empty hours, best information first.

	Three passes, in this order, because two of them know better than the third.

	1. A task measured in Hours already records the hours -- in
	   `actual_quantity`. Filling those rows with the date's standard would
	   overwrite a fact with an assumption, and it showed: it put 6 against a
	   Saturday row whose quantity says 8, and the hours-vs-quantity check
	   flagged 309 rows on kaitet.local that were purely this patch's doing.

	2. A worker with several rows on one date gave ONE day between them. Giving
	   each row a full standard day claims a 24-hour Wednesday: 142 worker-days
	   on kaitet.local span more than one row -- 3% of them -- and a
	   full-standard fill invented 1,168 hours of labour and 120 long-day flags.
	   So the day is divided by the number of rows sharing it.

	   Approximate where a day mixes an hourly task with a piece-rate one, and
	   deliberately so: this is a backfill of history, and approximate-and-honest
	   beats precise-and-false. Anything typed from here on is exact.

	3. Everything else is one row for one day, which means the standard day.

	Only empty cells throughout. Zero counts as empty: a row with quantity and no
	hours is one this field never reached, and nobody records a day of zero hours
	against real output.
	"""
	hourly = _fill_hourly_from_quantity()
	shared = _fill_shared_days(model)
	whole = _fill_whole_days(model)

	frappe.db.commit()
	left = frappe.db.sql(
		"SELECT COUNT(*) n FROM `tabWork Actuals Employee` WHERE IFNULL(hours, 0) = 0"
	)[0][0]
	print("backfilled %d row(s) -- %d from an hourly task's own quantity, %d by "
		"dividing a shared day, %d at the standard day; %d left"
		% (hourly + shared + whole, hourly, shared, whole, left))


def _fill_hourly_from_quantity():
	"""An Hour-unit task's quantity IS its hours. Use what is recorded."""
	rows = frappe.db.sql("""
		SELECT COUNT(*) n FROM `tabWork Actuals Employee` we
		INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
		INNER JOIN `tabWork Management Assigner` a ON ac.assignment = a.name
		INNER JOIN `tabWork Management Planner` p ON a.planner_request = p.name
		WHERE IFNULL(we.hours, 0) = 0 AND we.actual_quantity > 0
		  AND LOWER(TRIM(IFNULL(p.uom, ''))) IN ('hour', 'hours', 'hr', 'hrs')
	""")[0][0]
	if not rows:
		return 0
	frappe.db.sql("""
		UPDATE `tabWork Actuals Employee` we
		INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
		INNER JOIN `tabWork Management Assigner` a ON ac.assignment = a.name
		INNER JOIN `tabWork Management Planner` p ON a.planner_request = p.name
		SET we.hours = we.actual_quantity
		WHERE IFNULL(we.hours, 0) = 0 AND we.actual_quantity > 0
		  AND LOWER(TRIM(IFNULL(p.uom, ''))) IN ('hour', 'hours', 'hr', 'hrs')
	""")
	print("   hourly    %6d row(s) took their hours from their own quantity" % rows)
	return rows


def _fill_shared_days(model):
	"""A day split across several rows is one day, divided between them."""
	filled = 0
	for key, clause in _WEEKDAY_GROUPS:
		hours = float(model.get(key) or 0)
		if hours <= 0:
			continue
		rows = frappe.db.sql("""
			SELECT COUNT(*) n FROM `tabWork Actuals Employee` we
			INNER JOIN (
				SELECT employee, work_date, COUNT(*) c
				FROM `tabWork Actuals Employee`
				WHERE work_date IS NOT NULL
				GROUP BY employee, work_date
				HAVING COUNT(*) > 1
			) d ON d.employee = we.employee AND d.work_date = we.work_date
			WHERE IFNULL(we.hours, 0) = 0 AND DAYOFWEEK(we.work_date) %s
		""" % clause)[0][0]
		if not rows:
			continue
		frappe.db.sql("""
			UPDATE `tabWork Actuals Employee` we
			INNER JOIN (
				SELECT employee, work_date, COUNT(*) c
				FROM `tabWork Actuals Employee`
				WHERE work_date IS NOT NULL
				GROUP BY employee, work_date
				HAVING COUNT(*) > 1
			) d ON d.employee = we.employee AND d.work_date = we.work_date
			SET we.hours = %%(h)s / d.c
			WHERE IFNULL(we.hours, 0) = 0 AND DAYOFWEEK(we.work_date) %s
		""" % clause, {"h": hours})
		print("   shared    %6d %s row(s) split a %s-hour day between them"
			% (rows, key, hours))
		filled += rows
	return filled


def _fill_whole_days(model):
	"""One row, one day: the standard."""
	filled = 0
	for key, clause in _WEEKDAY_GROUPS:
		hours = float(model.get(key) or 0)
		rows = frappe.db.sql("""
			SELECT COUNT(*) n FROM `tabWork Actuals Employee`
			WHERE IFNULL(hours, 0) = 0 AND work_date IS NOT NULL
			  AND DAYOFWEEK(work_date) %s
		""" % clause)[0][0]
		if not rows:
			continue
		if hours <= 0:
			# a site that works no hours that day. Writing zero would be writing
			# what is already there and calling it a backfill
			print("   %-9s %6d row(s) left alone -- the site works no hours that day"
				% (key, rows))
			continue
		frappe.db.sql("""
			UPDATE `tabWork Actuals Employee`
			SET hours = %%(h)s
			WHERE IFNULL(hours, 0) = 0 AND work_date IS NOT NULL
			  AND DAYOFWEEK(work_date) %s
		""" % clause, {"h": hours})
		print("   %-9s %6d row(s) set to the standard %s hours" % (key, rows, hours))
		filled += rows
	return filled
