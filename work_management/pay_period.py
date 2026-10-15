# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""The pay period: a pay week, or a pay month. The ONE place its dates are worked out.

Altura moved casual payroll from weekly to monthly. A pay month does not follow
the calendar: it runs from a configured start day to the day before it in the
next month -- the 21st to the 20th -- and is named for the month it ENDS in:

    October 2026: 21 Sep -> 20 Oct

Two settings decide it, beside the three that already shape a pay week:

- `pay_frequency`        Weekly | Monthly. Weekly is every site's behaviour to
                         date and stays the default.
- `pay_month_start_day`  1..28. 1 is the calendar month; 21 is Altura's. Capped at
                         28 so every month has the day.

Everything that needs a period asks here: the payroll feed, the Pay workers
window, sending to accounts (one worker or in bulk), the Issues check, and the
screen's period navigator, which gets its periods from the server rather than
doing its own date maths. Before this the week arithmetic lived in five places,
one of them JavaScript that ignored `pay_week_starts_on` altogether.

WEEKLY IS NOT REIMPLEMENTED. A weekly period is exactly `pay_week.week_of()`,
its pay date exactly `pay_week.pay_date()`, and its stamp exactly the
"from -> to" the feed has always written -- so a weekly site sees no change at
all, and Employee.custom_basic_pay_week values written before this still match.

Pure apart from `from_settings()`: every other function takes plain dates and a
shape dict, so the boundaries can be tested without a site.
"""

import calendar
import datetime

from work_management import pay_week

WEEKLY = "Weekly"
MONTHLY = "Monthly"
FREQUENCIES = (WEEKLY, MONTHLY)

#: Altura's month opens on the 21st; a site that says nothing gets the calendar month
DEFAULT_MONTH_START_DAY = 1
MAX_MONTH_START_DAY = 28

SHORT_MONTHS = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

as_date = pay_week.as_date


def month_start_day(value):
	"""The configured start day as an int in 1..28; anything else gets the default."""
	try:
		day = int(value or 0)
	except (TypeError, ValueError):
		day = 0
	if day < 1 or day > MAX_MONTH_START_DAY:
		return DEFAULT_MONTH_START_DAY
	return day


def shape(frequency=None, start_day=None, starts_on=None, ends_on=None, pay_day=None):
	"""The configured period: the pay week's shape, plus frequency and month start."""
	out = pay_week.shape(starts_on, ends_on, pay_day)
	out["frequency"] = MONTHLY if frequency == MONTHLY else WEEKLY
	out["month_start_day"] = month_start_day(start_day)
	return out


def from_settings(settings=None):
	"""shape() from Work Management Settings, or from a dict/doc standing in for it."""
	if settings is None:
		import frappe

		def get(field):
			return frappe.db.get_single_value("Work Management Settings", field)
	else:
		def get(field):
			return settings.get(field)
	return shape(get("pay_frequency"), get("pay_month_start_day"),
		get("pay_week_starts_on"), get("pay_week_ends_on"), get("pay_day"))


def is_monthly(sh):
	return sh.get("frequency") == MONTHLY


def word(sh):
	"""'month' or 'week', for the sentences the screens build."""
	return "month" if is_monthly(sh) else "week"


# ── months ─────────────────────────────────────────────────────────────────
def _shift_month(year, month, by):
	index = year * 12 + (month - 1) + by
	return index // 12, index % 12 + 1


def _month_opening(day, sh):
	"""The first day of the pay month containing `day`."""
	start = sh["month_start_day"]
	if day.day >= start:
		return datetime.date(day.year, day.month, start)
	year, month = _shift_month(day.year, day.month, -1)
	return datetime.date(year, month, start)


def _month_span(opening, sh):
	year, month = _shift_month(opening.year, opening.month, 1)
	nxt = datetime.date(year, month, sh["month_start_day"])
	return opening, nxt - datetime.timedelta(days=1)


# ── the resolver ───────────────────────────────────────────────────────────
def period_of(day, sh):
	"""(from_date, to_date) of the period containing `day`, or None.

	None only in weekly mode, on a weekday a shorter-than-seven-day pay week
	leaves out (see pay_week.week_of). Every date belongs to some pay month.
	"""
	day = as_date(day)
	if is_monthly(sh):
		return _month_span(_month_opening(day, sh), sh)
	return pay_week.week_of(day, sh)


def shift(day, steps, sh):
	"""The period `steps` periods before (negative) or after the one holding `day`."""
	day = as_date(day)
	if is_monthly(sh):
		opening = _month_opening(day, sh)
		year, month = _shift_month(opening.year, opening.month, int(steps))
		return _month_span(datetime.date(year, month, sh["month_start_day"]), sh)
	found = pay_week.week_of(day, sh)
	if not found:
		# a gap weekday: the week before it is the one it follows
		found = previous_complete(day, sh, inclusive=True)
	start = found[0] + datetime.timedelta(days=7 * int(steps))
	return pay_week.week_of(start, sh)


def previous_complete(today, sh, inclusive=False):
	"""The most recent period that closed before `today` (on or before, if inclusive)."""
	today = as_date(today)
	if is_monthly(sh):
		opening = _month_opening(today, sh)
		span = _month_span(opening, sh)
		if inclusive and span[1] <= today:
			return span
		return _month_span(_month_opening(opening - datetime.timedelta(days=1), sh), sh)
	if inclusive:
		return pay_week.last_complete_week(today + datetime.timedelta(days=1), sh)
	return pay_week.last_complete_week(today, sh)


def stamp(start, end):
	"""What Employee.custom_basic_pay_week holds: the same text in either mode."""
	return str(as_date(start)) + " → " + str(as_date(end))


def label(start, end, sh):
	"""How a person reads the period. Both dates, always.

	Weekly is what the Pay workers navigator has always shown: "12 Oct -> 18
	Oct 2026". Monthly is named for the month it ends in: "October 2026: 21 Sep
	-> 20 Oct". (Neither is the stamp; the stamp is ISO and is for matching.)
	"""
	start = as_date(start)
	end = as_date(end)
	if not is_monthly(sh):
		return (str(start.day) + " " + SHORT_MONTHS[start.month] + " → "
			+ str(end.day) + " " + SHORT_MONTHS[end.month] + " " + str(end.year))
	return (calendar.month_name[end.month] + " " + str(end.year) + ": "
		+ str(start.day) + " " + SHORT_MONTHS[start.month] + " → "
		+ str(end.day) + " " + SHORT_MONTHS[end.month])


def pay_date(end, sh):
	"""When the period is paid. A pay week keeps its configured pay day; a pay
	month is paid on the day it closes, the 20th for a 21st-to-20th month."""
	if is_monthly(sh):
		return as_date(end)
	return pay_week.pay_date(end, sh)


def is_complete(end, today, allow_part=False):
	return pay_week.is_complete(end, today, allow_part)


def resolve(span, sh, today):
	"""Everything a caller or the screen needs to know about one period."""
	if not span:
		return None
	start, end = as_date(span[0]), as_date(span[1])
	return {
		"from": str(start),
		"to": str(end),
		"label": label(start, end, sh),
		"stamp": stamp(start, end),
		"is_complete": 1 if is_complete(end, today) else 0,
		"pay_date": str(pay_date(end, sh)),
		"frequency": sh["frequency"],
		"word": word(sh),
	}


def payroll_period(day, settings=None, today=None, sh=None):
	"""The period containing `day`, resolved: from, to, label, stamp, is_complete."""
	sh = sh or from_settings(settings)
	if today is None:
		import frappe

		today = frappe.utils.today()
	return resolve(period_of(day, sh), sh, today)


def weeks_closing_in(start, end, sh):
	"""The pay weeks that END inside [start, end], in order.

	How a pay month carries the weekly off-day bonus: each pay week belongs to
	the month its last day falls in, so a week straddling the 20th/21st is
	counted once, in the month it closes in, and never in both or neither.
	"""
	start = as_date(start)
	end = as_date(end)
	out = []
	day = start
	while day <= end:
		found = pay_week.week_of(day, sh)
		if found and start <= found[1] <= end and found not in out:
			out.append(found)
		day += datetime.timedelta(days=1)
	return out
