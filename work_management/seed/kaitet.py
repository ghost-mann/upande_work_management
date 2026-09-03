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

# What this site has always allowed, beyond approving. These were four lists
# compiled into the app naming Kaitet's job titles; they are capabilities now,
# and the shipped default is System Manager alone so no other farm inherits them.
# Kaitet is the site that had them, so Kaitet is where they are set.
CAPABILITY_ROLES = {
	"edit_master_plan": ["Farm Manager", "HOD HR", "General Manager", "System Manager"],
	"set_rates": ["General Manager", "HOD HR", "System Manager"],
	"send_payment": ["HOD HR", "Accounts Manager", "Accounts User", "General Manager",
		"System Manager"],
	"enter_work": ["HR User", "HR Manager", "HR Clerk", "HOD HR"],
	"handle_payments": ["Accounts Manager", "Accounts User", "System Manager"],
}

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
#
# The five below used to arrive by accident: they were named in shipped doctype
# permissions, and Frappe creates a Role it finds in a DocPerm. That is why
# installing at any farm produced an `HOD HR`. The permissions moved here, so the
# roles have to move here too -- otherwise a rebuilt Kaitet site would have the
# grants and not the roles, and restore_docperms() skips a role that is absent,
# silently.
KAITET_ROLES = list(FARM_APPROVER_ROLE.values()) + [
	"HR Manager Kaitet",
	"Coffee Clerk",
	"Agriculture Manager",
	"Farm Manager",
	"General Manager",
	"HOD HR",
	"HR Clerk",
	"Production Section Head",
]

# DocPerms that left the shipped doctype JSONs, re-added here as Custom DocPerms
# so nobody on this site loses access they had.
#
# They left because a shipped doctype naming a role makes Frappe create it, and
# five of them are Kaitet's own job titles: installing the app at any farm was
# creating `HOD HR` and `Production Section Head` in their role list. The app now
# grants only to roles a stock ERPNext + HRMS site already has, so a fresh install
# reaches System Manager and nothing else -- and each site grants its own.
#
# Kaitet is the site that had them, so Kaitet is where they are restored, exactly:
# every grant that moved, with the rights it carried, and no more. Widening here
# would be the opposite mistake and just as quiet.
#
# No `submit` on the two child tables. A child row is submitted by submitting its
# parent, so a child table has no submit of its own to grant -- and Frappe refuses
# the grant when anything saves that doctype's permissions, not when the grant is
# added, which once killed this whole seed with an error naming an innocent role.
KAITET_DOCPERMS = [
	# moved out of the shipped doctypes, so the app invents no job titles
	("Work Actuals Employee", "Farm Manager",
		["read", "write", "create", "delete", "report", "export", "share", "print", "email"]),
	("Work Actuals Employee", "HR Clerk",
		["read", "write", "create", "delete", "report", "export", "share", "print", "email"]),
	("Work Actuals Employee", "Production Section Head",
		["read", "write", "create", "delete", "report", "export", "share", "print", "email"]),
	("Work Actuals Employee", "HOD HR",
		["read", "write", "create", "delete", "report", "export", "share", "print", "email"]),
	("Work Actuals Employee", "General Manager",
		["read", "write", "create", "delete", "report", "export", "share", "print", "email"]),
	("Work Assignment Employee", "Farm Manager",
		["read", "write", "create", "delete", "report", "export", "share", "print", "email"]),
	("Work Assignment Employee", "HR Clerk",
		["read", "write", "create", "delete", "report", "export", "share", "print", "email"]),
	("Work Assignment Employee", "Production Section Head",
		["read", "write", "create", "delete", "report", "export", "share", "print", "email"]),
	("Work Assignment Employee", "HOD HR",
		["read", "write", "create", "delete", "report", "export", "share", "print", "email"]),
	("Work Assignment Employee", "General Manager",
		["read", "write", "create", "delete", "report", "export", "share", "print", "email"]),
	("Work Management Actuals", "HR Clerk",
		["read", "write", "create", "delete", "submit", "report", "export", "share", "print", "email"]),
	("Work Management Actuals", "HOD HR",
		["read", "write", "create", "delete", "submit", "cancel", "amend", "report", "export", "share", "print", "email"]),
	("Work Management Actuals", "General Manager",
		["read", "write", "create", "delete", "submit", "cancel", "amend", "report", "export", "share", "print", "email"]),
	("Work Management Actuals", "Farm Manager",
		["select", "read", "write", "create", "delete", "submit", "report", "export", "share", "print", "email"]),
	("Work Management Actuals", "Production Section Head",
		["select", "read", "write", "create", "delete", "submit", "report", "export", "share", "print", "email"]),
	("Work Management Assigner", "HOD HR",
		["read", "write", "create", "delete", "submit", "cancel", "amend", "report", "export", "share", "print", "email"]),
	("Work Management Assigner", "General Manager",
		["read", "write", "create", "delete", "submit", "report", "export", "share", "print", "email"]),
	("Work Management Assigner", "Farm Manager",
		["read", "write", "create", "delete", "submit", "report", "export", "share", "print", "email"]),
	("Work Management Assigner", "Production Section Head",
		["select", "read", "write", "create", "delete", "submit", "report", "export", "share", "print", "email"]),
	("Work Management Master Plan", "General Manager",
		["read", "write", "create", "report"]),
	("Work Management Master Plan", "HOD HR",
		["read", "write", "create", "report"]),
	("Work Management Master Plan", "Farm Manager",
		["read", "write", "create", "report"]),
	("Work Management Payment", "HR Clerk",
		["read", "write", "create", "delete", "submit", "report", "export", "share", "print", "email"]),
	("Work Management Payment", "HOD HR",
		["read", "write", "create", "delete", "submit", "cancel", "report", "export", "share", "print", "email"]),
	("Work Management Payment", "General Manager",
		["read", "write", "create", "delete", "report", "export", "share", "print", "email"]),
	("Work Management Planner", "Production Section Head",
		["read", "write", "create", "delete", "submit", "report", "export", "share", "print", "email"]),
	("Work Management Planner", "Farm Manager",
		["read", "write", "create", "submit", "cancel", "amend", "report", "export", "share", "print", "email"]),
	# No `submit` on these two, nor on the Planner's shipped Accounts Manager and
	# HR Manager rows. All four meant approve-but-do-not-edit, and Frappe has no
	# way to express that: "Cannot set Submit, Cancel, Amend without Write". The
	# rights are otherwise exactly what they carried.
	#
	# Nothing is lost on the approval path -- api/planner.py sets docstatus with
	# frappe.db.set_value and never consults this grant; who may approve is
	# decided by the stage's configured role and the farm check beside it. What
	# these four give up is the desk form's own Submit button.
	("Work Management Planner", "HOD HR",
		["read", "report", "export", "share", "print", "email"]),
	("Work Management Planner", "General Manager",
		["read", "report", "export", "share", "print", "email"]),
	("Work Management Section", "Farm Manager",
		["select", "read", "report"]),
	("Work Management Section", "General Manager",
		["select", "read", "report"]),
	("Work Task Rate", "Farm Manager",
		["read", "report"]),

	# always lived here: roles this seed creates, never shipped
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
	caps = seed_capabilities()
	set_company()

	frappe.db.commit()
	print(
		f"Kaitet seed: {created_roles} role(s), {written_projects} cost project(s), "
		f"{rows} approver row(s), {caps} capability row(s), "
		f"{carried} user(s) given HR Manager"
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


def seed_capabilities():
	"""Give each capability the roles this site has always granted it.

	The app ships every capability pointing at System Manager alone, so that a
	farm installing it inherits nobody's org chart. That default would take these
	away from Kaitet, where they have always been in force -- so they are restored
	here, on this site, exactly as they were.

	A role somebody has since added is kept: this fills gaps, it does not reset
	the grid. Roles that do not exist on the site are skipped rather than written,
	since a Link to a missing Role will not save.
	"""
	from work_management import capabilities

	settings = frappe.get_doc("Work Management Settings")
	capabilities.seed(settings=settings, save=False)

	existing = set()
	for row in settings.get("capabilities") or []:
		if row.capability and row.role:
			existing.add((row.capability, row.role))

	added = 0
	for key, roles in CAPABILITY_ROLES.items():
		cap = capabilities.by_key(key)
		if not cap:
			continue
		for role in roles:
			if not frappe.db.exists("Role", role):
				continue
			if (cap.label, role) in existing:
				continue
			settings.append("capabilities", {"capability": cap.label, "role": role})
			existing.add((cap.label, role))
			added += 1

	# The seeded default is System Manager, which every list above already
	# contains where it should; where it does not, it stays -- System Manager may
	# do everything anyway, so leaving the row is honest rather than misleading.
	settings.flags.ignore_permissions = True
	settings.save()
	return added


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
