"""Setting up a new site: which cost project each farm's activities come from.

A master plan budgets activities, and a farm's activities are the Tasks on its
cost project. Upande Core does not track cost projects, so the mapping lives on
the farms table in Work Management Settings -- and until it is set, the Master
Plan screen says the farm has no cost project and offers nothing to plan.

Doing it by hand means adding a row per farm and picking from a Link that offers
every project on the site. The dev site has 105, of which 86 carry Tasks and two
are the answer. So:

    # 1. find the ids -- read-only, ranked, likeliest first
    bench --site <site> execute work_management.setup.show_candidates

    # 2. write them
    bench --site <site> execute work_management.setup.set_farm_cost_projects \\
        --kwargs "{'mapping': {'Saboti': 'PROJ-0031', 'Lokitela': 'PROJ-0031', \\
                               'Vale': 'PROJ-0031', 'Endebess': 'PROJ-0032'}}"

Nothing here guesses which project a farm should use. That is an accounting
decision -- it says where a farm's labour cost lands -- and a wrong guess is a
whole period budgeted against the wrong cost centre, which is worse than an
empty field that says so.

For the Kaitet site specifically the mapping is already known and
`work_management.seed.kaitet` applies it, along with that site's roles and
approvers. This module is for every other site.
"""

import frappe

# A project whose name says "tasks" is a catalogue of activities; the others that
# carry Tasks are usually one-off jobs -- a greenhouse build, a leaver's checklist
# -- which have Tasks but are not things a week's labour is planned against.
# A hint for ranking, never a filter: a site may well name its activity project
# something else, and hiding it would send somebody back to guessing.
LIKELY_WORDS = ("task", "activit", "operation")

# Generated one per leaver, so on a large site they arrive in bulk and would
# otherwise crowd the real answer out of the top of the list on task count alone.
UNLIKELY_WORDS = ("employee separation", "separation :")


def plan_farm_projects(rows, mapping):
	"""What writing `mapping` would do to the farms table `rows`.

	Returns {"add": [(farm, project)], "change": [(farm, was, now)],
	"unchanged": [farm]}, each sorted by farm so the printed plan is reviewable
	and stable.

	A farm the mapping does not mention is left alone -- a partial mapping must
	not clear the farms it says nothing about. A farm already pointing at the
	right project produces no write at all, which keeps this idempotent and
	avoids a Settings save that could trip the stranded-approver check for
	reasons unrelated to what was asked.
	"""
	existing = {}
	for row in rows or []:
		farm = row.get("farm") if isinstance(row, dict) else row.farm
		project = row.get("project") if isinstance(row, dict) else row.project
		if farm:
			existing[farm] = project

	add, change, unchanged = [], [], []
	for farm in sorted(mapping or {}):
		project = mapping[farm]
		if not farm or not str(farm).strip():
			raise ValueError("a farm name is required")
		if not project or not str(project).strip():
			raise ValueError(
				"%s has no project in the mapping. Leaving a cost project empty is "
				"what causes \"has no cost project\"; to clear one, do it in the "
				"form where the consequence is visible." % farm)
		if farm not in existing:
			add.append((farm, project))
		elif existing[farm] == project:
			unchanged.append(farm)
		else:
			change.append((farm, existing[farm], project))
	return {"add": add, "change": change, "unchanged": unchanged}


def rank_candidates(rows):
	"""Projects that could be a farm's cost project, likeliest first.

	`rows` carry name, project_name and tasks. A project with no Tasks is dropped
	-- it can offer no activities, so it can never be the answer. The rest are
	ranked, not filtered, and each carries a `likely` flag saying whether its name
	reads like an activity catalogue.
	"""
	out = []
	for row in rows or []:
		if not frappe.utils.cint(row.get("tasks")):
			continue
		name = (row.get("project_name") or row.get("name") or "").lower()
		likely = (any(word in name for word in LIKELY_WORDS)
			and not any(word in name for word in UNLIKELY_WORDS))
		out.append({
			"name": row.get("name"),
			"project_name": row.get("project_name"),
			"tasks": frappe.utils.cint(row.get("tasks")),
			"likely": likely,
		})
	return sorted(out, key=lambda r: (not r["likely"], -r["tasks"], r["name"]))


def cost_project_candidates():
	"""Every project carrying Tasks, ranked. Read-only."""
	rows = frappe.db.sql("""
		SELECT p.name, p.project_name, COUNT(t.name) tasks
		FROM `tabProject` p
		LEFT JOIN `tabTask` t ON t.project = p.name AND IFNULL(t.is_group, 0) = 0
		GROUP BY p.name, p.project_name
		HAVING tasks > 0
		ORDER BY tasks DESC
	""", as_dict=True)
	return rank_candidates([dict(r) for r in rows])


def show_candidates(limit=20):
	"""Print the candidates, so the ids can be read off for the mapping."""
	candidates = cost_project_candidates()
	# Every farm using each project, not the last one seen: three farms sharing
	# one project is normal -- same crop, same activity list -- and a note saying
	# "already used by Vale" when Saboti and Lokitela use it too reads as a
	# warning against a mapping that is in fact correct.
	used = {}
	for row in frappe.get_doc("Work Management Settings").get("farms") or []:
		if row.project:
			used.setdefault(row.project, []).append(row.farm)
	print("Projects that could be a farm's cost project -- likeliest first.")
	print("A farm's plannable activities are this project's Tasks.\n")
	print("  %-24s %-46s %6s  %s" % ("id", "name", "tasks", "note"))
	for row in candidates[:frappe.utils.cint(limit) or 20]:
		notes = []
		if row["likely"]:
			notes.append("reads like an activity list")
		if row["name"] in used:
			notes.append("already used by " + ", ".join(sorted(used[row["name"]])))
		print("  %-24s %-46s %6d  %s"
			% (row["name"], (row["project_name"] or "")[:46], row["tasks"],
			   "; ".join(notes)))
	if len(candidates) > (frappe.utils.cint(limit) or 20):
		print("\n  ... and %d more with Tasks"
			% (len(candidates) - (frappe.utils.cint(limit) or 20)))
	print("\nThen:\n  bench --site <site> execute "
		"work_management.setup.set_farm_cost_projects \\\n"
		"      --kwargs \"{'mapping': {'<farm>': '<project id>', ...}}\"")


def set_farm_cost_projects(mapping=None, restrict=None):
	"""Write each farm's cost project onto the farms table in Settings.

	`mapping` is {farm: project} and is required -- see the module docstring for
	why nothing here picks for you. `restrict` optionally sets the "Only work the
	Farms listed below" checkbox in the same save, which is worth doing when the
	mapping names every farm the project works: without it the rows supply cost
	projects and the screens still offer every farm Upande Core has.

	Validates before it writes. A farm Core has not got, or a project this site
	has not got, is reported and nothing is saved -- a half-applied mapping is
	harder to reason about than none.
	"""
	if not mapping:
		raise ValueError(
			"mapping is required, e.g. --kwargs \"{'mapping': "
			"{'Lokitela': 'PROJ-0031'}}\". Run "
			"work_management.setup.show_candidates to find the project ids.")

	problems = []
	for farm, project in sorted(mapping.items()):
		if not frappe.db.exists("Farm", farm):
			problems.append("no Farm named %s in Upande Core" % farm)
		if project and not frappe.db.exists("Project", project):
			problems.append("no Project named %s on this site" % project)
	if problems:
		raise ValueError("nothing written:\n  " + "\n  ".join(problems))

	settings = frappe.get_doc("Work Management Settings")
	plan = plan_farm_projects(settings.get("farms") or [], mapping)

	rows = {row.farm: row for row in settings.get("farms") or []}
	for farm, project in plan["add"]:
		settings.append("farms", {"farm": farm, "project": project})
	for farm, _was, project in plan["change"]:
		rows[farm].project = project

	restricted = False
	if restrict is not None and bool(settings.get("farms_restrict")) != bool(restrict):
		settings.farms_restrict = 1 if restrict else 0
		restricted = True

	if plan["add"] or plan["change"] or restricted:
		settings.save(ignore_permissions=True)
		frappe.db.commit()

	for farm, project in plan["add"]:
		print("  added    %-14s -> %s" % (farm, project))
	for farm, was, project in plan["change"]:
		print("  changed  %-14s %s -> %s" % (farm, was or "(none)", project))
	for farm in plan["unchanged"]:
		print("  already  %-14s -> %s" % (farm, mapping[farm]))
	if restricted:
		print("  farms_restrict -> %s" % (1 if restrict else 0))
	if not (plan["add"] or plan["change"] or restricted):
		print("  nothing to do; every farm already points at the project given")
	return plan
