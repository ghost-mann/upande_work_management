"""Keep the app's desk surfaces attached to the app.

Three surfaces — the workspace, the v16 sidebar and the apps-screen/desktop icon
— are all derived from two fields on one record: ``Workspace.module`` and
``Workspace.app``. Frappe joins ``Workspace.module`` to ``Module Def.app_name``
to decide which app a workspace belongs to (``frappe/boot.py``,
``load_desktop_data``), ``create_desktop_icons_from_workspace()`` reads the same
pair, and ``get_workspaces()`` raises ``PermissionError`` for a user who has no
access to the owning module. Get those two fields wrong and all three surfaces
disappear at once.

They go wrong on their own. ``frappe/modules/import_file.py`` skips a standard
JSON whenever the record already in the database carries a ``modified`` newer
than the one in the file::

    if is_db_timestamp_latest and doc["doctype"] != "DocType":
        continue

So a Work Management workspace someone built in the desk — which is exactly what
the site this app was extracted from has, filed under Projects — silently beats
the one the app ships. The record survives with ``module: Projects``,
``app: erpnext`` and none of the app's cards, and nothing anywhere reports a
problem.

This module repairs that on install and on every migrate: it re-points a
mis-attributed workspace at this app and force-imports the shipped definition,
the same way ``install.adopt_existing_custom_doctypes()`` adopts doctypes that
were built in the UI before the app existed. A workspace that is already correct
and populated is left alone, so deliberate customisation survives.
"""

import pathlib

import frappe

APP = "work_management"
MODULE = "Work Management"
WORKSPACE = "Work Management"
SIDEBAR = "Work Management"

HERE = pathlib.Path(__file__).resolve().parent
WORKSPACE_JSON = HERE / "work_management" / "workspace" / "work_management" / "work_management.json"
SIDEBAR_JSON = HERE / "workspace_sidebar" / "work_management.json"


# ------------------------------------------------------------------ decision


def shipped_link_count(shipped):
	"""How many links the shipped workspace defines."""
	return len(shipped.get("links") or [])


def workspace_repair_reason(record, link_count, shipped_links=None):
	"""Why the workspace needs the shipped definition forced onto it, or None.

	Pure, so the rule can be tested without a site. Ordered most fundamental
	first: a wrong module is worth reporting even when the record is also empty.

	`shipped_links` closes the other half of the problem. Bumping `modified` in
	the JSON is the conventional way to make Frappe apply a change, and it is
	easy to forget, so a workspace carrying a different number of links from the
	one the app ships is resynced regardless of timestamps. This app owns this
	workspace; a card it ships is meant to be there.
	"""
	if record is None:
		return "missing"
	if record.get("module") != MODULE:
		return "module"
	if record.get("app") != APP:
		return "app"
	if not link_count:
		return "empty"
	if shipped_links is not None and link_count != shipped_links:
		return "stale"
	return None


# -------------------------------------------------------------------- repair


def _force_import(path):
	from frappe.modules.import_file import import_file_by_path

	if not path.exists():
		return False
	import_file_by_path(str(path), force=True)
	return True


def _adopt_workspace():
	"""Point a mis-attributed workspace at this app before re-importing it.

	Without this the import would still land, but anything already keyed off the
	old module — the desktop icon in particular — keeps pointing at the wrong
	app until it is rebuilt.
	"""
	frappe.db.set_value(
		"Workspace",
		WORKSPACE,
		{"module": MODULE, "app": APP},
		update_modified=False,
	)


def _refresh_desktop_icon():
	"""Rebuild this app's desktop icon from the now-correct workspace.

	create_desktop_icons() never revisits an icon that already exists, so a
	stale one filed under the wrong app has to go first. Only icons pointing at
	this app's own workspace are touched.
	"""
	if not frappe.db.exists("DocType", "Desktop Icon"):
		return  # v15: the apps screen is built from hooks alone.

	for name in frappe.get_all(
		"Desktop Icon",
		or_filters=[{"link_to": WORKSPACE}, {"label": WORKSPACE}],
		pluck="name",
	):
		frappe.delete_doc("Desktop Icon", name, force=True, ignore_permissions=True)

	from frappe.desk.doctype.desktop_icon.desktop_icon import create_desktop_icons

	create_desktop_icons()


def sync_workspace():
	"""Make sure the workspace is this app's, and carries what the app ships."""
	import json

	record = frappe.db.get_value(
		"Workspace", WORKSPACE, ["name", "module", "app"], as_dict=True
	)
	link_count = (
		frappe.db.count("Workspace Link", {"parent": WORKSPACE}) if record else 0
	)
	shipped = json.loads(WORKSPACE_JSON.read_text()) if WORKSPACE_JSON.exists() else None
	reason = workspace_repair_reason(
		record, link_count, shipped_links=shipped_link_count(shipped) if shipped else None
	)
	if not reason:
		return None

	if record:
		_adopt_workspace()
	if not _force_import(WORKSPACE_JSON):
		return None

	if shipped and shipped_link_count(shipped):
		# The import writes the record; re-assert attribution in case the file
		# is ever exported from a site that had it wrong.
		_adopt_workspace()
	return reason


def sync_sidebar():
	"""The v16 sidebar, which does not exist on v15 and is skipped there."""
	if not frappe.db.exists("DocType", "Workspace Sidebar"):
		return None
	_force_import(SIDEBAR_JSON)
	return SIDEBAR


def sync():
	"""Repair every desk surface. Safe to run repeatedly."""
	reason = sync_workspace()
	sync_sidebar()
	if reason:
		_refresh_desktop_icon()
		frappe.clear_cache()
		print(f"Work Management: repaired the desk workspace ({reason})")
	return reason
