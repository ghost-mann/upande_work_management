"""Who counts as a task worker, and which recorded rows no longer agree.

Three lists in Work Management Settings decide whether a person's work is paid
per unit: their employment type, their designation, or their category. Any one
match is enough -- they are ORed.

The lists are free text whose contents end up inside a SQL `IN (...)`, so
reading them is the part that has actually broken in production: a newline that
survived into a value once discarded the whole list and stopped 315 task
workers being payable. parse_list() is that reader, kept here with tests
because the failure mode is silent non-payment rather than an error.

The second half of this module exists because `count_in_payroll` and `amount`
are decided once, when a row is written, and never revisited. Change an
employee's classification or edit a list, and every row already recorded keeps
the old answer -- at zero, with nothing anywhere reporting it. disagreements()
is the missing check.
"""

# Characters a real job title uses. Anything else is dropped, because these
# values are interpolated into SQL.
ALLOWED_CHARS = " -_/&().'"

# (legacy text field, child table, field on the child row, Employee field).
#
# The lists are moving from free text people type to values they pick. Both are
# read, child rows first, so payroll is never down for the moment in between:
# code deployed with the tables still empty behaves exactly as before, and a
# list migrated one at a time does not disturb the others.
LISTS = (
	("tw_employment_types", "tw_employment_type_rows", "employment_type", "employment_type"),
	("tw_designations", "tw_designation_rows", "designation", "designation"),
	("tw_categories", "tw_category_rows", "category", "custom_category"),
)


def parse_list(raw):
	"""The usable values in one Settings box.

	Commas and newlines both separate, because a multi-line box invites either.
	A value carrying anything a job title would not is dropped **on its own** --
	never taking the rest of the list with it, which is the bug this guards.
	"""
	values = set()
	for part in str(raw or "").replace("\r", "\n").replace("\n", ",").split(","):
		part = part.strip()
		if part and all(c.isalnum() or c in ALLOWED_CHARS for c in part):
			values.add(part)
	return values


def picked_values(rows, field):
	"""The values chosen in a child table.

	No character check: these are Link targets or Select options, not typing, so
	a designation with an apostrophe in it is a docname rather than a hazard.
	"""
	values = set()
	for row in rows or []:
		value = (row.get(field) if hasattr(row, "get") else getattr(row, field, None)) or ""
		value = str(value).strip()
		if value:
			values.add(value)
	return values


def rule_from(settings):
	"""{employee field: allowed values} read off a Settings document or dict.

	A list that has been picked wins outright over whatever text it replaced --
	the old box is history at that point, not an addition to it.
	"""
	getter = settings.get if hasattr(settings, "get") else lambda k: None
	rule = {}
	for box, table, child_field, employee_field in LISTS:
		values = picked_values(getter(table), child_field)
		rule[employee_field] = values or parse_list(getter(box))
	return rule


def qualifies(employee, rule):
	"""Whether this employee's work is paid per unit under `rule`.

	An empty rule qualifies nobody. That is deliberate: a blank or unusable
	Settings must not quietly put everyone on piece rates.
	"""
	return any(
		(employee.get(field) or "") in values
		for field, values in rule.items() if values
	)


def disagreements(rows, rule, people):
	"""The rows whose stored payroll flag is not what `rule` says today.

	Both directions are reported. A row left out that should be in is somebody
	unpaid for work they did; a row left in that should be out is money going
	out that should not. An employee the lookup does not know is skipped rather
	than guessed at -- a deleted employee is a different problem.
	"""
	found = []
	for row in rows:
		employee = row.get("employee")
		if employee not in people:
			continue
		expected = 1 if qualifies(people[employee], rule) else 0
		stored = 1 if row.get("count_in_payroll") else 0
		if expected != stored:
			found.append({
				"row": row.get("name"),
				"parent": row.get("parent"),
				"employee": employee,
				"work_date": row.get("work_date"),
				"quantity": row.get("actual_quantity"),
				"amount": row.get("amount"),
				"stored": stored,
				"expected": expected,
			})
	return found


# Weekday indices as Python reports them: Monday is 0, Sunday is 6.
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def pay_week_length(start_day, end_day):
    """How many days the configured pay week spans, inclusive.

    Tuesday to Sunday is six days -- which is the point: a week shorter than
    seven leaves a weekday belonging to no week at all.
    """
    start = WEEKDAYS.index(start_day) if start_day in WEEKDAYS else 6
    end = WEEKDAYS.index(end_day) if end_day in WEEKDAYS else 5
    return start, ((end - start) % 7) + 1


def pay_week_for(weekday, start_weekday, week_len, allow_single_day):
    """(days back to the week start, days the week spans) for one work date.

    None when the date falls in the gap of a pay week shorter than seven days
    and single-day sending is off. That gap is why Monday work on a
    Tuesday-to-Sunday week could never be sent: the bulk send dropped those
    dates without a word, and the single send could only list them as
    "outside".

    With single-day sending on, such a date becomes a one-day week of its own
    rather than nothing. A date that already has a week is returned unchanged
    either way -- turning the setting on must not regroup work that was already
    being sent correctly.
    """
    back = (weekday - start_weekday) % 7
    if back < week_len:
        return back, week_len
    if allow_single_day:
        return 0, 1
    return None
