"""Carry the old configuration into the new one.

Two things moved when the module stopped being Kaitet-specific:

  - farms and their cost projects left the WM Farm child table in Settings and
    became records of "Work Management Farm", so the `farm` field on every
    pipeline doctype could be a Link instead of a Select with four names
    hardcoded in it;
  - who approves what left the workflow fixtures and the WM Farm approver_role
    column, and became Stage Approver rows in Settings.

Both source fields are still present and read-only, so this patch can read them.
It is safe to run more than once.
"""

import frappe

from work_management import approvals


def execute():
	if not frappe.db.exists("DocType", "Work Management Settings"):
		return

	settings = frappe.get_doc("Work Management Settings")
	approvals.seed_stages(settings=settings)
	settings.reload()

	created_farms = migrate_farms(settings)
	created_rows = migrate_farm_approvers(settings)
	created_rows += migrate_consultants(settings)

	if created_rows:
		settings.flags.ignore_permissions = True
		settings.flags.skip_approval_sync = True
		settings.save()

	frappe.clear_cache(doctype="Work Management Settings")
	approvals.build_workflows()
	frappe.db.commit()

	print(
		f"Work Management: {created_farms} farm record(s), "
		f"{created_rows} approver row(s) migrated"
	)


def migrate_farms(settings):
	"""WM Farm rows -> Work Management Farm records."""
	created = 0
	for row in settings.get("farms") or []:
		if not row.farm or frappe.db.exists("Work Management Farm", row.farm):
			continue
		frappe.get_doc({
			"doctype": "Work Management Farm",
			"farm_name": row.farm,
			"project": row.project,
		}).insert(ignore_permissions=True)
		created += 1
	return created


def migrate_farm_approvers(settings):
	"""WM Farm.approver_role -> Stage Approver rows, one per holder of that role.

	The old column named a role, not a person. The people who approve that farm
	today are exactly the users holding it, so that is what gets written — with
	the role kept as a per-farm override, which is what stops one farm's approver
	reaching another's work.
	"""
	scoped = [stage for stage in approvals.CATALOGUE if stage.scoped]
	if not scoped:
		return 0

	existing = {
		(row.stage, row.scope, row.user)
		for row in settings.get("stage_approvers") or []
	}
	created = 0

	for row in settings.get("farms") or []:
		role = getattr(row, "approver_role", None)
		if not row.farm or not role or not frappe.db.exists("Role", role):
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
				key = (stage.key, row.farm, user)
				if key in existing:
					continue
				settings.append("stage_approvers", {
					"stage": stage.key,
					"stage_label": stage.label,
					"scope": row.farm,
					"user": user,
					"role": role,
				})
				existing.add(key)
				created += 1
	return created


def migrate_consultants(settings):
	"""Settings.consultant_users -> Stage Approver rows on the consultant stages."""
	raw = settings.get("consultant_users") or ""
	emails = [part.strip() for part in raw.replace("\n", ",").split(",") if part.strip()]
	if not emails:
		return 0

	stages = [
		approvals.by_key("planner_weekly_consultant"),
		approvals.by_key("masterplan_consultant"),
	]
	existing = {
		(row.stage, row.scope, row.user)
		for row in settings.get("stage_approvers") or []
	}
	created = 0

	for stage in stages:
		if not stage:
			continue
		for email in emails:
			if not frappe.db.exists("User", email):
				continue
			key = (stage.key, None, email)
			if key in existing or (stage.key, "", email) in existing:
				continue
			settings.append("stage_approvers", {
				"stage": stage.key,
				"stage_label": stage.label,
				"user": email,
			})
			existing.add(key)
			created += 1
	return created
