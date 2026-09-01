"""Remove the two consultant controls that nothing ever read.

Both promised a rule the app does not implement, and a promise in a settings
screen is worse than an absence: somebody ticks it and expects an effect.

  `require_consultant_approval`   a checkbox labelled "Require consultant
                                  approval for future-week plans", default on,
                                  with zero readers anywhere in the app, the
                                  mirror scripts or the web pages.
  `planner_weekly_consultant`     a stage of kind `Gate`. `chain_for()` filtered
                                  Gates out of the workflow and nothing else read
                                  the kind, so the stage was inert.

The consultant control that works is untouched: `consultant_state` on each
Master Plan Activity, where a consultant settles individual activities and the
planner only offers ones marked OK. `Master Plan: Consultant` also stays, as a
real workflow step that can now be switched off like any other.

The checkbox leaves the shipped doctype JSON, so migrate stops rendering it. Its
column is left in the table -- Frappe does not drop columns and neither should a
patch, since a column nobody reads costs nothing while a dropped one cannot be
recovered if this turns out to have been wrong.

The stage row has to go explicitly. `configured_stages()` treats a row whose key
the code has never heard of as a step like any other, which is the whole point of
making the chain configurable -- so leaving this one behind would leave a step in
the Settings grid carrying a `kind` that is no longer even an option.
"""

import frappe

STAGE = "planner_weekly_consultant"


def execute():
	if not frappe.db.exists("DocType", "Work Management Approval Stage"):
		return

	rows = frappe.get_all(
		"Work Management Approval Stage",
		filters={"parenttype": "Work Management Settings", "stage": STAGE},
		pluck="name",
	)
	if not rows:
		return

	for name in rows:
		frappe.db.delete("Work Management Approval Stage", {"name": name})
	frappe.db.commit()
	print("dropped %d inert %s stage row(s)" % (len(rows), STAGE))
