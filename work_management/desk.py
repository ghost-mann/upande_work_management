"""Keep the app's desk surfaces attached to the app, and in step with its files.

Three surfaces — the workspaces, the v16 sidebar and the apps-screen/desktop icon
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

This module repairs that on install and on every migrate, for every workspace
the app ships: it re-points a mis-attributed workspace at this app and
force-imports the shipped definition, the same way
``install.adopt_existing_custom_doctypes()`` adopts doctypes that were built in
the UI before the app existed.

It also owns the navigation block. The parent workspace's whole body is a
``Custom HTML Block`` tile grid, matching the navigation blocks used elsewhere at
Upande. That cannot ship as a module fixture — ``Custom HTML Block`` is not in
Frappe's importable doctypes, so ``sync_all()`` walks straight past it — hence
the upsert in :func:`ensure_nav_block`, wired to ``before_migrate`` so the block
exists by the time the workspace referencing it is imported.
"""

import json
import pathlib

import frappe

from work_management.migrating import DESK_STEP, without_aborting_the_migrate

APP = "work_management"
MODULE = "Work Management"
WORKSPACE = "Work Management"
SIDEBAR = "Work Management"
NAV_BLOCK = "Work Management Navigation"

HERE = pathlib.Path(__file__).resolve().parent
WORKSPACE_DIR = HERE / "work_management" / "workspace"
WORKSPACE_JSON = WORKSPACE_DIR / "work_management" / "work_management.json"
SIDEBAR_JSON = HERE / "workspace_sidebar" / "work_management.json"
BLOCK_DIR = HERE / "custom_html_block"
BLOCK_SLUG = "work_management_navigation"

COUNTED = ("links", "shortcuts", "custom_blocks")


# ------------------------------------------------------------------ decision


def shipped_counts(shipped):
	"""How much of each child table the shipped definition carries."""
	return {key: len(shipped.get(key) or []) for key in COUNTED}


def shipped_link_count(shipped):
	"""Kept for callers that only care about links."""
	return len(shipped.get("links") or [])


def workspace_repair_reason(record, present, shipped):
	"""Why a workspace needs the shipped definition forced onto it, or None.

	Pure, so the rule can be tested without a site. Ordered most fundamental
	first: a wrong module is worth reporting even when the content is also wrong.

	Content is compared against the shipped file rather than against zero. The
	parent workspace's body is a single custom block and carries no links at all,
	so "has no links" cannot mean "broken" — only "does not match what the app
	ships" can. That also means a change to a shipped workspace applies without
	anyone having to remember to bump `modified` in the JSON.
	"""
	if record is None:
		return "missing"
	if record.get("module") != MODULE:
		return "module"
	if record.get("app") != APP:
		return "app"
	if (record.get("parent_page") or "") != (shipped.get("parent_page") or ""):
		return "parent"
	wanted = shipped_counts(shipped)
	for key in COUNTED:
		if present.get(key, 0) != wanted[key]:
			return "stale"
	return None


# --------------------------------------------------------------- nav block


def _block_sources():
	base = BLOCK_DIR / BLOCK_SLUG
	out = {}
	for field, ext in (("html", "html"), ("style", "css"), ("script", "js")):
		out[field] = (base.with_suffix(f".{ext}")).read_text(encoding="utf-8")
	return out


def ensure_nav_block():
	"""Create or refresh the navigation block from the app's own files.

	Overwrites every time, deliberately: the files in the app are the source of
	truth. Anyone editing the block in the UI should expect the next migrate to
	reset it — edit the files instead.
	"""
	if not frappe.db.exists("DocType", "Custom HTML Block"):
		return None
	if not (BLOCK_DIR / f"{BLOCK_SLUG}.html").exists():
		return None

	if frappe.db.exists("Custom HTML Block", NAV_BLOCK):
		doc = frappe.get_doc("Custom HTML Block", NAV_BLOCK)
	else:
		doc = frappe.new_doc("Custom HTML Block")
		doc.name = NAV_BLOCK
	doc.update(_block_sources())
	# Public, and readable by anyone who can reach the workspace. Per-tile role
	# gating happens in the block's own script; putting roles here instead would
	# hide the whole grid rather than the one tile that needs hiding.
	doc.private = 0
	doc.set("roles", [])
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return NAV_BLOCK


# -------------------------------------------------------------------- repair


def workspace_definitions():
	"""Every workspace this app ships, as (name, path, shipped dict)."""
	for path in sorted(WORKSPACE_DIR.glob("*/*.json")):
		shipped = json.loads(path.read_text())
		if shipped.get("doctype") != "Workspace":
			continue
		yield shipped["name"], path, shipped


def _present_counts(name):
	return {
		"links": frappe.db.count("Workspace Link", {"parent": name}),
		"shortcuts": frappe.db.count("Workspace Shortcut", {"parent": name}),
		"custom_blocks": frappe.db.count("Workspace Custom Block", {"parent": name}),
	}


def _force_import(path):
	from frappe.modules.import_file import import_file_by_path

	if not path.exists():
		return False
	import_file_by_path(str(path), force=True)
	return True


def _adopt(name, shipped):
	"""Point a mis-attributed workspace at this app before re-importing it.

	Without this the import would still land, but anything already keyed off the
	old module — the desktop icon in particular — keeps pointing at the wrong
	app until it is rebuilt.
	"""
	frappe.db.set_value(
		"Workspace",
		name,
		{
			"module": MODULE,
			"app": APP,
			"parent_page": shipped.get("parent_page") or "",
		},
		update_modified=False,
	)


def _refresh_desktop_icon():
	"""Rebuild this app's desktop icons from the now-correct workspaces.

	create_desktop_icons() never revisits an icon that already exists, so a
	stale one filed under the wrong app has to go first. Only icons pointing at
	this app's own workspaces are touched.
	"""
	if not frappe.db.exists("DocType", "Desktop Icon"):
		return  # v15: the apps screen is built from hooks alone.

	ours = [name for name, _path, _shipped in workspace_definitions()]
	for name in frappe.get_all(
		"Desktop Icon",
		or_filters=[{"link_to": ["in", ours]}, {"label": ["in", ours]}, {"app": APP}],
		pluck="name",
	):
		frappe.delete_doc("Desktop Icon", name, force=True, ignore_permissions=True)

	from frappe.desk.doctype.desktop_icon.desktop_icon import create_desktop_icons

	return without_aborting_the_migrate(
		create_desktop_icons, "rebuild the desktop icons", title=DESK_STEP
	)


def sync_workspaces():
	"""Make every shipped workspace this app's, carrying what the app ships."""
	repaired = {}
	for name, path, shipped in workspace_definitions():
		record = frappe.db.get_value(
			"Workspace", name, ["name", "module", "app", "parent_page"], as_dict=True
		)
		present = _present_counts(name) if record else dict.fromkeys(COUNTED, 0)
		reason = workspace_repair_reason(record, present, shipped)
		if not reason:
			continue
		if record:
			_adopt(name, shipped)
		if _force_import(path):
			_adopt(name, shipped)
			repaired[name] = reason
	return repaired


def sync_sidebar():
	"""The v16 sidebar, which does not exist on v15 and is skipped there."""
	if not frappe.db.exists("DocType", "Workspace Sidebar"):
		return None
	_force_import(SIDEBAR_JSON)
	return SIDEBAR


def sync():
	"""Repair every desk surface. Safe to run repeatedly."""
	ensure_nav_block()
	repaired = sync_workspaces()
	sync_sidebar()
	if repaired:
		_refresh_desktop_icon()
		frappe.clear_cache()
		for name, reason in repaired.items():
			print(f"Work Management: repaired workspace {name} ({reason})")
	return repaired
