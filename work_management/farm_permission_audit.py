"""Who has been working farms they are not permitted.

Step one of the farm-scoping rollout, and the step that is not optional. The app
is about to start honouring 202 Farm User Permissions it has ignored since it was
written. Enforcing a permission that has been ignored changes what 96 people see,
and some of them may have been relying on the gap to do their jobs. Turning it on
without measuring first converts a silent visibility gap into a loud access
problem, and makes the fix look like the outage.

So this reports, and changes nothing:

  * which farms each restricted person is permitted
  * which farms they have actually touched, and how often
  * the difference -- farms they worked and are not permitted

A person in that last column is either mis-permissioned or the permission is
wrong. Which one it is cannot be decided by a deploy. It is a question for
somebody who knows why the permission was written, and this exists to put the
question in front of them with the evidence attached.

Read-only. Nothing here writes, and it is deliberately not whitelisted: it names
who did what, which is not a screen, it is an answer to a question somebody
asked.

    bench --site <site> execute work_management.farm_permission_audit.print_report

    # or, for a window other than 90 days
    bench --site <site> execute work_management.farm_permission_audit.print_report \\
        --kwargs "{'days': 30}"
"""

import frappe

from work_management.api import config

# Every non-single Work Management record that carries both a farm and an owner is
# evidence of somebody working a farm. Discovered rather than listed, because the
# live site's copies are custom doctypes and a hardcoded list would quietly stop
# covering whatever gets added next.
FARM_COLUMN = "farm"
PERSON_COLUMNS = ("requested_by", "owner")


def carrier_doctypes():
	"""Work Management doctypes holding a farm and a person, and which column
	names the person.

	`requested_by` beats `owner` where both exist: on a planner request the owner
	can be whoever pressed save, and the requester is the person whose work it
	is. A single doctype has no table at all, and asking `has_column` about one
	raises rather than answering False -- which is worth stating because it has
	already broken this app once.
	"""
	out = []
	names = frappe.get_all("DocType", filters={"name": ("like", "Work Management%")},
		fields=["name"], order_by="name")
	for row in names:
		meta = frappe.get_meta(row.name)
		if meta.istable or meta.issingle:
			continue
		if not frappe.db.has_column(row.name, FARM_COLUMN):
			continue
		for column in PERSON_COLUMNS:
			if frappe.db.has_column(row.name, column):
				out.append((row.name, column))
				break
	return out


def touches(days=90):
	"""{user: {farm: how many records}}, over the last `days`.

	Counted from `modified`, not `creation`: a record somebody edited last week is
	work they did last week, whoever first created it.
	"""
	since = frappe.utils.add_days(frappe.utils.nowdate(), -abs(int(days)))
	out = {}
	for doctype, person in carrier_doctypes():
		rows = frappe.db.sql(
			"""
			SELECT `{person}` person, `{farm}` farm, COUNT(*) n
			FROM `tab{doctype}`
			WHERE IFNULL(`{person}`, '') != '' AND IFNULL(`{farm}`, '') != ''
			  AND modified >= %(since)s
			GROUP BY `{person}`, `{farm}`
			""".format(person=person, farm=FARM_COLUMN, doctype=doctype),
			{"since": since}, as_dict=True)
		for row in rows:
			out.setdefault(row.person, {})
			out[row.person][row.farm] = out[row.person].get(row.farm, 0) + int(row.n)
	return out


def worked_outside(permitted, touched):
	"""Farms in `touched` that `permitted` does not allow, worst first.

	`permitted` is None for an unrestricted person, and an unrestricted person can
	never be outside their permission -- so the answer there is empty, not
	"everything they touched".
	"""
	if permitted is None:
		return []
	outside = [(farm, n) for farm, n in (touched or {}).items() if farm not in permitted]
	return sorted(outside, key=lambda pair: (-pair[1], pair[0]))


def unused_permission(permitted, touched):
	"""Farms somebody is permitted and has not touched in the window.

	Not a problem on its own -- a manager may simply not have worked that farm
	this quarter -- but a permission nobody has ever used is the cheapest one to
	correct, so it is worth seeing beside the rest.
	"""
	if permitted is None:
		return []
	return sorted(f for f in permitted if f not in (touched or {}))


def audit(days=90):
	"""One row per person who is restricted or has touched a farm.

	Restricted people come first regardless of whether they are in breach,
	because the point is to see the whole set that enforcement would affect --
	including the ones for whom it changes nothing, which is the reassuring half.
	"""
	activity = touches(days=days)
	restricted = {}
	for row in frappe.get_all("User Permission", filters={"allow": "Farm"},
			fields=["user", "for_value", "applicable_for"], limit_page_length=0):
		restricted.setdefault(row.user, []).append(dict(row))

	people = set(restricted) | set(activity)
	rows = []
	for user in sorted(people):
		permitted = config.farms_from_permissions(restricted.get(user))
		touched = activity.get(user) or {}
		rows.append({
			"user": user,
			"permitted": sorted(permitted) if permitted else None,
			"touched": sorted(touched, key=lambda f: (-touched[f], f)),
			"touch_counts": touched,
			"outside": worked_outside(permitted, touched),
			"unused": unused_permission(permitted, touched),
		})
	rows.sort(key=lambda r: (
		0 if r["outside"] else (1 if r["permitted"] else 2),
		-sum(n for _f, n in r["outside"]),
		r["user"],
	))
	return {
		"days": abs(int(days)),
		"carriers": carrier_doctypes(),
		"rows": rows,
		"restricted_users": len([r for r in rows if r["permitted"]]),
		"in_breach": len([r for r in rows if r["outside"]]),
	}


def format_report(result):
	"""The audit as text somebody can paste into a decision."""
	lines = []
	carriers = ", ".join("%s (%s)" % (d, c) for d, c in result["carriers"])
	lines.append("Farm permission audit -- last %d days" % result["days"])
	lines.append("read from: %s" % (carriers or "no Work Management records carry a farm"))
	lines.append("")
	lines.append("%d users restricted to particular farms; %d of them worked a farm "
		"they are not permitted." % (result["restricted_users"], result["in_breach"]))
	lines.append("")

	breach = [r for r in result["rows"] if r["outside"]]
	if breach:
		lines.append("WORKED OUTSIDE THEIR PERMISSION -- each of these is a question")
		lines.append("for a person: is the permission wrong, or was the work?")
		lines.append("")
		for row in breach:
			lines.append("  %s" % row["user"])
			lines.append("      permitted: %s" % ", ".join(row["permitted"]))
			lines.append("      worked:    %s" % ", ".join(
				"%s x%d" % (f, row["touch_counts"][f]) for f in row["touched"]))
			lines.append("      OUTSIDE:   %s" % ", ".join(
				"%s x%d" % (f, n) for f, n in row["outside"]))
			lines.append("")

	clean = [r for r in result["rows"] if r["permitted"] and not r["outside"]]
	lines.append("RESTRICTED AND WITHIN THEIR PERMISSION -- %d users, unaffected by "
		"enforcement" % len(clean))
	for row in clean:
		worked = ", ".join(row["touched"]) or "nothing in this window"
		lines.append("  %-40s permitted %-28s worked %s"
			% (row["user"], ", ".join(row["permitted"]), worked))
	lines.append("")

	free = [r for r in result["rows"] if not r["permitted"] and r["touched"]]
	lines.append("UNRESTRICTED AND ACTIVE -- %d users, who see every farm by "
		"Frappe's own default" % len(free))
	for row in free[:40]:
		lines.append("  %-40s worked %s" % (row["user"], ", ".join(row["touched"])))
	if len(free) > 40:
		lines.append("  ... and %d more" % (len(free) - 40))
	return "\n".join(lines)


def print_report(days=90):
	print(format_report(audit(days=days)))
