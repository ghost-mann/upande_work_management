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

# (Settings fieldname, the Employee field it is matched against).
LISTS = (
	("tw_employment_types", "employment_type"),
	("tw_designations", "designation"),
	("tw_categories", "custom_category"),
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


def rule_from(settings):
	"""{employee field: allowed values} read off a Settings document or dict."""
	getter = settings.get if hasattr(settings, "get") else lambda k: None
	return {field: parse_list(getter(box)) for box, field in LISTS}


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
