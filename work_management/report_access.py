# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Who may open the Worker Task Day report, decided by this site's own chain.

The client asked for the general manager to be able to read it. The obvious
implementation -- adding "General Manager" to the report's `roles` in its JSON --
is the exact thing `test_no_shipped_roles` exists to prevent:

    Installing this app must not create another organisation's job titles.

"General Manager" is one of the five Kaitet role names that were removed for
that reason, and a Report's `roles` rows are Links to Role, so naming one a site
has not got breaks the import rather than degrading. A site that calls the job
"Operations Director" would get nothing from a hardcoded name anyway.

So it is read from configuration, the way everything else in this app is. Every
role the configured approval chain names for an APPROVAL step is granted the
report: those are the people who sign this pipeline's work off, whoever they are
at a given company, and a report of what was done is the thing they need to sign
it off against. The submit steps are deliberately not swept in -- raising work is
not overseeing it.

Additive and idempotent: a role already listed is left alone, a role the site has
not got is skipped rather than raising, and nothing is ever removed -- the three
roles the report ships with keep it whatever the chain says.
"""

import frappe

REPORT = "Worker Task Day"


#: `effective_chain()` distinguishes "you did not say" from "there is no
#: configuration": passing settings=None explicitly resolves against the SHIPPED
#: catalogue and never reads the site. Omitting the argument is what reads
#: Settings. Getting that backwards makes this grant System Manager on every
#: site and nothing else, silently -- which it did, once.
_SITE = object()


def oversight_roles(settings=_SITE):
	"""The roles this site's chain names for approval steps. Reads; never writes.

	Disabled steps count. A step switched off today may be switched on next
	month, and losing report access when somebody toggles a setting is the kind
	of surprise that gets blamed on the report.
	"""
	from work_management import approvals

	chain = (approvals.effective_chain() if settings is _SITE
		else approvals.effective_chain(settings=settings))
	roles = set()
	for step in chain:
		if step.get("kind") == "Approval" and step.get("role"):
			roles.add(step["role"])
	return sorted(roles)


def grant_report_roles(report=REPORT, settings=_SITE):
	"""Give this site's approvers the report. Returns the roles added.

	Runs on every migrate, so a chain reconfigured in Settings is reflected
	without anybody remembering this exists.

	The rows are written DIRECTLY rather than through `doc.save()`. Saving a
	standard Report on a site with developer_mode on re-exports its JSON into the
	app -- rewriting `creation`, adding whatever fields the running Frappe
	version has, and committing one site's role grants into everybody's copy.
	This is a permission grant, not an edit to the report's definition, and the
	definition should not move.
	"""
	if not frappe.db.exists("Report", report):
		return []

	already = set(frappe.db.get_all("Has Role",
		filters={"parent": report, "parenttype": "Report"}, pluck="role"))
	added = []
	for role in oversight_roles(settings):
		if role in already:
			continue
		if not frappe.db.exists("Role", role):
			# The chain may name a role nobody has created yet -- that is a
			# configuration state, not an error, and the next migrate will pick
			# it up once somebody makes it.
			continue
		row = frappe.new_doc("Has Role")
		row.parent = report
		row.parenttype = "Report"
		row.parentfield = "roles"
		row.role = role
		row.flags.ignore_permissions = True
		row.insert(ignore_permissions=True)
		added.append(role)
	if added:
		frappe.clear_cache(doctype=report)
	return added


def after_migrate():
	added = grant_report_roles()
	if added:
		print("Work Management: %s may now read '%s'" % (", ".join(added), REPORT))
