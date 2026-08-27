"""Copy this app's data from one site to another, document by document.

    bench --site TARGET execute work_management.scripts.migrate_site_data.preflight \
        --kwargs "{'path': 'wm_snapshot.json'}"
    bench --site TARGET execute work_management.scripts.migrate_site_data.load \
        --kwargs "{'path': 'wm_snapshot.json', 'dry_run': True}"

Restoring a database backup is the better way to move a whole site and should be
preferred: it carries the employees, warehouses, tasks and cost centres this
app's rows point at, and it preserves names and docstatus exactly. This exists
for the other case -- a target that already holds those masters and needs only
this app's documents, which is what an API-only migration can actually do.

Three things it will not compromise on:

Names. Work Payment Line.actuals names an Actuals document, Actuals.assignment
names an Assigner one, and so on down the chain. A document renamed on the way
in breaks every link pointing at it, so names come across as they are and a
name already on the target is skipped rather than duplicated under a new one.

docstatus and workflow state. 3,974 of the live documents are submitted, and
they sit in states like CONFIRMED and Approved. A document does not get to
re-enact its life on the way in: doc.insert() makes a draft, doc.submit() is
governed by the workflow, and setting the state directly is refused --

    WorkflowPermissionError: Workflow State transition not allowed from
    Draft to Approved

-- so rows are written with db_insert(), which is the primitive a data
migration wants. Name, docstatus, workflow state, creation and owner all land
exactly as they were, and none of the app's own hooks fire to recompute an
amount that was already decided on the source site.

Rows nobody can point at. Every external link is checked before anything is
written, and preflight refuses rather than importing documents whose employee
or warehouse does not exist on the target -- a dangling link is not visible on
a screen, it is a report that quietly counts less than it should.
"""

import json
import os

import frappe

# Insert order: each doctype links only backwards, so a parent's links are
# already there when it lands. Children travel inside their parent document.
ORDER = [
	"Work Task Rate",
	"Work Management Master Plan",
	"Work Management Planner",
	"Work Management Assigner",
	"Work Management Actuals",
	"Work Management Payment",
	"Work Rate Recalc Run",
]

# Fields the target rebuilds for itself. Everything else -- docstatus,
# workflow_state, creation, modified, owner -- comes across untouched, because
# an exact copy is the whole point.
DROP = {"doctype", "_user_tags", "_comments", "_assign", "_liked_by", "_seen"}


def _snapshot(path):
	with open(path) as handle:
		return json.load(handle)


def external_links(snapshot):
	"""{doctype: {names}} for every link these documents point at outside the app."""
	found = {}
	for doctype, docs in snapshot["parents"].items():
		meta = frappe.get_meta(doctype) if frappe.db.exists("DocType", doctype) else None
		if not meta:
			continue
		links = {f.fieldname: f.options for f in meta.fields
		         if f.fieldtype == "Link" and f.options}
		for doc in docs:
			for fieldname, target in links.items():
				value = doc.get(fieldname)
				if value and not target.startswith(("Work ", "WM ")):
					found.setdefault(target, set()).add(value)
	return found


def preflight(path, verbose=True):
	"""What the target is missing. Nothing is written."""
	snapshot = _snapshot(path)
	report = {"missing_doctypes": [], "missing_links": {}, "already_present": {}, "to_insert": {}}

	for doctype in ORDER:
		if not frappe.db.exists("DocType", doctype):
			report["missing_doctypes"].append(doctype)
			continue
		names = [d["name"] for d in snapshot["parents"].get(doctype, [])]
		here = set(frappe.get_all(doctype, pluck="name"))
		report["already_present"][doctype] = len([n for n in names if n in here])
		report["to_insert"][doctype] = len([n for n in names if n not in here])

	for target, names in sorted(external_links(snapshot).items()):
		if not frappe.db.exists("DocType", target):
			report["missing_links"][target] = "DOCTYPE ABSENT (%d names)" % len(names)
			continue
		here = set(frappe.get_all(target, pluck="name"))
		missing = sorted(n for n in names if n not in here)
		if missing:
			report["missing_links"][target] = missing

	if verbose:
		print("target site:", frappe.local.site)
		for doctype in ORDER:
			if doctype in report["missing_doctypes"]:
				print("  %-34s DOCTYPE ABSENT — install the app first" % doctype)
			else:
				print("  %-34s %5d to insert, %5d already here" % (
					doctype, report["to_insert"][doctype], report["already_present"][doctype]))
		if report["missing_links"]:
			print("\n  links with nothing to point at on this target:")
			for target, missing in report["missing_links"].items():
				count = missing if isinstance(missing, str) else "%d of them, e.g. %s" % (
					len(missing), ", ".join(missing[:3]))
				print("    %-16s %s" % (target, count))
			print("\n  REFUSING: bring those across first, or the imported rows dangle.")
		else:
			print("\n  every external link resolves on this target.")
	return report


def child_tables(meta):
	"""{fieldname: child doctype} for the tables one doctype carries."""
	return {f.fieldname: f.options for f in meta.fields if f.fieldtype == "Table"}


def _row(doc, doctype, extra=None):
	"""One row as the target should store it."""
	out = {"doctype": doctype}
	out.update({k: v for k, v in doc.items() if k not in DROP and not isinstance(v, list)})
	out.update(extra or {})
	return out


def write(doc, meta):
	"""Write one document and its child rows exactly as they were.

	db_insert() rather than insert(): no validation, no workflow transition, no
	hook recomputing a figure the source site already decided. The columns are
	the same on both sides, so the row is the row.
	"""
	parent = frappe.get_doc(_row(doc, meta.name))
	parent.db_insert()
	written = 1
	for fieldname, child_type in child_tables(meta).items():
		for index, kid in enumerate(doc.get(fieldname) or [], start=1):
			row = frappe.get_doc(_row(kid, child_type, {
				"parent": doc["name"], "parenttype": meta.name,
				"parentfield": fieldname, "idx": kid.get("idx") or index}))
			row.db_insert()
			written += 1
	return written


def load(path, dry_run=False, limit=None, only=None):
	"""Insert every document the target has not got, preserving name and docstatus."""
	snapshot = _snapshot(path)
	report = preflight(path, verbose=False)
	if report["missing_links"] or report["missing_doctypes"]:
		preflight(path)
		raise frappe.ValidationError(
			"target is not ready — see the refusal above; nothing was written")

	done, failed = {}, []
	for doctype in ORDER:
		if only and doctype not in only:
			continue
		meta = frappe.get_meta(doctype)
		here = set(frappe.get_all(doctype, pluck="name"))
		count = 0
		for doc in snapshot["parents"].get(doctype, []):
			if doc["name"] in here:
				continue
			if limit is not None and count >= limit:
				break
			count += 1
			if dry_run:
				continue
			try:
				write(doc, meta)
				frappe.db.commit()
			except Exception as exc:
				frappe.db.rollback()
				failed.append((doctype, doc["name"], str(exc)[:160]))
		done[doctype] = count
		print("  %-34s %s %d" % (doctype, "would insert" if dry_run else "inserted", count))
	if failed:
		print("\n  %d document(s) refused:" % len(failed))
		for doctype, name, why in failed[:20]:
			print("    %-30s %-22s %s" % (doctype, name, why))
	return {"inserted": done, "failed": failed}
