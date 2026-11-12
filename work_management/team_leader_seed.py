"""Load a farm team-leader list into Work Management Team Leader (idempotent).

Master plans now refuse a row without a listed, active team leader, and live
starts with an empty list -- so before plans can be saved after deploy, each
farm's list must be there. This loads the list prepared from the 4 Nov sheet
(exported from the bench registry), skipping anyone already listed or whose
login does not exist on the site.

    bench --site <site> execute work_management.team_leader_seed.load --kwargs '{"path": "/path/to/team_leaders.json"}'
"""

import json

import frappe


def load(path, dry_run=0):
	with open(path) as handle:
		rows = json.load(handle)
	out = {"added": [], "already": [], "no_user": [], "dry_run": int(dry_run)}
	for r in rows:
		user, farm = r.get("user"), r.get("farm")
		if not (user and farm):
			continue
		if not frappe.db.exists("User", user):
			out["no_user"].append(user)
			continue
		if frappe.db.exists("Work Management Team Leader", user):
			out["already"].append(user)
			continue
		if not int(dry_run):
			d = frappe.new_doc("Work Management Team Leader")
			d.user = user
			d.farm = farm
			d.active = 1
			d.full_name = frappe.db.get_value("User", user, "full_name")
			d.added_by = frappe.session.user
			d.added_on = frappe.utils.now()
			d.insert(ignore_permissions=True)
		out["added"].append(user)
	if not int(dry_run):
		frappe.db.commit()
	return out
