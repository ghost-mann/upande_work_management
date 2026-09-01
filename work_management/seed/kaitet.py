"""Kaitet's own configuration, applied to the Kaitet site only.

The app ships empty on purpose: farms, the company and the approvers are
configuration, not code, and a new project should never find someone else's farm
names in its pickers. This module puts Kaitet's values back, and is the only
place in the repository that knows them.

	bench --site kaitet-group.upande.com execute work_management.seed.kaitet.execute

Safe to run more than once.
"""

import frappe

from work_management import approvals

COMPANY = "Kaitet Ltd."

FARMS = [
	("Saboti", "PROJ-0031"),
	("Lokitela", "PROJ-0031"),
	("Vale", "PROJ-0031"),
	("Endebess", "PROJ-0032"),
]

# The live role name is spelled "Valle" while the farm is "Vale". Kept as-is:
# renaming a role people already hold is a separate, riskier job.
FARM_APPROVER_ROLE = {
	"Saboti": "Farm Manager Saboti",
	"Lokitela": "Farm Manager Lokitela",
	"Endebess": "Farm Manager Endebess",
	"Vale": "Farm Manager Valle",
}

# Roles the shipped app no longer creates, because no other project has them.
KAITET_ROLES = list(FARM_APPROVER_ROLE.values()) + [
	"HR Manager Kaitet",
	"Coffee Clerk",
	"Agriculture Manager",
]

# DocPerms that left the shipped doctype JSON with those roles. Re-added here as
# Custom DocPerms so nobody on this site loses access they had.
KAITET_DOCPERMS = [
	# No `submit` on the two child tables. A child row is submitted by submitting
	# its parent, so a child table has no submit of its own to grant -- and Frappe
	# refuses the grant when anything saves that doctype's permissions, not when
	# the grant is added. The shipped JSON carried it for nine roles each, so
	# adding one Coffee Clerk row here revalidated the whole doctype and died on
	# Farm Manager. That killed the seed, which is what gives each farm its cost
	# project, which is why a Master Plan screen said Lokitela had none.
	("Work Actuals Employee", "Coffee Clerk",
		["read", "write", "create", "delete", "report", "export", "share", "print", "email"]),
	("Work Assignment Employee", "Coffee Clerk",
		["read", "write", "create", "delete", "report", "export", "share", "print", "email"]),
	("Work Management Planner", "Agriculture Manager",
		["read", "write", "create", "submit", "cancel", "amend", "report", "export", "share", "print", "email"]),
]


def execute():
	created_roles = ensure_roles()
	written_projects, missing_farms, missing_projects = ensure_farm_projects()
	restore_docperms()
	carried = carry_hr_manager_kaitet()
	rows = seed_stage_approvers()
	set_company()

	frappe.db.commit()
	print(
		f"Kaitet seed: {created_roles} role(s), {written_projects} cost project(s), "
		f"{rows} approver row(s), {carried} user(s) given HR Manager"
	)
	if missing_farms:
		print(
			"  no Farm record in Upande Core for: " + ", ".join(missing_farms)
			+ " -- create them there and re-run to give them their cost project"
		)
	if missing_projects:
		# Said out loud because it used to be swallowed, and a farm without a cost
		# project is a Master Plan screen that offers no activities and cannot say
		# why. On a site that is not Kaitet the mapping in this file names the
		# wrong projects, and that is the thing to fix.
		print(
			"  no Project on this site for: " + ", ".join(missing_projects)
			+ " -- create those projects, or set each farm's own cost project in"
			  " Work Management Settings, Farms tab"
		)


def ensure_roles():
	created = 0
	for role in KAITET_ROLES:
		if frappe.db.exists("Role", role):
			continue
		frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
			ignore_permissions=True
		)
		created += 1
	return created


def ensure_farm_projects():
	"""Give each Kaitet farm its cost project.

	Returns (written, missing_farms, missing_projects), the last two being what
	this could not do and why -- one list per cause, because the fixes differ: a
	farm Upande Core has not got is created there, while a project this site has
	not got is either created here or means the mapping above names another
	site's projects.

	This used to create the farms themselves. It does not any more: farms are
	Upande Core's records, and a farm invented here would be missing the company,
	farm type and abbreviation Core requires. What is still Kaitet's own is which
	project each farm's costs land in -- the mapping live runs on -- and that
	lives on the farms table in Settings.

	Neither skip is silent, and the missing project used to be. The cost project
	is what the Master Plan screen reads to decide which tasks exist, so a farm
	quietly without one shows "no cost project" and no reason why -- which this
	function's own docstring warned about while causing it.
	"""
	settings = frappe.get_doc("Work Management Settings")
	existing = {row.farm: row for row in settings.get("farms") or []}
	written, missing_farms, missing_projects = 0, [], []

	for farm, project in FARMS:
		if not frappe.db.exists("Farm", farm):
			missing_farms.append(farm)
			continue
		if not frappe.db.exists("Project", project):
			missing_projects.append("%s (wanted %s)" % (farm, project))
			continue
		row = existing.get(farm)
		if row:
			if row.project == project:
				continue
			row.project = project
		else:
			settings.append("farms", {"farm": farm, "project": project})
		written += 1

	# And narrow the app to them, which is the other half of naming them. Kaitet
	# works four of the sixteen farms Upande Core carries on this site; without
	# this, the four rows above supply cost projects and nothing else, and every
	# screen still offers all sixteen.
	#
	# Not cosmetic. The per-farm approvers seeded below cover exactly these four,
	# and the stranded-farm check refuses a save where some farms in scope have an
	# approver and others do not. Leaving the scope at sixteen made the seed write
	# a configuration its own validation rejected -- it threw, the transaction
	# rolled back, and the cost projects written above were lost with it.
	restricted = 0
	if not settings.get("farms_restrict"):
		settings.farms_restrict = 1
		restricted = 1

	if written or restricted:
		settings.save(ignore_permissions=True)
	return written, missing_farms, missing_projects


def restore_docperms():
	from frappe.permissions import add_permission, update_permission_property

	for doctype, role, rights in KAITET_DOCPERMS:
		if not frappe.db.exists("DocType", doctype) or not frappe.db.exists("Role", role):
			continue
		if frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0}):
			continue
		add_permission(doctype, role, 0)
		for right in rights:
			update_permission_property(doctype, role, 0, right, 1)


def carry_hr_manager_kaitet():
	"""The shipped doctypes now grant HR Manager what HR Manager Kaitet had.

	Rather than keep a Kaitet-named role in permissions, give its holders the
	standard role so their access is unchanged.
	"""
	if not frappe.db.exists("Role", "HR Manager"):
		return 0
	holders = frappe.get_all(
		"Has Role",
		filters={"role": "HR Manager Kaitet", "parenttype": "User"},
		pluck="parent",
		distinct=True,
	)
	carried = 0
	for user in holders:
		if not frappe.db.exists("User", user):
			continue
		user_doc = frappe.get_doc("User", user)
		if any(row.role == "HR Manager" for row in user_doc.get("roles") or []):
			continue
		user_doc.append("roles", {"role": "HR Manager"})
		user_doc.flags.ignore_permissions = True
		user_doc.save()
		carried += 1
	return carried


def seed_stage_approvers():
	"""Give every farm-scoped stage a per-farm approver, per farm.

	This is where Kaitet's per-farm restriction becomes real rather than
	nominal. The old workflows carried both a per-farm transition and an
	unconditional "Farm Manager" one, so anyone holding the plain role could
	approve any farm. Naming an approver per farm closes that.
	"""
	settings = frappe.get_doc("Work Management Settings")
	approvals.seed_stages(settings=settings)
	settings.reload()

	scoped = [stage for stage in approvals.CATALOGUE if stage.scoped]
	existing = {
		(row.stage_label, row.scope, row.user)
		for row in settings.get("stage_approvers") or []
	}
	created = 0

	for farm, role in FARM_APPROVER_ROLE.items():
		if not frappe.db.exists("Farm", farm):
			continue
		users = frappe.get_all(
			"Has Role",
			filters={"role": role, "parenttype": "User"},
			pluck="parent",
			distinct=True,
		)
		for user in users:
			if not frappe.db.exists("User", user):
				continue
			for stage in scoped:
				key = (stage.label, farm, user)
				if key in existing:
					continue
				settings.append("stage_approvers", {
					"stage_label": stage.label,
					"scope": farm,
					"user": user,
					"role": role,
				})
				existing.add(key)
				created += 1

	if created:
		settings.flags.ignore_permissions = True
		settings.save()
	return created


def set_company():
	if not frappe.db.exists("Company", COMPANY):
		return
	settings = frappe.get_doc("Work Management Settings")
	if settings.default_company == COMPANY:
		return
	settings.default_company = COMPANY
	settings.flags.ignore_permissions = True
	settings.flags.skip_approval_sync = True
	settings.save()
