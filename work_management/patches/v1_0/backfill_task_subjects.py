"""Fill task_subject on rows written before the column existed.

`fetch_from` populates on save, and nothing is going to re-save the rows already
there -- 1,578 planner requests and every master plan activity on live. Without
this the new column is empty on all of them, so the desk grid would show blanks
where it used to show at least an id, which is worse than what it replaced.

Only empty cells are filled. A row that already names its task is already right,
and overwriting it would undo a correction somebody made deliberately.

One UPDATE per table rather than a row at a time: these are submitted doctypes,
a saved document would be refused, and set_value per row would be thousands of
round trips for a column the database can fill in one statement.
"""

import frappe

CARRIERS = ("Work Management Master Plan Activity", "Work Management Planner")


def execute():
	for doctype in CARRIERS:
		if not frappe.db.exists("DocType", doctype):
			continue
		if not frappe.db.has_column(doctype, "task_subject"):
			# the field arrives with this release; a site mid-migrate may not have
			# synced the doctype yet, and asking for a missing column is a hard
			# SQL error that would take the whole migrate down
			continue
		filled = frappe.db.sql(
			f"""
			UPDATE `tab{doctype}` row
			INNER JOIN `tabTask` task ON task.name = row.task
			SET row.task_subject = task.subject
			WHERE IFNULL(row.task_subject, '') = ''
			  AND IFNULL(task.subject, '') != ''
			"""
		)
		count = frappe.db.sql(
			f"SELECT COUNT(*) FROM `tab{doctype}` WHERE IFNULL(task_subject, '') != ''"
		)[0][0]
		print(f"Work Management: {doctype} -- {count} row(s) now name their activity")

		orphans = frappe.db.sql(
			f"""
			SELECT COUNT(*) FROM `tab{doctype}` row
			LEFT JOIN `tabTask` task ON task.name = row.task
			WHERE IFNULL(row.task, '') != '' AND task.name IS NULL
			"""
		)[0][0]
		if orphans:
			# a row naming a task that no longer exists. Left as it is and reported:
			# the id it carries is the only record of what was planned, and
			# inventing a name for it would bury that.
			print(
				f"Work Management: {doctype} -- {orphans} row(s) name a task that no "
				"longer exists; left with the id they carry"
			)
	frappe.db.commit()
