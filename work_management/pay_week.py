# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Where one pay week starts, where it ends, and when it is paid.

Workers are paid by the WEEK: one payment per worker per completed pay week, so
payroll receives one line per week rather than a lump covering several. Three
independent settings decide the shape -- `pay_week_starts_on`, `pay_week_ends_on`
and `pay_day` -- and the week's LENGTH follows from the first two, so a pay week
need not be seven days. Where it is shorter, the weekdays left over belong to no
week at all: they are real work and are reported rather than folded into a
neighbouring week, because folding them would pay a day twice.

This arithmetic was inline in `api/payment.py`'s `pay_worker_submit`, which is
the only place that needed it. `feed_week_to_payroll` in `api/payroll.py` needs
exactly the same answer -- a payroll feed that grouped days into different weeks
from the payment run would pay a worker for a week the payment never covered --
so the rule lives here, pure, and both sides ask it rather than each deriving it.

Pure and site-free on purpose: every function takes plain dates and strings, so
the boundaries can be tested at every offset without a database. Frappe's script
sandbox forbids imports, so the mirror inlines this the way it inlines
``split_day.py`` and ``master_plan.py``; keep the two in step.
"""

import datetime

#: Monday is 0, matching ``datetime.date.weekday()`` and Frappe's own usage.
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

#: What a site gets when it has said nothing: Sunday to Saturday, paid on the
#: closing day. This is the shape kaitet.local has always run.
DEFAULT_STARTS_ON = "Sunday"
DEFAULT_ENDS_ON = "Saturday"


def as_date(value):
	"""A ``datetime.date`` from a date, a datetime or an ISO string."""
	if isinstance(value, datetime.datetime):
		return value.date()
	if isinstance(value, datetime.date):
		return value
	return datetime.date.fromisoformat(str(value)[:10])


def weekday_index(name, fallback):
	"""The position of a weekday name, or `fallback` for anything unrecognised.

	A Select can hold an empty string -- the field ships with a blank first
	option -- and an unconfigured site must get the default shape rather than an
	exception on the payment screen.
	"""
	if name in WEEKDAYS:
		return WEEKDAYS.index(name)
	return fallback


def shape(starts_on=None, ends_on=None, pay_day=None):
	"""The configured week as three weekday indexes and a length.

	`days` is the inclusive count from the opening weekday to the closing one,
	wrapping the week: Sunday to Saturday is 7, Monday to Friday is 5, and
	Saturday to Wednesday is 5 as well.

	`pay_day` defaults to the closing day, so a site that only sets the first two
	gets paid on the day the week closes.
	"""
	start_wd = weekday_index(starts_on, WEEKDAYS.index(DEFAULT_STARTS_ON))
	end_wd = weekday_index(ends_on, WEEKDAYS.index(DEFAULT_ENDS_ON))
	pay_wd = weekday_index(pay_day, end_wd)
	return {
		"start_wd": start_wd,
		"end_wd": end_wd,
		"pay_wd": pay_wd,
		"days": ((end_wd - start_wd) % 7) + 1,
	}


def week_of(day, week):
	"""The pay week containing `day`, or None where no week contains it.

	Returns ``(from_date, to_date)``. None is the shorter-than-seven-day case:
	with a Monday-to-Friday week, a Saturday sits in the gap and belongs to no
	pay week. `api/payment.py` reports those days as `outside_any_week` rather
	than dropping them, and this returning None is what lets it.
	"""
	day = as_date(day)
	back = (day.weekday() - week["start_wd"]) % 7
	if back >= week["days"]:
		return None
	start = day - datetime.timedelta(days=back)
	return start, start + datetime.timedelta(days=week["days"] - 1)


def days_in(week_from, week_to):
	"""Every date in a closed week, in order."""
	week_from = as_date(week_from)
	week_to = as_date(week_to)
	out = []
	cursor = week_from
	while cursor <= week_to:
		out.append(cursor)
		cursor += datetime.timedelta(days=1)
	return out


def is_complete(week_to, today, allow_part_week=False):
	"""Has this week closed?

	The week still in progress is held back, because sending it would need a
	second document for the same week later and payroll would see it twice.
	`allow_part_week` is the site's own decision to send it anyway.
	"""
	if allow_part_week:
		return True
	return as_date(week_to) < as_date(today)


def pay_date(week_to, week):
	"""The first pay day on or after the week closes.

	Setting the pay day to the closing day therefore pays on that day, which is
	what `pay_day` defaulting to `pay_week_ends_on` gives.
	"""
	day = as_date(week_to)
	for _ in range(7):
		if day.weekday() == week["pay_wd"]:
			return day
		day += datetime.timedelta(days=1)
	return as_date(week_to)


def last_complete_week(today, week):
	"""The most recent pay week that has closed on or before `today`.

	What a weekly feed offers by default: the week just gone, never the one
	being worked. Walks back a day at a time rather than subtracting a week,
	because a week shorter than seven days leaves gap days that belong to no
	week and stepping by seven would land on one of them.
	"""
	day = as_date(today)
	for _ in range(15):
		found = week_of(day, week)
		if found and found[1] < as_date(today):
			return found
		day -= datetime.timedelta(days=1)
	return None
