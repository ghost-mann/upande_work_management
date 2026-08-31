"""Record which master plan each existing request drew against.

`master_plan` arrives with this release, and every request written before it has
none. Their budget was inferred from farm plus dates -- reliable only because two
plans could not cover the same days, which is the rule this release lifts.

So this is the last moment every existing request has exactly one answer. Once
somebody raises a second overlapping plan, a request from before then cannot be
resolved at all, by this patch or by anything else.

A request with no covering plan is left null and counted: the date fallback still
resolves it, and inventing a link would be worse than leaving none. A request
with two is named rather than guessed -- that cannot happen on data written under
the old rule, but it is reported in case a site got there another way, because
guessing which budget somebody's work came from is the error this whole change
exists to prevent.
"""

import frappe

from work_management.master_plan import resolve_master_plan


def execute():
	if not frappe.db.has_column("Work Management Planner", "master_plan"):
		# the field arrives with this release; a site mid-migrate may not have
		# synced the doctype yet, and asking for a missing column is a hard SQL
		# error that would take the whole migrate down
		return

	rows = frappe.db.sql(
		"""
		SELECT name, farm, from_date, to_date FROM `tabWork Management Planner`
		WHERE IFNULL(master_plan, '') = '' AND IFNULL(farm, '') != ''
		  AND from_date IS NOT NULL AND to_date IS NOT NULL
		""",
		as_dict=True,
	)

	linked = 0
	unresolved = 0
	ambiguous = []
	for row in rows:
		candidates = frappe.db.sql_list(
			"""
			SELECT name FROM `tabWork Management Master Plan`
			WHERE farm = %(f)s AND IFNULL(workflow_state, '') != 'Rejected'
			  AND period_from <= %(a)s AND period_to >= %(b)s
			""",
			{"f": row.farm, "a": row.from_date, "b": row.to_date},
		)
		name, _reason = resolve_master_plan("", candidates)
		if name:
			# set_value: Planner is submittable and a submitted document will not
			# accept a save. The farm and dates are not being changed, only the
			# link that was always implied by them.
			frappe.db.set_value(
				"Work Management Planner", row.name, "master_plan", name,
				update_modified=False,
			)
			linked = linked + 1
		elif len(candidates) > 1:
			ambiguous.append((row.name, sorted(candidates)))
		else:
			unresolved = unresolved + 1

	frappe.db.commit()
	print(f"Work Management: linked {linked} request(s) to the plan they drew against")
	if unresolved:
		print(
			f"Work Management: {unresolved} request(s) have no covering plan; left "
			"unlinked, and their dates still resolve them"
		)
	for request, plans in ambiguous:
		print(
			f"Work Management: {request} is covered by {', '.join(plans)} -- "
			"left unlinked rather than guessed; set it by hand"
		)
