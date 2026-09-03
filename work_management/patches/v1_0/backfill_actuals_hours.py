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
	# DAYOFWEEK in MariaDB: 1 = Sunday .. 7 = Saturday
	groups = (("saturday", "= 7"), ("sunday", "= 1"), ("weekday", "NOT IN (1, 7)"))
	filled = 0
	for key, clause in groups:
		hours = float(model.get(key) or 0)
		empty = frappe.db.sql(
			"""
			SELECT COUNT(*) n FROM `tabWork Actuals Employee`
			WHERE IFNULL(hours, 0) = 0 AND work_date IS NOT NULL
			  AND DAYOFWEEK(work_date) %s
			""" % clause
		)[0][0]
		if not empty:
			continue
		if hours <= 0:
			# a site that says this day is not worked. Writing zero would be
			# writing what is already there, and claiming it as a backfill
			print("   %-9s %6d row(s) left alone -- the site works no hours that day"
				% (key, empty))
			continue
		frappe.db.sql(
			"""
			UPDATE `tabWork Actuals Employee`
			SET hours = %%(h)s
			WHERE IFNULL(hours, 0) = 0 AND work_date IS NOT NULL
			  AND DAYOFWEEK(work_date) %s
			""" % clause,
			{"h": hours},
		)
		filled += empty
		print("   %-9s %6d row(s) set to %s hours" % (key, empty, hours))

	frappe.db.commit()
	left = frappe.db.sql(
		"SELECT COUNT(*) n FROM `tabWork Actuals Employee` WHERE IFNULL(hours, 0) = 0"
	)[0][0]
	print("backfilled %d row(s); %d still without hours" % (filled, left))
