"""Make the desk print what a task is called, not what it is filed under.

The web screens resolve this themselves, through `taskName()` and
wm_dashboard's `task_names` map. The desk had no such thing: a Link field to
Task renders the docname, and on a site whose Task autoname is a series that
docname is `TASK-2026-00131`. The subject -- FERTILIZER APPLICATION -- is what
a person recognises.

Task already declares `title_field = "subject"`; what it does not set is
`show_title_field_in_link`. With that on, frappe shows the title wherever a
Task is linked -- list views, the link picker, link previews, form load, print
formats -- while still storing the docname. One setting, rather than a fetched
subject column on each of the four doctypes here that link a Task.

That is also why this is not simply better than the earlier per-doctype
columns: those were added to *grids*, where the child row shows a column rather
than a rendered link, and they stay useful. This covers everything else.

A Property Setter rather than an edit to ERPNext's shipped JSON, following
approvals.stage_picker_options() and taxonomy.apply_labels(). frappe reads this
particular flag from a Property Setter deliberately -- see frappe/boot.py,
which unions the doctypes declaring it with the setters that set it.

Worth being explicit about the reach: Task belongs to ERPNext's Projects
module, so this changes how a task reads there too. It is a display change in
one direction -- an id becomes a name - and this app already owns part of Task
(its rate fields, and a doc_event on it), so it is not a stranger to it.
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "Task"):
		return

	meta = frappe.get_meta("Task")
	if not meta.title_field:
		# nothing to show in place of the id; leave it alone rather than turning
		# on a flag that would render blanks
		print("Task declares no title_field -- leaving links as they are")
		return
	if meta.show_title_field_in_link:
		return

	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	make_property_setter("Task", None, "show_title_field_in_link", 1, "Check",
		for_doctype=True, validate_fields_for_doctype=False)
	frappe.clear_cache(doctype="Task")

	# say what it will now read as, so the log shows the change rather than just
	# claiming one
	named = frappe.db.count("Task", {"subject": ["!=", ""]})
	series = frappe.db.sql("""
		SELECT COUNT(*) FROM `tabTask`
		WHERE subject IS NOT NULL AND subject != '' AND subject != name
	""")[0][0]
	print("Task links now show `%s`: %d tasks have one, %d of them differ from the docname"
		% (meta.title_field, named, series))
