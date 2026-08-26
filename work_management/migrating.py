"""Keep a migrate on its feet when one step, or one record, cannot succeed.

`bench migrate` runs this app's patches and its after_migrate hooks against
sites nobody here has seen. A step that cannot succeed on one of them is a
fact of life; a step that takes the whole migrate down with it leaves the site
half-upgraded, which is worse than whatever the step was trying to do.

So both helpers here trade completeness for progress, in writing: the failure
is printed and logged, the run carries on, and the caller gets back what it
needs to report honestly at the end.
"""

import frappe


DESK_STEP = "Work Management: desk rebuild step failed"
PATCH_RECORD = "Work Management: a record was skipped during migrate"


def without_aborting_the_migrate(action, what, title=DESK_STEP):
	"""Run one migrate step, refusing to let it take the whole migrate down.

	Frappe 16.27's create_desktop_icons_from_workspace() files each workspace
	icon with link_type "Workspace Sidebar" while link_to names a Workspace, so
	the insert fails link validation. Its own handler then reports the failure
	through frappe.error_log(...) — which is a list, not a function — and the
	TypeError that raises replaces the original error and escapes, so
	`bench migrate` stops partway through with a message about neither problem.

	None of that is ours to fix, but all of it reaches a site through this
	app's after_migrate hook. An apps-screen icon we could not rebuild is a
	cosmetic loss on one screen; a migrate that halts leaves the site in a state
	nobody asked for. So the step is allowed to fail, loudly and in writing.

	Returns None on success, or the message it recorded.
	"""
	try:
		action()
	except Exception as exc:
		note = f"Work Management: could not {what} — {type(exc).__name__}: {exc}"
		print(note)
		try:
			frappe.log_error(title=title, message=note)
		except Exception:
			pass  # Logging must never be the thing that aborts a migrate either.
		return note
	return None


def each_without_aborting(items, work, what):
	"""Run `work(item)` for every item, surviving a failure on any one of them.

	A patch walks records the app has never seen: a legacy value that will not
	validate, a link whose target was deleted, a duplicate that predates the
	unique constraint. Raising on the first of those aborts `bench migrate` for
	the whole site, so the ninety records that would have upgraded cleanly do
	not, and the site is left half-migrated over one bad row.

	Each item's failure is reported with the item named, so migrate output says
	which record to go and fix rather than only that something went wrong.

	No rollback between items, which puts one requirement on `work`: an item
	must confine itself to a single document write. Rolling the transaction
	back would discard the records that did succeed, and MariaDB only undoes
	the statement that failed -- so an item that writes twice can fail halfway
	and leave the first write standing. Both patches are shaped to write once
	per record for that reason, and both are re-runnable, so a skipped record
	is picked up by the next migrate once whatever made it fail is dealt with.

	Returns (how many items the work completed, the notes for the ones it did not).
	"""
	done, notes = 0, []
	for item in items:
		note = without_aborting_the_migrate(
			lambda: work(item), f"{what} {item}", title=PATCH_RECORD
		)
		if note:
			notes.append(note)
		else:
			done = done + 1
	return done, notes
