"""Who counts as a task worker, and which recorded rows no longer agree.

Three lists in Work Management Settings decide whether a person's work is paid
per unit: their employment type, their designation, or their category. Any one
match is enough -- they are ORed.

These used to be free text typed into a box, parsed and interpolated into a SQL
`IN (...)` -- a newline that survived into a value once discarded the whole
list and stopped 315 task workers being payable. That reader is gone along with
the boxes themselves; every site now picks from real child tables instead, so
there is nothing left to mis-parse.

The second half of this module exists because `count_in_payroll` and `amount`
are decided once, when a row is written, and never revisited. Change an
employee's classification or edit a list, and every row already recorded keeps
the old answer -- at zero, with nothing anywhere reporting it. disagreements()
is the missing check.
"""

# (child table, field on the child row, Employee field).
LISTS = (
	("tw_employment_type_rows", "employment_type", "employment_type"),
	("tw_designation_rows", "designation", "designation"),
	("tw_category_rows", "category", "custom_category"),
)


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
	"""{employee field: allowed values} read off a Settings document or dict."""
	getter = settings.get if hasattr(settings, "get") else lambda k: None
	rule = {}
	for table, child_field, employee_field in LISTS:
		rule[employee_field] = picked_values(getter(table), child_field)
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


# Open-ended, but not unbounded. A mistyped 3650 would sweep ten years of work
# into one payment, and a payment already sent is the expensive thing to undo. A
# month is longer than any pay period this app pays on.
MAX_SPAN_DAYS = 31


def send_window(weekday, start_weekday, week_len, days=None, since_anchor=0):
    """(days back to the window start, days the window spans) for one work date.

    Two things a send can cover, and the caller picks by passing `days` or not:

    * the configured pay week (days is None) -- the default, and what payroll
      has always received. The window is found from the weekday, and the
      function returns None when the date falls in the gap of a pay week
      shorter than seven days: that gap is why Monday work on a
      Tuesday-to-Sunday week could never be sent, and the caller is expected to
      report those dates rather than drop them.
    * a chosen span of `days` -- one day, five, a fortnight. The weekday is not
      consulted at all: the operator picked the range, and snapping it to a
      configured week would pay days they did not choose and leave out days they
      did. There is no gap, so the orphan weekday sends like any other.

    A span tiles forward from the start of the range chosen, which is what
    `since_anchor` counts days from. Anchoring each date's window on itself
    instead would overlap the windows -- with a span of five, the 28th would
    open 28th-1st and the 29th would open 29th-2nd, and both would claim the
    30th. Only the first would get it, and which rows landed on which payment
    would depend on the order the dates came back from the database. A span of
    one is the same window whatever the anchor, so a single day needs none.
    """
    if days:
        return int(since_anchor or 0) % int(days), int(days)
    back = (weekday - start_weekday) % 7
    if back < week_len:
        return back, week_len
    return None


def send_span(requested_days, allowed, anchored=True):
    """(days or None, error or None) -- what one send should cover.

    Two separate questions. Whether spans are offered at all belongs to
    Settings; what this particular send covers belongs to whoever is sending. So
    a site can offer both and let the operator choose, or offer pay weeks only.

    Pay weeks stay available either way: offering spans adds an option, it never
    removes the weekly one, and a send that asks for nothing in particular
    behaves exactly as it always has.

    None means "the configured pay week". A number means that many days tiled
    from the start of the chosen range -- 1 for a single day, which is why a
    single day needs no mode of its own. Anything that is not a usable number of
    days is refused rather than rounded into one: the operator asked to pay a
    particular range, and paying a different one would hand payroll documents
    covering dates nobody chose.

    A span of more than one day needs a range to tile from, so it is refused
    when `anchored` is false. Picking an anchor on its behalf -- today, or the
    earliest work date, which differs per worker -- would put the same day on
    different payments for different people, and re-running the same send later
    would draw the boundaries somewhere else.
    """
    text = str(requested_days if requested_days is not None else "").strip()
    if text.lower() in ("", "0", "none", "false"):
        return None, None
    if str(allowed if allowed is not None else "").strip().lower() in ("", "0", "false", "none"):
        return None, ("Sending a chosen range of days is switched off. Tick "
                      "\u201cAlso allow sending a chosen range of days\u201d in Work "
                      "Management Settings to use it.")
    try:
        days = int(float(text))
    except (TypeError, ValueError):
        return None, "%s is not a number of days." % text
    if days < 1:
        return None, "A send has to cover at least one day."
    if days > MAX_SPAN_DAYS:
        return None, "One payment can cover at most %d days; %d were asked for." % (MAX_SPAN_DAYS, days)
    if days > 1 and not anchored:
        return None, ("Choose the date range first -- a span of %d days has to start "
                      "somewhere." % days)
    return days, None
