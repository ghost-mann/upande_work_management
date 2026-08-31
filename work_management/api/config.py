"""Deployment configuration for Work Management.

Nothing about a particular customer belongs in this file. Farms and their cost
projects are Upande Core's records of "Farm", with each farm's cost project on
the farms table in "Work Management Settings"; who approves what comes from the
approval stages there too; the company falls back to the site's own default. An unconfigured install therefore has no farms and no
approvers, and the screens say so rather than quietly offering someone else's.

Kaitet's own values are applied by work_management.seed.kaitet on that site alone.
"""

import frappe

from work_management import taxonomy

# Warehouse name fragments that are stores rather than places work happens.
# Generic enough to be a useful starting point anywhere; override in Settings.
DEFAULT_BLOCK_EXCLUDE = [
	"Store", "Mill", "Tank", "BIN", "Warehouse", "Cold Room", "Parchment", "Diesel",
]


def _default_company():
	company = frappe.defaults.get_defaults().get("company")
	if company:
		return company
	companies = frappe.get_all("Company", limit=1, pluck="name")
	return companies[0] if companies else None


def _farms():
	"""Active farms, in the order they were created, from Upande Core.

	Which farms exist is Core's answer, not this app's. hooks.py requires that
	app, so `Farm` is unambiguous and no exists() check stands here -- on a site
	whose `Farm` came from somewhere else the install would have failed, which is
	the only defence against reading the wrong records rather than none.

	`disabled` is not a field Core ships. Where a site has added one this
	respects it; where none exists every farm is active. upande_scp reads it the
	same way, behind the same check.

	Cost projects are not Core's business and do not live on its doctype: they
	come from the farms table on Settings, in get_config() below.
	"""
	filters = {"disabled": 0} if frappe.db.has_column("Farm", "disabled") else {}
	rows = frappe.get_all("Farm", filters=filters, fields=["name"], order_by="creation asc")
	return [row.name for row in rows], {}


def farms_in_use(all_farms, chosen, restrict=True):
	"""The farms this app offers: the listed ones when restricted, else all.

	`restrict` is the Settings checkbox. Off -- the default -- the rows exist only
	to carry each farm's cost project and area, and every farm in Upande Core is
	offered. That matters: a row added to give Lokitela its cost project must not
	hide the fifteen farms nobody mentioned, and when the list and the narrowing
	were one and the same it did exactly that.

	Upande Core's farm list serves every Upande app on the site, so it is wider
	than any one of them needs -- sixteen farms across eight companies on
	kaitet.local, where this app plans work against four. Settings names the ones
	in use, and this is where that choice narrows the app.

	Empty means all, deliberately. That is what every existing site has, and a
	setting nobody has touched must not empty the pickers on five screens.

	A chosen farm Core no longer has is dropped -- a farm can be renamed there
	without telling this app, and a name that resolves to nothing is worse in a
	picker than an absence. But if *every* choice has gone stale the answer is
	all of them, not none: "no farms" would take the whole app dark over a
	rename, with nothing on screen saying why.

	Pure, so both directions can be read and tested without a site.
	"""
	if not restrict:
		return list(all_farms)
	wanted = {name for name in (chosen or []) if name}
	if not wanted:
		return list(all_farms)
	kept = [name for name in all_farms if name in wanted]
	return kept or list(all_farms)


def _farm_approver_role(settings, farms):
	"""{farm: role} — the role that approves work for each farm.

	Read from the farm-scoped approval stages: a row naming a farm and a role
	override is what keeps one farm's approvals out of another's reach. Farms with
	no row of their own fall back to the stage's role, which covers every farm.
	"""
	from work_management import approvals

	mapping = {}
	scoped = [stage for stage in approvals.CATALOGUE if stage.scoped]
	if not scoped:
		return mapping

	rows = approvals.stage_rows(settings)
	for stage in scoped:
		default_role = approvals.stage_role(stage, rows)
		for approver in approvals.approvers_for(stage.key, settings=settings):
			if approver.scope and approver.scope not in mapping:
				mapping[approver.scope] = approver.role or default_role
		for farm in farms:
			mapping.setdefault(farm, default_role)
	return mapping


def _stage_roles(settings, *keys):
	"""Every role that can act at the named stages, overrides included.

	The ported screens ask "is this user the HR head?" and used to answer it by
	naming two specific HR roles. Now the question is answered by whoever the HR
	stages are configured for.
	"""
	from work_management import approvals

	rows = approvals.stage_rows(settings)
	roles = []
	for key in keys:
		stage = approvals.by_key(key)
		if not stage:
			continue
		for role in [approvals.stage_role(stage, rows)] + [
			approver.role for approver in approvals.approvers_for(stage.key, settings=settings)
		]:
			if role and role not in roles:
				roles.append(role)
	return roles


def get_config():
	farms, farm_project = _farms()
	cfg = {
		"farms": farms,
		"farm_project": farm_project,
		"farm_approver_role": {},
		"hr_head_roles": [],
		"default_company": _default_company(),
		"block_exclude": list(DEFAULT_BLOCK_EXCLUDE),
		# The shipped names, not {}: a site whose Settings will not load still
		# has to give the screens something to print. They fall back to their
		# own hardcoded wording on an empty dict, which is the same text -- but
		# only until a screen forgets to pass a fallback.
		"taxonomy": taxonomy.resolve(None),
	}

	try:
		settings = frappe.get_cached_doc("Work Management Settings")
	except Exception:
		return cfg

	if settings.get("default_company"):
		cfg["default_company"] = settings.default_company
	if settings.get("block_exclude"):
		keywords = [k.strip() for k in settings.block_exclude.split(",") if k.strip()]
		if keywords:
			cfg["block_exclude"] = keywords

	# Each farm's cost project, and an area override, come from the farms table on
	# Settings -- the one thing this app knows about a farm that Upande Core does
	# not track. Rows naming a farm Core has not got are ignored rather than
	# added to the list: which farms exist is Core's answer alone.
	rows = settings.get("farms") or []
	# One table, and one visible switch over whether it narrows. The rows always
	# carry the cost project; they only decide which farms exist when asked to.
	cfg["farms"] = farms_in_use(
		cfg["farms"],
		[row.farm for row in rows if row.farm],
		restrict=bool(settings.get("farms_restrict")),
	)

	cfg["farm_project"] = {
		row.farm: row.project
		for row in rows
		if row.farm and row.project and row.farm in cfg["farms"]
	}

	cfg["farm_approver_role"] = _farm_approver_role(settings, cfg["farms"])
	cfg["hr_head_roles"] = _stage_roles(settings, "assigner_hr_head", "actuals_hr_head")

	cfg["taxonomy"] = taxonomy.resolve(settings)
	return cfg


DEFAULT_HEADER_LOGO = "/assets/work_management/images/work-management-wordmark.svg"


def header_logo():
	"""The logo the work screens show, or the module's own wordmark."""
	try:
		configured = frappe.db.get_single_value("Work Management Settings", "project_logo")
	except Exception:
		configured = None
	return configured or DEFAULT_HEADER_LOGO
