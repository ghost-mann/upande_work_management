"""Assign the day before (2026-11-26).

Crews should know their job before they arrive. An assignment for day D is due
before the cut-off (Settings, default 18:00) on D-1. Later is still allowed, but
whoever saves it gives a reason, the farm manager sees it when approving, and the
team leader card on the dashboard counts it (by team leader and by who saved).
A plan approved after the cut-off could not have been assigned earlier, so its
assignment carries "Plan approved late" without asking anybody.

At 16:00 farm managers (and the Settings list) get tomorrow's approved plans that
have no crew yet (send_reminder).

Spec: docs/superpowers/specs/2026-11-26-assign-day-before-design.md
"""

import datetime

import frappe

REASONS = ["Replacing absent worker", "Weather", "Urgent work", "Other"]
PLAN_LATE = "Plan approved late"
NO_REASON = "No reason given"
DEFAULT_CUTOFF = "18:00:00"
SENDER = "Kaitet Work Management <notifications@karenroses.com>"
LIVE_STATES = ("Pending Farm Manager", "Pending HR Head", "Pending GM", "Assigned")
PRESENT = ("Present", "Half Day", "Work From Home")


# ---- pure rules (no database) -------------------------------------------------

def norm_time(cutoff):
	"""'18:00' / '18:00:00' / timedelta -> 'HH:MM:SS'."""
	if isinstance(cutoff, datetime.timedelta):
		s = int(cutoff.total_seconds())
		return "%02d:%02d:%02d" % (s // 3600, (s % 3600) // 60, s % 60)
	c = str(cutoff or DEFAULT_CUTOFF).strip()
	parts = c.split(":")
	while len(parts) < 3:
		parts.append("00")
	return "%02d:%02d:%02d" % (int(parts[0]), int(parts[1]), int(float(parts[2])))


def deadline(start, cutoff=DEFAULT_CUTOFF):
	"""When an assignment starting on `start` is due: the day before, at the cut-off."""
	if not start:
		return None
	day = datetime.date.fromisoformat(str(start)[:10]) - datetime.timedelta(days=1)
	return str(day) + " " + norm_time(cutoff)


def is_late(saved_at, start, cutoff=DEFAULT_CUTOFF):
	"""True when it was saved after its deadline."""
	due = deadline(start, cutoff)
	if not due or not saved_at:
		return False
	return str(saved_at)[:19] > due


def reason_err(reason, note):
	"""An error for a late reason, else ""."""
	reason = (reason or "").strip()
	if not reason:
		return "Give a reason for assigning this late."
	if reason not in REASONS:
		return "Pick one of: " + ", ".join(REASONS) + "."
	if reason == "Other" and not (note or "").strip():
		return "Say why in the note when the reason is Other."
	return ""


def approved_at_of(custom_approved_at, approval_date):
	"""When a plan was approved: the exact time if kept, else the start of the approval day."""
	if custom_approved_at:
		return str(custom_approved_at)[:19]
	if approval_date:
		return str(approval_date)[:10] + " 00:00:00"
	return None


def day_status(scan, att, leave):
	"""Today's status for one worker: Leave > Present (scan or present-class attendance) >
	Absent > Not scanned. A scan beats an Absent mark; leave beats both."""
	if leave:
		return "Leave"
	if scan or att in PRESENT:
		return "Present"
	if att:
		return "Absent" if att == "Absent" else str(att)
	return "Not scanned"


def summarise(rows, cutoff=DEFAULT_CUTOFF):
	"""Late counts per team leader and per person who saved, plus the late rows.

	rows: {asg, start, created, approved_at, tl, tl_name, saver, saver_name,
	reason, note, farm, task, block}. Lateness comes from `created` against the
	deadline, so history counts too (no reason was asked then: NO_REASON).
	"Plan approved late" is counted apart, and not in pct_late."""
	groups = {"by_leader": {}, "by_saver": {}}
	late_rows = []
	for r in rows:
		due = deadline(r.get("start"), cutoff)
		late = is_late(r.get("created"), r.get("start"), cutoff)
		plan_late = late and (r.get("reason") == PLAN_LATE or
			bool(r.get("approved_at") and due and str(r["approved_at"])[:19] > due))
		reason = (PLAN_LATE if plan_late else (r.get("reason") or NO_REASON)) if late else None
		for kind, key, name in (("by_leader", r.get("tl") or "", r.get("tl_name") or r.get("tl") or "No team leader"),
								("by_saver", r.get("saver") or "", r.get("saver_name") or r.get("saver") or "Unknown")):
			g = groups[kind].get(key)
			if g is None:
				g = {"key": key, "name": name, "total": 0, "late": 0, "plan_late": 0, "reasons": {}}
				groups[kind][key] = g
			g["total"] += 1
			if plan_late:
				g["plan_late"] += 1
			elif late:
				g["late"] += 1
				g["reasons"][reason] = g["reasons"].get(reason, 0) + 1
		if late:
			lr = dict(r)
			lr.update({"deadline": due, "plan_late": 1 if plan_late else 0, "reason": reason,
				"created": str(r.get("created"))[:16], "start": str(r.get("start"))[:10]})
			late_rows.append(lr)
	out = {}
	for kind, g in groups.items():
		lst = []
		for v in g.values():
			reasons = v.pop("reasons")
			v["top_reason"] = (sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if reasons else None)
			v["pct_late"] = round(v["late"] * 100.0 / v["total"], 1) if v["total"] else None
			lst.append(v)
		out[kind] = sorted(lst, key=lambda v: (-v["late"], -(v["pct_late"] or 0), v["name"]))
	out["late_rows"] = sorted(late_rows, key=lambda x: (x["start"], x["created"]), reverse=True)
	return out


def unassigned_tomorrow(plans, taken, day):
	"""Approved plans starting on `day`, still open, with no crew yet."""
	return [p for p in plans if str(p.get("from_date"))[:10] == str(day)
		and not (p.get("custom_close_state") or "").strip() and p.get("name") not in taken]


# ---- settings and the save-time check ----------------------------------------

def cutoff_setting():
	return norm_time(frappe.db.get_single_value("Work Management Settings", "assign_cutoff_time") or DEFAULT_CUTOFF)


@frappe.whitelist()
def check(start=None, planner=None, now=None):
	"""Is an assignment starting on `start`, saved now, late? With the switch off,
	never. A plan approved after the deadline fills the reason in itself."""
	out = {"late": 0, "deadline": None, "auto_reason": None}
	if not frappe.db.get_single_value("Work Management Settings", "assign_day_before") or not start:
		return out
	cutoff = cutoff_setting()
	out["deadline"] = deadline(start, cutoff)
	now = str(now or frappe.utils.now())[:19]
	if not is_late(now, start, cutoff):
		return out
	out["late"] = 1
	if planner:
		p = frappe.db.get_value("Work Management Planner", planner, ["custom_approved_at", "approval_date"], as_dict=True)
		at = approved_at_of(p.custom_approved_at, p.approval_date) if p else None
		if at and at > out["deadline"]:
			out["auto_reason"] = PLAN_LATE
	return out


# ---- dashboard: team leader card tabs -----------------------------------------

def display_names(keys):
	"""Login -> full name, Employee ID -> employee name, else the key itself."""
	keys = [k for k in set(keys) if k]
	out = {}
	if not keys:
		return out
	for name, full in frappe.db.sql("SELECT name, full_name FROM `tabUser` WHERE name IN %s", (tuple(keys),)):
		out[name] = full or name
	rest = [k for k in keys if k not in out]
	if rest:
		for name, full in frappe.db.sql("SELECT name, employee_name FROM `tabEmployee` WHERE name IN %s", (tuple(rest),)):
			out[name] = full or name
	for k in keys:
		out.setdefault(k, k)
	return out


def late_report(farms, from_date, to_date, farm=None, team_leader=None):
	"""Late-assigning tab: assignments starting in the dates, late by their creation."""
	args = {"a": from_date, "b": to_date, "fms": tuple(farms) or ("__none__",)}
	where = " AND a.farm IN %(fms)s"
	if farm:
		where += " AND a.farm = %(fm)s"
		args["fm"] = farm
	if team_leader:
		where += " AND p.team_leader = %(tl)s"
		args["tl"] = team_leader
	rows = frappe.db.sql("""
		SELECT a.name asg, a.from_date start, a.creation created, a.farm, a.task,
			IFNULL(tk.subject, a.task) task_label, a.block_section block, a.workflow_state state,
			a.late_reason reason, a.late_note note,
			COALESCE(NULLIF(a.assigned_by, ''), a.owner) saver, IFNULL(p.team_leader, '') tl,
			p.custom_approved_at, p.approval_date
		FROM `tabWork Management Assigner` a
		LEFT JOIN `tabWork Management Planner` p ON p.name = a.planner_request
		LEFT JOIN `tabTask` tk ON tk.name = a.task
		WHERE a.docstatus < 2 AND IFNULL(a.workflow_state, '') != 'Rejected'
			AND a.from_date >= %(a)s AND a.from_date <= %(b)s""" + where + """
		ORDER BY a.from_date DESC""", args, as_dict=True)
	names = display_names([r.tl for r in rows] + [r.saver for r in rows])
	data = []
	for r in rows:
		data.append({"asg": r.asg, "start": str(r.start), "created": str(r.created), "farm": r.farm,
			"task_label": r.task_label or r.task, "block": r.block, "state": r.state,
			"reason": r.reason, "note": r.note,
			"approved_at": approved_at_of(r.custom_approved_at, r.approval_date),
			"tl": r.tl, "tl_name": names.get(r.tl) if r.tl else "",
			"saver": r.saver, "saver_name": names.get(r.saver) or r.saver})
	cutoff = cutoff_setting()
	out = summarise(data, cutoff)
	out["cutoff"] = cutoff[:5]
	out["switch_on"] = frappe.utils.cint(frappe.db.get_single_value("Work Management Settings", "assign_day_before"))
	return out


def day_statuses(emps, day):
	"""({emp: first scan HH:MM}, {emp: day_status}) for these workers on one day.
	Scans and attendance are read only for today or earlier; leave for any day."""
	ids = tuple(emps) or ("__none__",)
	scan, att, leave = {}, {}, {}
	if day <= str(frappe.utils.today()):
		for emp, t1 in frappe.db.sql("""SELECT employee, MIN(`time`) FROM `tabEmployee Checkin`
				WHERE employee IN %s AND `time` >= %s AND `time` < DATE_ADD(%s, INTERVAL 1 DAY)
				GROUP BY employee""", (ids, day, day)):
			scan[emp] = str(t1)[11:16]
		for emp, status in frappe.db.sql("""SELECT employee, status FROM `tabAttendance`
				WHERE docstatus = 1 AND attendance_date = %s AND employee IN %s""", (day, ids)):
			if att.get(emp) not in PRESENT:
				att[emp] = status
	for emp, lt in frappe.db.sql("""SELECT employee, leave_type FROM `tabLeave Application`
			WHERE docstatus = 1 AND status = 'Approved' AND from_date <= %s AND to_date >= %s
			AND employee IN %s""", (day, day, ids)):
		leave[emp] = lt or "Leave"
	return scan, {e: day_status(scan.get(e), att.get(e), leave.get(e)) for e in emps}


def crew_on_day(farms, day, farm=None):
	"""People tab list: per team leader, the workers on their crews on one day
	(assigned) and how many of them were present, absent or on leave. A worker on
	two of one leader's crews counts once. {leader: {assigned, present, absent,
	leave, not_scanned, name}}."""
	day = str(day or frappe.utils.today())
	args = {"d": day, "st": LIVE_STATES, "fms": tuple(farms) or ("__none__",)}
	where = ""
	if farm:
		where = " AND a.farm = %(fm)s"
		args["fm"] = farm
	rows = frappe.db.sql("""
		SELECT DISTINCT p.team_leader tl, we.employee emp
		FROM `tabWork Assignment Employee` we
		INNER JOIN `tabWork Management Assigner` a ON a.name = we.parent
		INNER JOIN `tabWork Management Planner` p ON p.name = a.planner_request
		WHERE IFNULL(p.team_leader, '') != '' AND a.docstatus < 2 AND a.workflow_state IN %(st)s
			AND a.farm IN %(fms)s""" + where + """
			AND COALESCE(we.start_date, a.from_date) <= %(d)s
			AND LEAST(COALESCE(CASE WHEN IFNULL(we.status,'Active') = 'Left' THEN we.left_date END, a.to_date), a.to_date) >= %(d)s""",
		args, as_dict=True)
	crews = {}
	for r in rows:
		crews.setdefault(r.tl, set()).add(r.emp)
	emps = sorted({e for s in crews.values() for e in s})
	st = day_statuses(emps, day)[1] if emps else {}
	names = display_names(list(crews))
	out = {}
	for tl, members in crews.items():
		c = {"assigned": len(members), "present": 0, "absent": 0, "leave": 0, "not_scanned": 0,
			"name": names.get(tl, tl)}
		for e in members:
			s = st.get(e, "Not scanned")
			if s == "Present":
				c["present"] += 1
			elif s in ("Leave", "On Leave"):
				c["leave"] += 1
			elif s == "Not scanned":
				c["not_scanned"] += 1
			else:
				c["absent"] += 1
		out[tl] = c
	return out


def crew_people(farms, from_date, to_date, team_leader, day=None):
	"""People tab: workers on the crews of activities this team leader leads, in the dates."""
	day = str(day or frappe.utils.today())
	rows = frappe.db.sql("""
		SELECT we.employee emp, we.employee_name name, a.name asg, a.farm,
			IFNULL(tk.subject, a.task) task_label, a.block_section block,
			COALESCE(we.start_date, a.from_date) since,
			LEAST(COALESCE(CASE WHEN IFNULL(we.status,'Active') = 'Left' THEN we.left_date END, a.to_date), a.to_date) until
		FROM `tabWork Assignment Employee` we
		INNER JOIN `tabWork Management Assigner` a ON a.name = we.parent
		INNER JOIN `tabWork Management Planner` p ON p.name = a.planner_request
		LEFT JOIN `tabTask` tk ON tk.name = a.task
		WHERE p.team_leader = %(tl)s AND a.docstatus < 2 AND a.workflow_state IN %(st)s
			AND a.farm IN %(fms)s
			AND COALESCE(we.start_date, a.from_date) <= %(b)s
			AND LEAST(COALESCE(CASE WHEN IFNULL(we.status,'Active') = 'Left' THEN we.left_date END, a.to_date), a.to_date) >= %(a)s
		ORDER BY we.employee_name, since""",
		{"tl": team_leader, "st": LIVE_STATES, "fms": tuple(farms) or ("__none__",), "a": from_date, "b": to_date},
		as_dict=True)
	people = {}
	asgs = set()
	for r in rows:
		asgs.add(r.asg)
		p = people.get(r.emp)
		if p is None:
			p = {"emp": r.emp, "name": r.name or r.emp, "farm": r.farm, "acts": [], "days": 0, "on_today": 0}
			people[r.emp] = p
		p["acts"].append({"asg": r.asg, "task_label": r.task_label, "block": r.block,
			"since": str(r.since), "until": str(r.until)})
		if str(r.since) <= day <= str(r.until):
			p["on_today"] = 1
	if asgs:
		for emp, n in frappe.db.sql("""
			SELECT ae.employee, COUNT(DISTINCT ae.work_date) FROM `tabWork Actuals Employee` ae
			INNER JOIN `tabWork Management Actuals` ac ON ac.name = ae.parent
			WHERE ac.assignment IN %(asg)s AND ac.docstatus < 2 AND IFNULL(ac.workflow_state, '') != 'Rejected'
				AND ae.work_date >= %(a)s AND ae.work_date <= %(b)s
			GROUP BY ae.employee""", {"asg": tuple(asgs), "a": from_date, "b": to_date}):
			if emp in people:
				people[emp]["days"] = int(n or 0)
	scan, st = day_statuses(list(people), day)
	for p in people.values():
		p["status"] = st.get(p["emp"], "Not scanned")
		p["scan"] = scan.get(p["emp"])
	return {"people": sorted(people.values(), key=lambda x: (-x["on_today"], x["name"])), "date": day,
		"team_leader": team_leader, "team_leader_name": display_names([team_leader]).get(team_leader, team_leader)}


def leaders_in(farms, from_date, to_date, farm=None):
	"""Team leaders on weekly plans overlapping the dates: [{key, name}] by name."""
	args = {"a": from_date, "b": to_date, "fms": tuple(farms) or ("__none__",)}
	where = " AND farm IN %(fms)s"
	if farm:
		where += " AND farm = %(fm)s"
		args["fm"] = farm
	keys = [r[0] for r in frappe.db.sql("""SELECT DISTINCT team_leader FROM `tabWork Management Planner`
		WHERE IFNULL(team_leader, '') != '' AND IFNULL(workflow_state, '') NOT IN ('Rejected', 'Draft')
		AND from_date <= %(b)s AND to_date >= %(a)s""" + where, args)]
	names = display_names(keys)
	return sorted([{"key": k, "name": names.get(k, k)} for k in keys], key=lambda x: x["name"])


# ---- 16:00 reminder ------------------------------------------------------------

def render_reminder(by_farm, day, url):
	esc = frappe.utils.escape_html
	h = ['<div style="font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#222">']
	h.append("<p>These plans start <b>tomorrow, " + esc(day) + "</b>, and have no crew yet. Assign them before " +
		"the cut-off today in <a href=\"" + esc(url) + "\">Work Assigner</a>, so the workers know their job " +
		"when they arrive. After the cut-off a reason is asked for.</p>")
	for farm in sorted(by_farm):
		h.append('<h3 style="margin:16px 0 4px 0;font-size:14px">' + esc(farm) + "</h3>")
		h.append('<table cellpadding="4" style="border-collapse:collapse;width:100%">'
			'<tr style="background:#f4f3ef"><th align="left">Plan</th><th align="left">Task</th>'
			'<th align="left">Block</th><th align="right">People</th><th align="left">Team leader</th></tr>')
		for p in by_farm[farm]:
			h.append("<tr><td>" + esc(p["name"]) + "</td><td>" + esc(p.get("task_label") or p.get("task") or "") +
				"</td><td>" + esc(p.get("block_section") or "") + "</td><td align=\"right\">" +
				esc(str(p.get("people_per_day") or "")) + "</td><td>" + esc(p.get("tl_name") or "") + "</td></tr>")
		h.append("</table>")
	h.append("</div>")
	return "".join(h)


def send_reminder():
	"""Daily at 16:00 (hooks.py cron): tomorrow's approved plans with no crew yet."""
	if not frappe.db.get_single_value("Work Management Settings", "assign_reminder"):
		return 0
	from work_management.missing_work import split_emails

	day = str(frappe.utils.add_days(frappe.utils.today(), 1))
	plans = frappe.get_all("Work Management Planner", filters={"workflow_state": "Approved", "from_date": day},
		fields=["name", "farm", "task", "block_section", "people_per_day", "custom_close_state", "team_leader", "from_date"])
	if not plans:
		return 0
	taken = set(frappe.get_all("Work Management Assigner",
		filters={"planner_request": ["in", [p.name for p in plans]], "workflow_state": ["!=", "Rejected"],
			"docstatus": ["<", 2]}, pluck="planner_request"))
	free = unassigned_tomorrow([dict(p) for p in plans], taken, day)
	if not free:
		return 0
	names = display_names([p.get("team_leader") for p in free])
	subjects = dict(frappe.db.sql("SELECT name, subject FROM `tabTask` WHERE name IN %s",
		(tuple({p.get("task") or "" for p in free}),)))
	by_farm = {}
	for p in free:
		p["tl_name"] = names.get(p.get("team_leader")) or ""
		p["task_label"] = subjects.get(p.get("task")) or p.get("task")
		by_farm.setdefault(p.get("farm") or "", []).append(p)
	fms = {}
	for farm, email in frappe.db.sql("""SELECT sa.scope, u.email FROM `tabWork Management Stage Approver` sa
		INNER JOIN `tabUser` u ON u.name = sa.user
		WHERE sa.parenttype = 'Work Management Settings' AND sa.stage_label = 'Assigner: Farm Manager'
		AND IFNULL(sa.scope, '') != '' AND u.enabled = 1 AND IFNULL(u.email, '') != ''"""):
		fms.setdefault(farm, []).append(email)
	boxes = {}
	for farm, lst in by_farm.items():
		for email in fms.get(farm, []):
			boxes.setdefault(email, {})[farm] = lst
	for email in split_emails(frappe.db.get_single_value("Work Management Settings", "assign_reminder_notify")):
		boxes[email] = dict(by_farm)
	url = frappe.utils.get_url("/work-assigner")
	sent = 0
	for email, box in boxes.items():
		n = sum(len(v) for v in box.values())
		frappe.sendmail(recipients=[email], sender=SENDER, add_css=False,
			subject="Tomorrow: " + str(n) + " plan(s) with no crew yet",
			message=render_reminder(box, day, url))
		sent += 1
	return sent
