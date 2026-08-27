"""Deployment configuration for Work Management.

Nothing about a particular customer belongs in this file. Farms and their cost
projects are records of "Work Management Farm"; who approves what comes from the
approval stages in "Work Management Settings"; the company falls back to the
site's own default. An unconfigured install therefore has no farms and no
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
	"""Active farms, with their cost projects, in the order they were created."""
	if not frappe.db.exists("DocType", "Work Management Farm"):
		return [], {}
	rows = frappe.get_all(
		"Work Management Farm",
		filters={"disabled": 0},
		fields=["name", "project"],
		order_by="creation asc",
	)
	return [row.name for row in rows], {row.name: row.project for row in rows if row.project}


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


def payable_employee_columns():
	"""The Employee columns the task-worker rule may read on THIS site.

	employment_type and designation are standard fields. custom_category is a
	custom field one site created, and naming a column the site has not got does
	not degrade a query, it kills it:

	    (1054, "Unknown column 'twe.custom_category' in 'WHERE'")

	which took the whole payment screen down on a site that never had the field.
	The three lists are ORed, so dropping the column a site lacks costs nothing --
	there is no Settings list it could have matched anyway.
	"""
	columns = []
	for column in ("employment_type", "designation", "custom_category"):
		if frappe.db.has_column("Employee", column):
			columns.append(column)
	return columns


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

	# Sites that have not yet run the Work Management Farm migration still keep
	# their farms in the deprecated Settings table.
	if not cfg["farms"]:
		legacy = settings.get("farms") or []
		cfg["farms"] = [row.farm for row in legacy if row.farm]
		cfg["farm_project"] = {row.farm: row.project for row in legacy if row.farm and row.project}

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
