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

from work_management import taxonomy
# hooks.py imports nothing, so this is safe -- and taking the route from there
# rather than repeating it means the apps-screen entry and the Desktop Icon
# record cannot drift apart into two different destinations.
from work_management.hooks import app_home as APP_HOME
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

# Navigation entries whose label names a level, by what they point at. A
# Workspace Link and a Workspace Sidebar Item are records, not doctype fields,
# so none of the Property Setters that relabel the forms reaches them -- they
# are relabelled in place, after every import, by relabel_navigation(). Keyed on
# link_to rather than on the label, because after the first relabel the label is
# no longer the shipped one and would not be found again.
NAV_LABELS = {
	# Upande Core's doctype. Listed so the sidebar entry pointing at its list
	# carries the project's own word for the level.
	"Farm": "{top_plural}",
	"Work Management Section": "{section_plural}",
}


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


def nav_label(link_to, names):
	"""What a navigation entry pointing at `link_to` should read, or None.

	None, rather than the label unchanged, so a caller cannot mistake "this
	entry names no level" for "write this back".
	"""
	template = NAV_LABELS.get(link_to)
	return taxonomy.label_for(template, names) if template else None


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


# Doctypes this app used to ship, and what took their place. A navigation entry
# on a site still names the old one long after the app has stopped shipping it,
# and a Link whose target does not exist is a 404 with the doctype's name in it.
RETIRED = {
	# Farms became Upande Core's records; move_farms_to_upande_core retires ours.
	"Work Management Farm": "Farm",
}


def plan_retired_repoint(rows, retired=None):
	"""[(name, replacement)] for navigation rows naming a doctype we retired.

	Pure, so the rule can be read and tested without a site.
	"""
	retired = RETIRED if retired is None else retired
	return [
		(row["name"], retired[row["link_to"]])
		for row in rows
		if row.get("link_to") in retired
	]


def repoint_retired_links():
	"""Aim any navigation entry naming a retired doctype at its replacement.

	This lives here, and runs from sync() at every after_migrate, rather than in
	the patch that did the retiring -- because Frappe records a patch by name and
	never runs it again. move_farms_to_upande_core shipped without this step and
	gained it one commit later, so on a site that migrated in between the repair
	could never arrive: the doctype was gone, the Setup workspace still had a
	"Farms" link pointing at it, and clicking it said
	`DocType Work Management Farm not found`. A once-only patch is the wrong home
	for a repair; an idempotent after_migrate step is right, and fixes those
	sites on their next migrate without anyone having to know they were affected.

	Shortcuts are included, which the patch's own version missed: a Workspace
	Shortcut carries link_to exactly as a Workspace Link does, and 404s the same.
	"""
	moved = 0
	for doctype in ("Workspace Link", "Workspace Shortcut", "Workspace Sidebar Item"):
		if not frappe.db.exists("DocType", doctype):
			continue  # v15 has no Workspace Sidebar
		rows = frappe.get_all(
			doctype,
			filters={"link_to": ["in", list(RETIRED)]},
			fields=["name", "link_to"],
		)
		for name, replacement in plan_retired_repoint(rows):
			frappe.db.set_value(doctype, name, "link_to", replacement, update_modified=False)
			print(f"Work Management: repointed {doctype} {name} at {replacement}")
			moved += 1
	if moved:
		frappe.clear_cache()
	return moved


def plan_link_visibility(rows, available):
	"""(to hide, to show) for navigation links, by whether their doctype exists.

	A link pointing at a doctype the site does not have is a 404 waiting to be
	clicked. Only DocType links are judged -- a URL or a report has no doctype
	to look up -- and the decision is reversible: a link hidden because its
	target was missing is shown again when the target comes back.

	Pure, so the rule can be tested without a site.
	"""
	hide, show = [], []
	for row in rows:
		if (row.get("link_type") or "") != "DocType" or not row.get("link_to"):
			continue
		present = row["link_to"] in available
		hidden = 1 if row.get("hidden") else 0
		if not present and not hidden:
			hide.append(row["name"])
		elif present and hidden:
			show.append(row["name"])
	return hide, show


def hide_links_to_missing_doctypes():
	"""Apply plan_link_visibility to this app's own navigation surfaces."""
	ours = [name for name, _path, _shipped in workspace_definitions()]
	changed = 0
	for doctype, parents in (("Workspace Link", ours), ("Workspace Sidebar Item", [SIDEBAR])):
		if not frappe.db.exists("DocType", doctype):
			continue  # v15 has no Workspace Sidebar
		# Workspace Link has `hidden`; Workspace Sidebar Item does not. Asking
		# for a column a doctype has not got is a hard SQL error, and inside
		# after_migrate that takes the whole migrate down -- so ask the meta
		# first rather than assuming the two child tables share a shape.
		if not frappe.get_meta(doctype).get_field("hidden"):
			continue
		rows = frappe.get_all(
			doctype,
			filters={"parent": ["in", parents]},
			fields=["name", "link_type", "link_to", "hidden"],
		)
		wanted = {r["link_to"] for r in rows if r.get("link_to")}
		available = {
			d for d in wanted if frappe.db.exists("DocType", d)
		}
		hide, show = plan_link_visibility(rows, available)
		for name in hide:
			frappe.db.set_value(doctype, name, "hidden", 1, update_modified=False)
		for name in show:
			frappe.db.set_value(doctype, name, "hidden", 0, update_modified=False)
		changed = changed + len(hide) + len(show)
	if changed:
		frappe.clear_cache()
	return changed


# The apps-screen logo. Shipped by this app rather than borrowed from a
# neighbour: upande_sensors and upande_ta each carry their own copy of the Upande
# logo instead of pointing at one another, and an icon that pointed at
# /assets/upande_webshop/... would break on a site without webshop. hooks.py
# add_to_apps_screen names the same file, so the apps screen and the desk's app
# switcher draw the same picture.
LOGO_URL = "/assets/work_management/images/work-management-logo.svg"


def desktop_icon_fields(label=None):
	"""The Desktop Icon row, in the shape every other Upande app uses.

	Read off the working icons on a real v16 site: Ecommerce (upande_webshop),
	Upande Sensors and T&A all carry icon_type "App", link_type "External", a
	real `link`, and a `logo_url` -- and all three draw their own logo on the
	apps screen. Ours was icon_type "Link" with no logo_url at all, so it drew a
	generic glyph while its neighbours drew themselves.

	This did once sit on link_type "Workspace Sidebar", after an "External"
	attempt showed nothing. That attempt had link_to and icon both null, which is
	why there was nothing to draw; those three icons are the evidence that the
	shape is fine once the link and the logo are really there.

	Pure, so the shape can be checked without a site.
	"""
	return {
		"label": label or WORKSPACE,
		"icon_type": "App",
		"link_type": "External",
		"link": APP_HOME,
		"logo_url": LOGO_URL,
		"app": APP,
		"standard": 1,
		"hidden": 0,
		# Explicitly vacated, not merely omitted. ensure_desktop_icon() updates the
		# existing record rather than replacing it, so a field left out of this
		# dict keeps whatever the old shape put there -- and a stale `link_to`
		# beside link_type "External" makes Frappe resolve it as a doctype:
		# `DocType External not found`, on a record that had just been written
		# correctly in every other respect.
		"link_to": "",
		"sidebar": "",
		"icon": "",
	}


def ensure_desktop_icon():
	"""Put this app's apps-screen icon there, correctly, and keep it that way.

	Frappe's create_desktop_icons_from_workspace() cannot do it on 16.27 (see
	without_aborting_the_migrate), and letting it fail left the icon half-made
	rather than absent -- which is worse, because a dead icon looks like a
	working one. So the icon is ours to write, the same way the navigation block
	is: overwritten every time, because the app's own definition is the truth.

	Needs the Workspace Sidebar to exist first, or link_to would not resolve.
	"""
	if not frappe.db.exists("DocType", "Desktop Icon"):
		return None  # v15: the apps screen is built from hooks alone.
	if not frappe.db.exists("Workspace Sidebar", SIDEBAR):
		return None  # sync_sidebar() has not run, or this is v15

	fields = desktop_icon_fields()
	if frappe.db.exists("Desktop Icon", WORKSPACE):
		doc = frappe.get_doc("Desktop Icon", WORKSPACE)
	else:
		doc = frappe.new_doc("Desktop Icon")
		doc.name = WORKSPACE
	doc.update(fields)
	doc.flags.ignore_permissions = True
	doc.save()
	frappe.db.commit()
	return WORKSPACE


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

	# Still offered a chance -- other apps' icons come from it -- but ours no
	# longer depends on it succeeding, and is written afterwards either way.
	note = without_aborting_the_migrate(
		create_desktop_icons, "rebuild the desktop icons", title=DESK_STEP
	)
	without_aborting_the_migrate(
		ensure_desktop_icon, "write this app's apps-screen icon", title=DESK_STEP
	)
	return note


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


def relabel_navigation(settings=None):
	"""Put the level names on the navigation entries that carry one.

	Runs after the imports, every time, because importing a shipped definition
	puts the shipped labels back. Scoped to this app's own surfaces: another
	app's workspace may well link to a Work Management doctype, and its wording
	is not ours to rewrite.

	Returns how many entries it changed.
	"""
	if settings is None and frappe.db.exists("DocType", "Work Management Settings"):
		settings = frappe.get_cached_doc("Work Management Settings")
	names = taxonomy.resolve(settings)
	ours = [name for name, _path, _shipped in workspace_definitions()]
	changed = 0
	for doctype, parents in (("Workspace Link", ours), ("Workspace Sidebar Item", [SIDEBAR])):
		if not frappe.db.exists("DocType", doctype):
			continue  # v15 has no Workspace Sidebar.
		for row in frappe.get_all(
			doctype,
			filters={"parent": ["in", parents], "link_to": ["in", list(NAV_LABELS)]},
			fields=["name", "link_to", "label"],
		):
			wanted = nav_label(row.link_to, names)
			if wanted and row.label != wanted:
				frappe.db.set_value(doctype, row.name, "label", wanted, update_modified=False)
				changed = changed + 1
	if changed:
		frappe.clear_cache()
	return changed


def sync():
	"""Repair every desk surface. Safe to run repeatedly."""
	ensure_nav_block()
	repaired = sync_workspaces()
	sync_sidebar()
	ensure_desktop_icon()
	# before hide_links_to_missing_doctypes(): a link repointed at a doctype that
	# exists must not be hidden on the way past for naming one that does not
	repoint_retired_links()
	hide_links_to_missing_doctypes()
	relabel_navigation()
	if repaired:
		_refresh_desktop_icon()
		frappe.clear_cache()
		for name, reason in repaired.items():
			print(f"Work Management: repaired workspace {name} ({reason})")
	return repaired
