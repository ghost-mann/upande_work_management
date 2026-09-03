"""Deployment configuration for Work Management.

Nothing about a particular customer belongs in this file. Farms and their cost
projects are Upande Core's records of "Farm", with each farm's cost project on
the farms table in "Work Management Settings"; who approves what comes from the
approval stages there too; the company falls back to the site's own default. An unconfigured install therefore has no farms and no
approvers, and the screens say so rather than quietly offering someone else's.

Kaitet's own values are applied by work_management.seed.kaitet on that site alone.
"""

import frappe

from work_management import approvals, capabilities, split_day, taxonomy

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


def farms_from_permissions(rows, doctype=None):
	"""The farms these User Permission rows allow, or None for no restriction.

	Frappe's semantics, not softer ones: a row whose `applicable_for` is set
	restricts only that doctype, and rows that all filter out leave the person
	unrestricted -- which is what Frappe concludes when its own filter returns
	nothing (`frappe/permissions.py:782`, and the `if allowed_docs:` that guards
	its use). Behaving differently here than the list view does would be worse
	than either behaviour alone, because then nobody could reason about the site.

	`None` for unrestricted and a non-empty set for restricted, so that
	"permitted no farms" can never be read as "permitted every farm". That
	confusion turns a gate into a leak, and an empty set on both sides is how it
	would happen.
	"""
	allowed = set()
	for row in rows or []:
		scope = row.get("applicable_for")
		if scope and scope != doctype:
			continue
		farm = row.get("for_value")
		if farm:
			allowed.add(farm)
	return allowed or None


def permitted_farms(user=None, doctype=None):
	"""Farms this user may act on, or None if they are not restricted at all.

	Farm scoping already has an owner on these sites, and it is not this app:
	the live site carries 202 Farm User Permissions across 96 users, the newest
	created the day this was written. 362 of its 458 enabled users have none and
	so see every farm, which is Frappe's own default and the behaviour to keep.

	Read straight from the table rather than through
	`frappe.permissions.get_user_permissions`, for two reasons. The helper is not
	in the Server Script sandbox's globals, and live runs Server Scripts -- so a
	second implementation would be needed there anyway, and two implementations
	of a permission rule is how a site ends up with two answers. And
	`frappe.get_all` inside a Server Script is forced to `ignore_permissions=True`
	(`frappe/utils/safe_exec.py:307`), which is the mechanism behind the leak this
	closes; a read that must be explicit is better written explicitly.

	Administrator and Guest are never restricted, matching Frappe.
	"""
	user = user or frappe.session.user
	if not user or user in ("Administrator", "Guest"):
		return None
	rows = frappe.get_all(
		"User Permission",
		filters={"allow": "Farm", "user": user},
		fields=["for_value", "applicable_for"],
		limit_page_length=0,
	)
	return farms_from_permissions([dict(r) for r in rows], doctype=doctype)


def narrow_to_permitted(farms, permitted):
	"""`farms` less the ones this person may not act on, order preserved.

	Permission never widens a list: a farm somebody is permitted that this
	project does not work still does not appear. And a person permitted only
	farms outside the project gets an empty list rather than a fallback to all --
	an honest empty is a screen saying "nothing here for you", where the fallback
	would be the leak itself.
	"""
	if permitted is None:
		return list(farms)
	return [f for f in farms if f in permitted]


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
		# The approval chain, in the two shapes the screens need. Both default to
		# the shipped chain rather than to empty: a screen reading an empty chain
		# cannot advance anything, and one reading a missing key fails at module
		# top and takes the whole page down instead of degrading.
		#
		# `stage_rows` is for WRITES -- every step in order, the state it waits in,
		# the state approving it leads to, and whether it is on. `stage_states` is
		# for READS, per document type, and deliberately includes the states of
		# steps that are switched off: a list filter must not narrow because
		# somebody changed a setting, or documents that went through the old chain
		# vanish from reports.
		"stage_rows": approvals.effective_chain(settings=None),
		"stage_states": {
			doctype: approvals.pipeline_states(settings=None, document_type=doctype)
			for doctype in approvals.CHAIN_ENDS
		},
		# Who may do what, beyond approving: raise a budget, change a rate, send a
		# payment run, enter work. These were four lists and a scatter of inline
		# checks naming one company's job titles.
		"capabilities": capabilities.configured(settings=None),
		# May a farm hold two approved budgets over the same days? Off unless a
		# site says otherwise, so approving a second overlapping plan is refused
		# exactly as it always has been.
		"allow_concurrent_master_plans": False,
		# May one worker's day be shared between two tasks? Off unless a site says
		# so, and with it off the double-allocation guard refuses exactly as it
		# always has -- no figure on any existing site moves.
		"allow_split_day": False,
		# How long a full day is. The denominator every man-day figure divides by;
		# see work_management/split_day.py, which is unit-tested.
		"standard_day": dict(split_day.STANDARD_DAY),
	}

	try:
		settings = frappe.get_cached_doc("Work Management Settings")
	except Exception:
		return cfg

	# `settings.get(...)` rather than an attribute: a Settings doc saved before
	# this field existed has no such key, and an attribute would raise.
	cfg["allow_concurrent_master_plans"] = bool(settings.get("allow_concurrent_master_plans"))
	cfg["allow_split_day"] = bool(settings.get("allow_split_day"))
	# HOW LONG A DAY IS, read defensively, because zero is what an unset field
	# actually holds here.
	#
	# A `default` on a doctype field applies to a NEW document. Work Management
	# Settings is a Single that already exists on every site, so adding these
	# three fields wrote `'0'` into tabSingles for all of them -- not null, not 8.
	# Read literally, that says a working day is zero hours long, and it made
	# every man-day figure zero and the backfill write zero hours onto all 7,605
	# rows on kaitet.local. Both were the same bug.
	#
	# So a Monday or a Saturday of zero hours is read as "nothing said" and falls
	# back to the shipped figure: no site means it, and the cost of believing it
	# is every labour figure silently becoming zero. Sunday IS allowed to be
	# zero, because "we do not work Sundays" is a real thing to say and
	# split_day.man_days() contributes nothing for such a day rather than
	# dividing by it.
	for weekday, field in (("weekday", "std_hours_weekday"),
			("saturday", "std_hours_saturday")):
		hours = settings.get(field)
		if hours not in (None, "") and float(hours) > 0:
			cfg["standard_day"][weekday] = float(hours)
	sunday = settings.get("std_hours_sunday")
	if sunday not in (None, ""):
		cfg["standard_day"]["sunday"] = float(sunday)
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

	# Then, if this site has asked for it, narrow again to the farms this person
	# may act on. Two switches, read in this order and doing different jobs: the
	# one above asks which farms the project works, this one asks which of those
	# this person is permitted.
	#
	# Off by default and off on every existing site, because turning it on changes
	# what 95 restricted people on the live site can reach. The audit says none of
	# them is currently working a farm they are not permitted, so enforcing there
	# costs nobody anything -- but that is a fact about one site, established by
	# running `farm_permission_audit`, and it is not a fact this app may assume
	# about the next one.
	#
	# `settings.get(...)` rather than an attribute, so a Settings doc saved before
	# the field existed reads as off instead of raising.
	if settings.get("farms_respect_user_permissions"):
		cfg["farms"] = narrow_to_permitted(cfg["farms"], permitted_farms())

	cfg["farm_project"] = {
		row.farm: row.project
		for row in rows
		if row.farm and row.project and row.farm in cfg["farms"]
	}

	cfg["farm_approver_role"] = _farm_approver_role(settings, cfg["farms"])
	cfg["hr_head_roles"] = _stage_roles(settings, "assigner_hr_head", "actuals_hr_head")

	cfg["stage_rows"] = approvals.effective_chain(settings)
	cfg["stage_states"] = {
		doctype: approvals.pipeline_states(settings, document_type=doctype)
		for doctype in approvals.CHAIN_ENDS
	}

	cfg["capabilities"] = capabilities.configured(settings)

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
