# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt
"""A worker's day, measured rather than counted.

A day used to be atomic here. An actuals row said worker, date, task and how
much, never how long, so man-days could only be counted:

    COUNT(DISTINCT CONCAT(we.employee, '|', we.work_date))

That is exactly right while a worker can be on one task a day. It is wrong the
moment they can be on two -- the same worker on two assignments for 12 August
counts as two man-days at farm level, a plan for ten people cannot take ten
half-day workers, and a half-day worker misses a full day's `daily_target` and
reads as underperforming.

So every figure derives from hours over the standard hours for that date. The
whole module is pure: no frappe, no database, no document. That is deliberate --
the mirror inlines this logic into a sandbox that allows no functions, and the
only way to know the two agree is for this one to be testable on its own.

Pay does not appear here at all. It stays `quantity x rate`, piece rate, so both
halves of a split day pay correctly by construction and a mistyped hour spoils a
metric rather than a wage.
"""

import datetime

#: Hours in a standard day, by weekday group. Sunday is worked on these farms,
#: so it is a full day and not zero -- a zero here would divide by zero on every
#: Sunday row. A site overrides these in Work Management Settings.
STANDARD_DAY = {"weekday": 8, "saturday": 6, "sunday": 8}

#: Money and quantity comparisons tolerate this much, matching wm_payment.
TOLERANCE = 0.005

#: How far output may run ahead of time before the two are calling each other
#: liars. A constant rather than a setting to begin with: shipping a threshold
#: nobody has a feel for invites somebody to tune it blind.
DISAGREEMENT = 0.25

#: At or above this share of the day, the day was essentially whole and output
#: running ahead of time is just good work.
WHOLE_DAY = 0.95

#: What the catalogue spells an hour. Both are in use.
HOURLY_UOMS = ("hour", "hours", "hr", "hrs")


def _as_date(day):
	"""A date from whatever the caller has -- a date, or an ISO string."""
	if isinstance(day, datetime.datetime):
		return day.date()
	if isinstance(day, datetime.date):
		return day
	return datetime.date.fromisoformat(str(day)[:10])


def standard_hours(day, model=None):
	"""The hours a full day is on `day`.

	Saturday is short and Sunday is not, which is the shape these farms work.
	"""
	model = model or STANDARD_DAY
	weekday = _as_date(day).weekday()  # Monday 0 .. Sunday 6
	if weekday == 5:
		return model.get("saturday", STANDARD_DAY["saturday"])
	if weekday == 6:
		return model.get("sunday", STANDARD_DAY["sunday"])
	return model.get("weekday", STANDARD_DAY["weekday"])


def hours_of(day, hours, model=None):
	"""The hours a row represents, with absence read as a full day.

	30,833 rows predate the field and every one of them means a whole day --
	that is what a row meant before a day could be divided. Reading a null as
	zero would erase all of them from every man-day figure. Explicit zero is a
	real answer and is kept.
	"""
	if hours is None or hours == "":
		return float(standard_hours(day, model))
	return float(hours)


def day_length(day, uom=None, daily_target=None, model=None):
	"""How long a full day is for this piece of work.

	Usually the site's standard day. But a task measured in Hours carries its own
	day length in `daily_target` -- Security Patroll's is 12, Coffee Picking's 3,
	Mill Operations' 8 -- and those are hours, because the unit is hours.

	A twelve-hour patrol shift is one person for one working day. Dividing it by
	an eight-hour standard called it one and a half, which inflated the figure on
	381 rows by +201 man-days on kaitet.local alone. And the job's day does not
	shorten because the site's does: a twelve-hour shift on a Saturday is still
	one shift.

	For everything else -- Trees, Meters, Crates -- `daily_target` is output per
	day and says nothing about time, so the standard day is the only sensible
	denominator.
	"""
	if str(uom or "").strip().lower() in HOURLY_UOMS and float(daily_target or 0) > 0:
		return float(daily_target)
	return float(standard_hours(day, model))


def man_days(rows, model=None):
	"""Man-days across `rows`.

	A row is `(date, hours)`, or `(date, hours, uom, daily_target)` where the
	caller knows the unit -- see day_length() for why that matters. The short
	form still works, so a caller that knows nothing about units is unchanged.

	Hours are summed per date and divided by the length of a day, so two
	four-hour rows on one Wednesday are one man-day however many assignments they
	span, and a full six-hour Saturday is one man-day rather than three quarters.

	Where a date mixes jobs of different day lengths, each row contributes its own
	fraction -- six hours of a twelve-hour job and four of an eight-hour one is
	half of each, which is one day of somebody's time.

	A day of zero length contributes zero rather than raising: that is a site
	saying the day is not worked.
	"""
	total = 0.0
	for row in rows:
		day = row[0]
		hours = row[1]
		uom = row[2] if len(row) > 2 else None
		target = row[3] if len(row) > 3 else None
		length = day_length(day, uom, target, model)
		if length > 0:
			total = total + hours_of(day, hours, model) / length
	return round(total, 6)


def person_days(rows, model=None):
	"""What the crew limit compares against `people_per_day`.

	The same measure as man_days, named for the place that uses it: the assigner
	refused more workers than the plan budgeted by counting people, so two
	half-days read as two people and a plan for ten took only five split
	workers.
	"""
	return man_days(rows, model)


def prorated_target(daily_target, hours, day, model=None):
	"""The output expected of somebody who gave `hours` on `day`.

	A half-day worker meeting half the target is on target, not under. A full
	Saturday expects the whole target: six hours IS the day there, so the
	fraction is against that date's own standard rather than eight.
	"""
	standard = float(standard_hours(day, model))
	if not daily_target or standard <= 0:
		return 0.0
	return round(float(daily_target) * (hours_of(day, hours, model) / standard), 6)


def is_long_day(rows, model=None):
	"""Does any single date in `rows` total more than that date is long?

	Grouped per date, which is the whole point: two ordinary eight-hour days are
	not one sixteen-hour day. Taking the standard from the first row and summing
	every row was the first shape of this, and it called any two full days long.

	Recorded and warned rather than refused: the cost of a wrong number here is
	a spoiled metric, never a wage, and somebody may genuinely have worked over.
	"""
	per_day = {}
	for day, hours in rows:
		key = str(_as_date(day))
		per_day[key] = per_day.get(key, 0.0) + hours_of(day, hours, model)
	for key, total in per_day.items():
		if total > float(standard_hours(key, model)) + TOLERANCE:
			return True
	return False


def output_disagrees_with_hours(quantity, daily_target, hours, day, model=None):
	"""Are the hours and the output contradicting each other?

	NOT "was this a short day". Four hours producing about half a target is an
	ordinary half day and flagging it would make the flag noise. What is worth a
	look is three hours producing a full day's output -- either the hours are
	wrong or the quantity is.

	Only that direction. Output falling short of the time is under-performance,
	a different question with its own reporting.
	"""
	standard = float(standard_hours(day, model))
	if not daily_target or standard <= 0:
		return False
	output_share = float(quantity or 0) / float(daily_target)
	time_share = hours_of(day, hours, model) / standard
	# A whole day is never this flag. Somebody doing 150% of target across a full
	# day is productive, not contradictory, and treating that as a contradiction
	# made the check 162 rows of good performers on real data. The contradiction
	# is a full day's output in a FRACTION of the day.
	if time_share >= WHOLE_DAY:
		return False
	return (output_share - time_share) > DISAGREEMENT


def hourly_task_mismatch(quantity, hours, uom):
	"""On a task already measured in hours, do the two numbers disagree?

	The same number is typed twice on such a task -- 34 of them in the
	catalogue, and 497 of the planners -- because hours are typed on every split
	row whatever the unit. Typing it twice means it can be typed twice
	differently, and this is that check. A Tree task's quantity has nothing to
	do with its hours and is never compared.
	"""
	if str(uom or "").strip().lower() not in HOURLY_UOMS:
		return False
	if hours is None or hours == "":
		return False
	return abs(float(quantity or 0) - float(hours)) > TOLERANCE
