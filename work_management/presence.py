# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Which date a presence question is about.

Presence is derived in six places -- the assigner's picker chips and its presence
bar, the actuals grid's per-cell evidence, the attendance gates on submit, the
worker review sheet's daily log and the discrepancy audit's presence rules -- and
every one of them is answering the same question:

    was this person on site on the day this row is about?

The day this row is about is the WORK DATE. It is the actuals row's
`work_date`, or the assignment window's own days. It is not today.

That distinction cost nothing while work was recorded on the day it happened.
Altura backfills: master plans and actuals are raised for previous weeks, and
against a window of 14-18 September the assigner's chips reported who had
scanned in this morning. Daniel was deciding whether a day was payable against a
scan from a different fortnight.

**One rule is genuinely about today and stays that way.** The morning-scan gate
asks "has this crew turned up *this morning*, and is it past the cutoff" -- it
exists to stop somebody staffing today's work with people who never arrived, and
it is meaningless against a window that has already finished. `applies_today()`
is that rule, and it says no for a past window rather than being made to answer
about one.

Pure -- dates in, dates out, no site -- so the arithmetic can be asserted
directly. `work_management/split_day.py` and `work_management/master_plan.py`
are laid out the same way and for the same reason.
"""

#: What a caller gets when no day of the window has happened yet: a window
#: entirely in the future has no presence to report, and reporting "no record"
#: for it reads as a finding when it is only a date.
NOTHING = (None, None, 0)


def _iso(value):
	"""A date as the string everything here compares, or None."""
	if value is None or value == "":
		return None
	return str(value)[:10]


def evidence_window(from_date, to_date, today):
	"""The days of this window that can be asked about, as ``(from, to, days)``.

	The window's own days, clipped at today, because tomorrow has no scan to
	find. ``NOTHING`` when the window has not started, or when either end is
	missing -- a request with no period is not a request about no days, it is a
	request that cannot be answered.

	>>> evidence_window("2026-09-14", "2026-09-18", "2026-09-23")
	('2026-09-14', '2026-09-18', 5)
	>>> evidence_window("2026-09-21", "2026-09-25", "2026-09-23")
	('2026-09-21', '2026-09-23', 3)
	>>> evidence_window("2026-09-28", "2026-10-02", "2026-09-23")
	(None, None, 0)
	"""
	start = _iso(from_date)
	end = _iso(to_date)
	now = _iso(today)
	if not start or not end or not now:
		return NOTHING
	if end > now:
		end = now
	if start > end:
		return NOTHING
	return start, end, _days_between(start, end)


def day_asked_about(from_date, to_date, today):
	"""The single date a presence chip answers for, or None.

	The last day of the window that has happened. On a window containing today
	that IS today, so nothing a screen prints changes on a current plan; on a
	window that finished last Tuesday it is last Tuesday, which is the day the
	work was done and the day the scan has to come from.
	"""
	return evidence_window(from_date, to_date, today)[1]


def applies_today(from_date, to_date, today):
	"""Whether a rule that is explicitly about TODAY has anything to say here.

	The morning-scan gate, and nothing else. True only while the window contains
	today: a past window's crew cannot turn up this morning, and refusing to
	staff it because they did not is the gate firing on a question nobody asked.
	"""
	start = _iso(from_date)
	end = _iso(to_date)
	now = _iso(today)
	if not (start and end and now):
		return False
	return start <= now <= end


def is_past_window(from_date, to_date, today):
	"""True when every day of this window is behind us -- a backfill.

	What a screen needs to know before it prints the word "today".
	"""
	end = _iso(to_date)
	now = _iso(today)
	return bool(end and now and end < now)


def _days_between(start, end):
	"""Inclusive day count between two ISO dates. No frappe, no datetime import
	games -- these are dates in one calendar and the arithmetic is ordinary."""
	from datetime import date

	first = date(int(start[0:4]), int(start[5:7]), int(start[8:10]))
	last = date(int(end[0:4]), int(end[5:7]), int(end[8:10]))
	return (last - first).days + 1
