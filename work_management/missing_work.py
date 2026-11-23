"""Missing work: task workers who were present but have no actuals that day.

A team leader or clerk sometimes forgets a worker who came to work. Without
this, that worker is simply not paid and nobody is told. Every task-worker day
with presence (a scan, or a Present / Half Day / Work From Home attendance) must
end in one of two states: actuals recorded, or a "no work given" reason (Work
Missing Day Excuse).

- Actuals > Missing work lists the open days and clears them (wm_missing_work).
- The payroll check blocks a farm's approval while it has open days.
- A daily email tells team leaders, farm managers and the GM/HR (send_reminders).

Rules (spec docs/superpowers/specs/2026-11-23-missing-work-design.md):
- Absent attendance beats a scan unless a Present-class record exists that day.
- Holidays on the employee's holiday list and approved leave are not missing.
- A day belongs to the farm of the crew the worker was on, else their home farm.
- Actuals anywhere that day (any crew, any farm, docstatus < 2) clear it.
"""

import datetime

import frappe

REASONS = ["Sent home – no work", "Rain / weather", "Sick / left early", "Scanned but not working", "Other"]
PRESENT = ("Present", "Half Day", "Work From Home")
CREW_STATES = ("Pending Farm Manager", "Pending HR Head", "Pending GM", "Assigned")


# ---- pure rules (no database) -------------------------------------------------

def present_days(employees, scans, present, absent, holidays, leaves):
	"""(employee, day) pairs where a task worker counts as present.

	employees: {emp: {"holiday_list", "joined", "relieved"}} -- task workers only
	scans, present, absent: sets of (emp, day); holidays: set of (holiday_list, day)
	leaves: {emp: [(from, to), ...]} approved leave."""
	out = set()
	for emp, day in set(scans) | set(present):
		e = employees.get(emp)
		if not e:
			continue
		if (emp, day) in absent and (emp, day) not in present:
			continue
		if e.get("holiday_list") and (e["holiday_list"], day) in holidays:
			continue
		if e.get("joined") and day < str(e["joined"]):
			continue
		if e.get("relieved") and day > str(e["relieved"]):
			continue
		if any(str(f) <= day <= str(t) for f, t in leaves.get(emp, [])):
			continue
		out.add((emp, day))
	return out


def crew_days(rows, from_date, to_date):
	"""Expand crew rows ({employee, start, end, assignment, farm, ...}) into
	{(emp, day): [crew, ...]} for the days inside from_date..to_date."""
	out = {}
	lo = datetime.date.fromisoformat(str(from_date))
	hi = datetime.date.fromisoformat(str(to_date))
	for r in rows:
		start = max(lo, datetime.date.fromisoformat(str(r["start"])))
		end = min(hi, datetime.date.fromisoformat(str(r["end"])))
		crew = {k: v for k, v in r.items() if k not in ("employee", "start", "end")}
		day = start
		while day <= end:
			out.setdefault((r["employee"], day.isoformat()), []).append(crew)
			day = day + datetime.timedelta(days=1)
	return out


def day_state(emp, day, L):
	"""Where a worker-day stands. "none": not present. "open": present with no work
	and no reason, or its reason was sent back. "waiting": its fix is in approval (a
	missing-day record not yet CONFIRMED, or a reason not yet Approved). "cleared":
	work in a normal record, a CONFIRMED missing-day record, or an Approved reason."""
	key = (emp, day)
	if key not in L["presence"]:
		return "none"
	if key in L["normal_actuals"]:
		return "cleared"
	fix = L["fix_states"].get(key)
	if fix:
		return "cleared" if fix == "CONFIRMED" else "waiting"
	ex = L["excuses"].get(key)
	if ex:
		status = ex.get("status") or "Approved"
		if status == "Approved":
			return "cleared"
		if status.startswith("Pending"):
			return "waiting"
	return "open"


def grid_codes(emp, days, L):
	"""One letter per day for the Missing work grid. Fix states first: M missing,
	W waiting for approval, R "no work" approved. Then attendance: A absent (X when
	HR has been asked to correct it), L leave, O off day / holiday, H half day,
	P present, ? no record. Lower case: work is recorded that day."""
	out = []
	for day in days:
		key = (emp, day)
		state = day_state(emp, day, L)
		worked = key in L["normal_actuals"] or key in L["fix_states"]
		if state == "open":
			out.append("M")
			continue
		if state == "waiting":
			out.append("W")
			continue
		ex = L["excuses"].get(key)
		if state == "cleared" and ex and not worked:
			out.append("R")
			continue
		if key in L["absent"] and key not in L["present"]:
			code = "X" if key in L["ar_open"] else "A"
		elif key in L["leave_days"]:
			code = "L"
		elif key in L["holiday_days"]:
			code = "O"
		elif key in L["half"]:
			code = "H"
		elif key in L["scans"] or key in L["present"]:
			code = "P"
		else:
			code = "?"
		out.append(code.lower() if worked and code not in ("X",) else code)
	return "".join(out)


def classify(presence, actuals, excuses, crews, home_farm, fix_states=None):
	"""One row per present day without work in a normal record:
	{employee, day, farm, crews, excuse, fix, state}, sorted by farm, day, employee.
	`state` is day_state's answer (open / waiting / cleared)."""
	L = {"presence": set(presence), "normal_actuals": set(actuals), "fix_states": fix_states or {},
		"excuses": excuses}
	out = []
	for emp, day in sorted(set(presence)):
		if (emp, day) in actuals:
			continue
		state = day_state(emp, day, L)
		if state == "cleared" and (emp, day) in L["fix_states"]:
			continue
		on = crews.get((emp, day)) or []
		out.append({
			"employee": emp,
			"day": day,
			"farm": on[0]["farm"] if on else home_farm.get(emp),
			"crews": on,
			"excuse": excuses.get((emp, day)),
			"fix": L["fix_states"].get((emp, day)),
			"state": state,
		})
	out.sort(key=lambda r: (r["farm"] or "", r["day"], r["employee"]))
	return out


# ---- queries ----------------------------------------------------------------------

def task_worker_sql():
	"""SQL condition on alias `e` (Employee): who is paid by the task. Same rule as
	the dashboard's people board: the payable lists in Settings, else 'Task Worker'."""
	conds = []
	for col, child, cf in (("employment_type", "Work Management Payable Employment Type", "employment_type"),
			("designation", "Work Management Payable Designation", "designation"),
			("custom_category", "Work Management Payable Category", "category")):
		if not frappe.get_meta("Employee").get_field(col) or not frappe.db.exists("DocType", child):
			continue
		vals = [str(r.get(cf) or "").strip() for r in frappe.get_all(child,
			filters={"parenttype": "Work Management Settings"}, fields=[cf])]
		vals = [frappe.db.escape(v) for v in vals if v]
		if vals:
			conds.append("e." + col + " IN (" + ", ".join(vals) + ")")
	return "(" + (" OR ".join(conds) if conds else "e.employment_type = 'Task Worker'") + ")"


def load(farms, from_date, to_date):
	"""Everything the rules need for from_date..to_date, in a fixed number of
	queries: task workers, presence, attendance, leave, holidays, work recorded
	(normal records and missing-day records apart), crews, reasons, attendance
	requests and sent-back missing-day records."""
	f, t = str(from_date), str(to_date)
	args = {"f": f, "t": t}
	emps = frappe.db.sql("""
		SELECT e.name, TRIM(IFNULL(e.custom_farm, '')) farm, IFNULL(e.holiday_list, '') holiday_list,
			e.date_of_joining joined, e.relieving_date relieved
		FROM `tabEmployee` e
		WHERE (e.status = 'Active' OR e.relieving_date >= %(f)s) AND """ + task_worker_sql(), args, as_dict=True)
	employees = {e.name: {"holiday_list": e.holiday_list, "joined": str(e.joined) if e.joined else None,
		"relieved": str(e.relieved) if e.relieved else None} for e in emps}
	home = {e.name: e.farm for e in emps}
	args["e"] = tuple(employees) or ("__none__",)

	scans = {(r[0], str(r[1])) for r in frappe.db.sql("""
		SELECT DISTINCT employee, DATE(`time`) FROM `tabEmployee Checkin`
		WHERE employee IN %(e)s AND `time` >= %(f)s AND `time` < DATE_ADD(%(t)s, INTERVAL 1 DAY)""", args)}
	present, absent, half = set(), set(), set()
	for emp, day, status in frappe.db.sql("""
		SELECT employee, attendance_date, status FROM `tabAttendance`
		WHERE docstatus = 1 AND employee IN %(e)s AND attendance_date BETWEEN %(f)s AND %(t)s""", args):
		(present if status in PRESENT else absent if status == "Absent" else set()).add((emp, str(day)))
		if status == "Half Day":
			half.add((emp, str(day)))
	lists = tuple({e["holiday_list"] for e in employees.values() if e["holiday_list"]}) or ("__none__",)
	holidays = {(r[0], str(r[1])) for r in frappe.db.sql("""
		SELECT parent, holiday_date FROM `tabHoliday`
		WHERE parent IN %(h)s AND holiday_date BETWEEN %(f)s AND %(t)s""", dict(args, h=lists))}
	leaves = {}
	for emp, lf, lt in frappe.db.sql("""
		SELECT employee, from_date, to_date FROM `tabLeave Application`
		WHERE docstatus = 1 AND status = 'Approved' AND employee IN %(e)s
		AND from_date <= %(t)s AND to_date >= %(f)s""", args):
		leaves.setdefault(emp, []).append((str(lf), str(lt)))

	presence = present_days(employees, scans, present, absent, holidays, leaves)

	normal_actuals, fix_states = set(), {}
	fix_sql = "IFNULL(ac.missing_work_fix, 0)" if frappe.get_meta("Work Management Actuals").has_field(
		"missing_work_fix") else "0"
	for emp, day, fix, state in frappe.db.sql("""
		SELECT we.employee, we.work_date, """ + fix_sql + """, ac.workflow_state FROM `tabWork Actuals Employee` we
		INNER JOIN `tabWork Management Actuals` ac ON ac.name = we.parent
		WHERE ac.docstatus < 2 AND we.employee IN %(e)s AND we.work_date BETWEEN %(f)s AND %(t)s""", args):
		if frappe.utils.cint(fix):
			fix_states[(emp, str(day))] = state or "Draft"
		else:
			normal_actuals.add((emp, str(day)))
	# Only crews the Actuals grid can still take entries on: not a plan closed early,
	# not an assignment whose whole crew has been released. A day on such a crew is
	# shown as "not on any crew", which offers Add to assignment.
	closed_sql = (" AND IFNULL(pl.custom_close_state, '') != 'Closed'"
		if frappe.get_meta("Work Management Planner").has_field("custom_close_state") else "")
	crew_rows = frappe.db.sql("""
		SELECT we.employee, a.name assignment, TRIM(a.farm) farm, IFNULL(tk.subject, a.task) task_name,
			IFNULL(a.block_section, '') block, IFNULL(a.planner_request, '') planner,
			IFNULL(pl.team_leader, '') team_leader, IFNULL(pl.master_plan, '') master_plan, IFNULL(pl.uom, '') uom,
			GREATEST(COALESCE(we.start_date, a.from_date), a.from_date) start,
			LEAST(COALESCE(CASE WHEN IFNULL(we.status, 'Active') = 'Left' THEN we.left_date END, a.to_date), a.to_date) end
		FROM `tabWork Assignment Employee` we
		INNER JOIN `tabWork Management Assigner` a ON a.name = we.parent
		LEFT JOIN `tabWork Management Planner` pl ON pl.name = a.planner_request
		LEFT JOIN `tabTask` tk ON tk.name = a.task
		WHERE a.docstatus < 2 AND a.workflow_state IN %(s)s AND we.employee IN %(e)s
		AND a.from_date <= %(t)s AND a.to_date >= %(f)s
		AND EXISTS (SELECT 1 FROM `tabWork Assignment Employee` w2 WHERE w2.parent = a.name
			AND IFNULL(w2.status, 'Active') != 'Left')""" + closed_sql, dict(args, s=CREW_STATES), as_dict=True)
	crews = crew_days([dict(r) for r in crew_rows if r.start and r.end and r.start <= r.end], f, t)
	excuses = {}
	for r in frappe.db.sql("""
		SELECT name, employee, work_date, reason, IFNULL(note, '') note, marked_by, marked_at,
			IFNULL(payroll_check, '') payroll_check, IFNULL(status, 'Pending Farm Manager') status,
			IFNULL(sent_back_by, '') sent_back_by, IFNULL(sent_back_reason, '') sent_back_reason
		FROM `tabWork Missing Day Excuse`
		WHERE employee IN %(e)s AND work_date BETWEEN %(f)s AND %(t)s""", args, as_dict=True):
		excuses[(r.employee, str(r.work_date))] = {"name": r.name, "reason": r.reason, "note": r.note,
			"marked_by": r.marked_by, "marked_at": str(r.marked_at or ""), "payroll_check": r.payroll_check,
			"status": r.status, "sent_back_by": r.sent_back_by, "sent_back_reason": r.sent_back_reason}
	ar_open = set()
	if frappe.db.exists("DocType", "Attendance Request"):
		for emp, af, at in frappe.db.sql("""SELECT employee, from_date, to_date FROM `tabAttendance Request`
			WHERE docstatus < 2 AND employee IN %(e)s AND from_date <= %(t)s AND to_date >= %(f)s""", args):
			day = datetime.date.fromisoformat(str(max(str(af), f)))
			last = datetime.date.fromisoformat(str(min(str(at), t)))
			while day <= last:
				ar_open.add((emp, day.isoformat()))
				day = day + datetime.timedelta(days=1)
	sent_back = {}
	if frappe.get_meta("Work Management Deleted Actuals").has_field("missing_employee"):
		for emp, day, by, why in frappe.db.sql("""SELECT missing_employee, missing_work_date, deleted_by, reason
			FROM `tabWork Management Deleted Actuals` WHERE missing_employee IN %(e)s
			AND missing_work_date BETWEEN %(f)s AND %(t)s ORDER BY deleted_on""", args):
			sent_back[(emp, str(day))] = {"by": by, "reason": why}
	holiday_days, leave_days = set(), set()
	for emp, info in employees.items():
		for (hl, day) in holidays:
			if hl and hl == info["holiday_list"]:
				holiday_days.add((emp, day))
	for emp, spans in leaves.items():
		for lf, lt in spans:
			day = datetime.date.fromisoformat(max(lf, f))
			last = datetime.date.fromisoformat(min(lt, t))
			while day <= last:
				leave_days.add((emp, day.isoformat()))
				day = day + datetime.timedelta(days=1)
	return {"employees": employees, "home": home, "rows": emps, "presence": presence, "scans": scans,
		"present": present, "absent": absent, "half": half, "holiday_days": holiday_days,
		"leave_days": leave_days, "normal_actuals": normal_actuals, "fix_states": fix_states, "crews": crews,
		"excuses": excuses, "ar_open": ar_open, "sent_back": sent_back}


def find(farms, from_date, to_date, include_excused=False):
	"""Missing days for these farms between from_date and to_date (inclusive):
	open days only; with include_excused, also days waiting for approval and days
	cleared by an approved reason (the screens show those)."""
	L = load(farms, from_date, to_date)
	wanted = set(farms or [])
	rows = [r for r in classify(L["presence"], L["normal_actuals"], L["excuses"], L["crews"], L["home"],
		L["fix_states"]) if r["farm"] in wanted]
	for r in rows:
		sb = L["sent_back"].get((r["employee"], r["day"]))
		if sb and r["state"] == "open":
			r["sent_back"] = sb
	return rows if include_excused else [r for r in rows if r["state"] == "open"]


def counts(farms, from_date, to_date):
	"""Unexcused missing days per farm."""
	out = {farm: 0 for farm in farms or []}
	for r in find(farms, from_date, to_date):
		out[r["farm"]] = out.get(r["farm"], 0) + 1
	return out


def grid(farm, from_date, to_date):
	"""The Missing work grid for one farm: every task worker whose home farm it is,
	plus anyone on its crews in the dates; one code per day (grid_codes). Workers
	with open days first."""
	L = load([farm], from_date, to_date)
	day = datetime.date.fromisoformat(str(from_date))
	last = datetime.date.fromisoformat(str(to_date))
	days = []
	while day <= last:
		days.append(day.isoformat())
		day = day + datetime.timedelta(days=1)
	on_crew = {emp for (emp, d), cs in L["crews"].items() for c in cs if c["farm"] == farm}
	workers = []
	for e in L["rows"]:
		if e.farm != farm and e.name not in on_crew:
			continue
		codes = grid_codes(e.name, days, L)
		workers.append({"emp": e.name, "cells": codes, "open": codes.count("M"), "waiting": codes.count("W")})
	names = {}
	if workers:
		for emp, nm, des in frappe.db.sql("SELECT name, employee_name, IFNULL(designation, '') FROM `tabEmployee` WHERE name IN %s",
			(tuple(w["emp"] for w in workers),)):
			names[emp] = (nm, des)
	for w in workers:
		w["name"], w["designation"] = names.get(w["emp"], (w["emp"], ""))
	workers.sort(key=lambda w: (-w["open"], -w["waiting"], w["name"] or ""))
	return {"days": days, "workers": workers, "L": L}


# ---- who may do what ------------------------------------------------------------

def may_record(cfg, roles, farm):
	"""May someone holding `roles` record work (and so excuse a day) on `farm`?
	The act_submit rule: System Manager, the enter_work grant, the GM, the HR
	head, or that farm's own farm manager -- and only on a configured farm."""
	if farm not in (cfg.get("farms") or []):
		return False
	held = set(roles or [])
	if held & {"System Manager", "General Manager"}:
		return True
	if held & set(cfg.get("hr_head_roles") or []):
		return True
	if held & set((cfg.get("capabilities") or {}).get("enter_work") or []):
		return True
	return (cfg.get("farm_approver_role") or {}).get(farm) in held


def may_add_late(cfg, roles, farm):
	"""May someone add a worker to a crew late inside an open payroll check?
	Only that farm's farm manager or the GM (the user's decision, 2026-11-23)."""
	if farm not in (cfg.get("farms") or []):
		return False
	held = set(roles or [])
	if held & {"System Manager", "General Manager"}:
		return True
	return (cfg.get("farm_approver_role") or {}).get(farm) in held


def user_farms(cfg, roles, permitted):
	"""The farms the Missing work tab shows: those this person may record work on,
	narrowed to their Farm user permissions when they have any."""
	farms = [f for f in cfg.get("farms") or [] if may_record(cfg, roles, f)]
	if permitted:
		farms = [f for f in farms if f in permitted]
	return farms


# ---- payroll check hooks ------------------------------------------------------------

def open_check(farm, day):
	"""The payroll check still with the farm managers that covers `day` and has
	`farm` not yet approved, or None. Top-ups are not counted."""
	rows = frappe.db.sql("""
		SELECT c.name, c.period_from, c.period_to FROM `tabWork Management Payroll Check` c
		INNER JOIN `tabWork Management Payroll Check Farm` f ON f.parent = c.name
		WHERE c.status = 'Farm Review' AND IFNULL(c.is_top_up, 0) = 0
		AND c.period_from <= %s AND c.period_to >= %s
		AND f.farm = %s AND IFNULL(f.status, '') != 'Approved'
		ORDER BY c.creation DESC LIMIT 1""", (day, day, farm), as_dict=True)
	if not rows:
		return None
	return {"name": rows[0].name, "period_from": str(rows[0].period_from), "period_to": str(rows[0].period_to)}


def current_check(farm):
	"""The newest payroll check still with the farm managers that has `farm` not yet
	approved, whatever its dates, or None. Top-ups are not counted."""
	rows = frappe.db.sql("""
		SELECT c.period_from FROM `tabWork Management Payroll Check` c
		INNER JOIN `tabWork Management Payroll Check Farm` f ON f.parent = c.name
		WHERE c.status = 'Farm Review' AND IFNULL(c.is_top_up, 0) = 0
		AND f.farm = %s AND IFNULL(f.status, '') != 'Approved'
		ORDER BY c.creation DESC LIMIT 1""", (farm,))
	return open_check(farm, str(rows[0][0])) if rows else None


def stamp_excuses(check, farm, period_from, period_to):
	"""Lock this farm's excuses in the check's dates to the check (farm approved)."""
	# an excuse whose day has since had work entered is stale: actuals win, so it is
	# neither locked into the check nor counted as an idle day
	frappe.db.sql("""UPDATE `tabWork Missing Day Excuse` x SET x.payroll_check = %s
		WHERE IFNULL(x.payroll_check, '') = '' AND x.farm = %s AND x.work_date BETWEEN %s AND %s
		AND NOT EXISTS (SELECT 1 FROM `tabWork Actuals Employee` we
			INNER JOIN `tabWork Management Actuals` ac ON ac.name = we.parent
			WHERE ac.docstatus < 2 AND we.employee = x.employee AND we.work_date = x.work_date)""",
		(check, farm, period_from, period_to))
	return frappe.db.sql("SELECT COUNT(*) FROM `tabWork Missing Day Excuse` WHERE payroll_check = %s", (check,))[0][0]


def unstamp_excuses(check):
	"""Free the excuses a check locked (sent back or cancelled)."""
	n = frappe.db.sql("SELECT COUNT(*) FROM `tabWork Missing Day Excuse` WHERE payroll_check = %s", (check,))[0][0]
	frappe.db.sql("UPDATE `tabWork Missing Day Excuse` SET payroll_check = '' WHERE payroll_check = %s", (check,))
	return n


# ---- the Actuals > Missing work endpoint ---------------------------------------------

def assignment_options(farm, from_date, to_date):
	"""Approved assignments on `farm` overlapping the dates whose crew still has an
	active worker -- where a worker who was on no crew can be added for a day. The
	Enter Actuals list hides plans already at target; a forgotten worker's day may
	belong to one of those."""
	return [dict(r, from_date=str(r.from_date), to_date=str(r.to_date)) for r in frappe.db.sql("""
		SELECT a.name, IFNULL(tk.subject, a.task) task_name, IFNULL(a.block_section, '') block,
			a.from_date, a.to_date
		FROM `tabWork Management Assigner` a
		LEFT JOIN `tabTask` tk ON tk.name = a.task
		WHERE a.docstatus < 2 AND a.workflow_state = 'Assigned' AND TRIM(a.farm) = %s
		AND a.from_date <= %s AND a.to_date >= %s
		AND EXISTS (SELECT 1 FROM `tabWork Assignment Employee` w2 WHERE w2.parent = a.name
			AND IFNULL(w2.status, 'Active') != 'Left')
		ORDER BY a.from_date, task_name""", (farm, to_date, from_date), as_dict=True)]


def permitted_farm_names(user):
	return [r[0] for r in frappe.db.sql("""SELECT DISTINCT for_value FROM `tabUser Permission`
		WHERE user = %s AND allow = 'Farm'""", (user,))]


def parse_rows(raw):
	if isinstance(raw, str):
		raw = frappe.parse_json(raw or "[]")
	return [r for r in raw or [] if r.get("employee") and r.get("day")]


@frappe.whitelist()
def wm_missing_work(**kwargs):
	from work_management.api.config import get_config

	cfg = get_config()
	roles = frappe.get_roles()
	action = kwargs.get("action") or frappe.form_dict.get("action")
	farms = user_farms(cfg, roles, permitted_farm_names(frappe.session.user))
	out = {}

	if action == "mw_list":
		farm = (kwargs.get("farm") or "").strip()
		chosen = [farm] if farm else farms[:1]
		chosen = [f for f in chosen if f in farms]
		check = current_check(chosen[0]) if len(chosen) == 1 else None
		from_date = kwargs.get("from_date") or (check or {}).get("period_from") or frappe.utils.add_days(
			frappe.utils.today(), -14)
		to_date = kwargs.get("to_date") or (check or {}).get("period_to") or frappe.utils.add_days(
			frappe.utils.today(), -1)
		# one pass over every farm of theirs: the farm buttons show each one's count
		all_rows = find(farms, from_date, to_date, include_excused=True) if chosen else []
		rows = [r for r in all_rows if r["farm"] in chosen]
		names = {r[0]: r[1] for r in frappe.db.sql("""SELECT name, employee_name FROM `tabEmployee`
			WHERE name IN %s""", (tuple({r["employee"] for r in rows}) or ("__none__",),))}
		scans = {}
		if rows:
			for emp, day, t1, t2 in frappe.db.sql("""SELECT employee, DATE(`time`), MIN(`time`), MAX(`time`)
				FROM `tabEmployee Checkin` WHERE employee IN %s AND `time` >= %s
				AND `time` < DATE_ADD(%s, INTERVAL 1 DAY) GROUP BY employee, DATE(`time`)""",
				(tuple({r["employee"] for r in rows}), from_date, to_date)):
				scans[(emp, str(day))] = (str(t1)[11:16], str(t2)[11:16])
		for r in rows:
			r["employee_name"] = names.get(r["employee"]) or r["employee"]
			r["scan"] = scans.get((r["employee"], r["day"]))
		out["rows"] = rows
		out["counts"] = {f: len([r for r in rows if r["farm"] == f and not r["excuse"]]) for f in chosen}
		out["farm_counts"] = {f: len([r for r in all_rows if r["farm"] == f and not r["excuse"]]) for f in farms}
		out["farms"] = farms
		out["farm"] = chosen[0] if chosen else ""
		out["from_date"] = str(from_date)
		out["to_date"] = str(to_date)
		out["open_check"] = check
		out["can_excuse"] = bool(chosen)
		out["late_farms"] = [f for f in chosen if may_add_late(cfg, roles, f)]
		out["reasons"] = REASONS
		out["assignments"] = assignment_options(chosen[0], from_date, to_date) if len(chosen) == 1 else []

	elif action == "mw_excuse":
		rows = parse_rows(kwargs.get("rows"))
		reason = (kwargs.get("reason") or "").strip()
		note = (kwargs.get("note") or "").strip()
		err = None
		if not rows:
			err = "Pick at least one worker-day."
		elif reason not in REASONS:
			err = "Pick a reason."
		elif reason == "Other" and not note:
			err = "Say what happened when the reason is Other."
		if not err:
			days = sorted({r["day"] for r in rows})
			missing = {(m["employee"], m["day"]): m for m in find(farms, days[0], days[-1], include_excused=True)}
			for r in rows:
				m = missing.get((r["employee"], r["day"]))
				if not m:
					err = r["employee"] + " on " + r["day"] + " is not a missing day (work is recorded, or not a farm of yours)."
				elif not may_record(cfg, roles, m["farm"]):
					err = "You may not record work on " + str(m["farm"]) + "."
				elif m["excuse"] and m["excuse"].get("payroll_check"):
					err = (r["employee"] + " on " + r["day"] + " is locked in payroll check " +
						m["excuse"]["payroll_check"] + ".")
				if err:
					break
		if err:
			out["error"] = err
		else:
			now = frappe.utils.now()
			for r in rows:
				m = missing[(r["employee"], r["day"])]
				if m["excuse"]:
					frappe.db.set_value("Work Missing Day Excuse", m["excuse"]["name"], {"reason": reason,
						"note": note, "marked_by": frappe.session.user, "marked_at": now})
					continue
				doc = frappe.new_doc("Work Missing Day Excuse")
				doc.employee = r["employee"]
				doc.farm = m["farm"]
				doc.work_date = r["day"]
				doc.reason = reason
				doc.note = note
				doc.assignment = m["crews"][0]["assignment"] if m["crews"] else None
				doc.marked_by = frappe.session.user
				doc.marked_at = now
				doc.insert(ignore_permissions=True)
			frappe.db.commit()
			out["excused"] = len(rows)

	elif action == "mw_unexcuse":
		names = kwargs.get("names")
		if isinstance(names, str):
			names = frappe.parse_json(names or "[]")
		err = None
		docs = frappe.get_all("Work Missing Day Excuse", filters={"name": ["in", names or ["__none__"]]},
			fields=["name", "farm", "payroll_check", "employee", "work_date"])
		if not docs:
			err = "Nothing to undo."
		for d in docs:
			if d.payroll_check:
				err = d.employee + " on " + str(d.work_date) + " is locked in payroll check " + d.payroll_check + "."
			elif not may_record(cfg, roles, d.farm):
				err = "You may not record work on " + str(d.farm) + "."
			if err:
				break
		if err:
			out["error"] = err
		else:
			for d in docs:
				frappe.delete_doc("Work Missing Day Excuse", d.name, ignore_permissions=True, force=True)
			frappe.db.commit()
			out["removed"] = len(docs)

	else:
		out["error"] = "unknown action: " + str(action)
	return out


# ---- the 07:30 reminder ----------------------------------------------------------------

SENDER = "Kaitet Work Management <notifications@karenroses.com>"


def split_emails(text):
	"""Settings lists: comma- or newline-separated."""
	return [x.strip() for x in str(text or "").replace("\n", ",").split(",") if x.strip()]


def leader_for(team_leader, master_plan, day, stand_ins):
	"""Who leads that crew on `day`: a dated stand-in for this leader on this
	master plan, else the leader."""
	for s in stand_ins or []:
		if (s.get("master_plan") == master_plan and s.get("team_leader") == team_leader
				and str(s.get("from_date")) <= day <= str(s.get("to_date"))):
			return s.get("stand_in") or team_leader
	return team_leader


def recipients(rows, stand_ins, users_with_email, fms_by_farm, notify):
	"""{email: {"rows": [...], "all_farms": bool}}. On-crew days go to the crew's
	leader (or stand-in) when they log in with an email; every day goes to its
	farm's managers; the notify list (GM, HR) gets every day as one summary."""
	out = {}

	def give(email, r, all_farms=False):
		if not email:
			return
		box = out.setdefault(email, {"rows": [], "all_farms": all_farms, "seen": set()})
		key = (r["employee"], r["day"])
		if key not in box["seen"]:
			box["seen"].add(key)
			box["rows"].append(r)

	for r in rows:
		for c in r["crews"][:1]:
			who = leader_for(c.get("team_leader"), c.get("master_plan"), r["day"], stand_ins)
			give(users_with_email.get(who), r)
		for fm in fms_by_farm.get(r["farm"]) or []:
			give(fm, r)
		for n in notify or []:
			give(n, r, True)
	for box in out.values():
		box.pop("seen", None)
	return out


def render_email(rows, all_farms, url):
	"""The email body: (for the summary) a count per farm, then each worker by
	farm, day and crew."""
	esc = frappe.utils.escape_html
	h = ['<div style="font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#222">']
	h.append("<p>These task workers were present (scan or attendance) but have no work recorded and no "
		"reason given. Enter their work, or say why there was none, in "
		'<a href="' + esc(url) + '">Actuals &gt; Missing work</a>. The payroll check will not let a farm '
		"approve until they are cleared.</p>")
	farms = sorted({r["farm"] or "" for r in rows})
	if all_farms:
		h.append('<table cellpadding="5" style="border-collapse:collapse;margin:0 0 12px 0">'
			'<tr style="background:#0a0a0a;color:#fafaf6"><th align="left">Farm</th><th>Days</th>'
			"<th>On a crew</th><th>Not on any crew</th></tr>")
		for f in farms:
			fr = [r for r in rows if r["farm"] == f]
			on = len([r for r in fr if r["crews"]])
			h.append("<tr><td>" + esc(f) + "</td><td align=\"right\">" + str(len(fr)) + "</td><td align=\"right\">" +
				str(on) + "</td><td align=\"right\">" + str(len(fr) - on) + "</td></tr>")
		h.append("</table>")
	for f in farms:
		h.append('<h3 style="margin:16px 0 4px 0;font-size:14px">' + esc(f) + "</h3>")
		h.append('<table cellpadding="4" style="border-collapse:collapse;width:100%">'
			'<tr style="background:#f4f3ef"><th align="left">Day</th><th align="left">Worker</th>'
			'<th align="left">Crew</th></tr>')
		for r in sorted([r for r in rows if r["farm"] == f], key=lambda x: (x["day"], x["crews"][0]["assignment"]
				if x["crews"] else "~", x.get("employee_name") or x["employee"])):
			c = r["crews"][0] if r["crews"] else None
			crew = (esc(c["task_name"] or "") + " &middot; " + esc(c["block"] or "") + " (" + esc(c["assignment"]) + ")"
				if c else "<i>not on any crew</i>")
			h.append("<tr><td>" + esc(r["day"]) + "</td><td>" + esc(r.get("employee_name") or r["employee"]) +
				" (" + esc(r["employee"]) + ")</td><td>" + crew + "</td></tr>")
		h.append("</table>")
	h.append("</div>")
	return "".join(h)


def send_reminders():
	"""Daily at 07:30 (hooks.py cron): yesterday and the six days before."""
	if not frappe.db.get_single_value("Work Management Settings", "missing_work_reminder"):
		return 0
	from work_management.api.config import get_config

	today = frappe.utils.today()
	from_date = frappe.utils.add_days(today, -7)
	to_date = frappe.utils.add_days(today, -1)
	farms = get_config().get("farms") or []
	rows = find(farms, from_date, to_date)
	if not rows:
		return 0
	names = {r[0]: r[1] for r in frappe.db.sql("SELECT name, employee_name FROM `tabEmployee` WHERE name IN %s",
		(tuple({r["employee"] for r in rows}),))}
	for r in rows:
		r["employee_name"] = names.get(r["employee"]) or r["employee"]
	plans = tuple({c["master_plan"] for r in rows for c in r["crews"] if c.get("master_plan")}) or ("__none__",)
	stand_ins = [dict(s) for s in frappe.db.sql("""SELECT parent master_plan, team_leader, stand_in, from_date, to_date
		FROM `tabWork Management Team Leader Stand In` WHERE parent IN %s""", (plans,), as_dict=True)] \
		if frappe.db.exists("DocType", "Work Management Team Leader Stand In") else []
	# a leader is a login (user) or an Employee ID; either way they need an email to be told
	users = {}
	for name, email in frappe.db.sql("SELECT name, email FROM `tabUser` WHERE enabled = 1 AND IFNULL(email, '') != ''"):
		users[name] = email
	for emp, uid in frappe.db.sql("""SELECT name, user_id FROM `tabEmployee` WHERE IFNULL(user_id, '') != ''"""):
		if uid in users:
			users[emp] = users[uid]
	fms = {}
	for farm, email in frappe.db.sql("""SELECT sa.scope, u.email FROM `tabWork Management Stage Approver` sa
		INNER JOIN `tabUser` u ON u.name = sa.user
		WHERE sa.parenttype = 'Work Management Settings' AND sa.stage_label = 'Actuals: Farm Manager'
		AND IFNULL(sa.scope, '') != '' AND u.enabled = 1"""):
		fms.setdefault(farm, []).append(email)
	notify = split_emails(frappe.db.get_single_value("Work Management Settings", "missing_work_notify"))
	base = frappe.utils.get_url("/work-actuals?tab=missing&from=" + from_date + "&to=" + to_date)
	sent = 0
	for email, box in recipients(rows, stand_ins, users, fms, notify).items():
		bf = sorted({r["farm"] for r in box["rows"]})
		url = base + ("&farm=" + bf[0] if len(bf) == 1 else "")
		frappe.sendmail(recipients=[email], sender=SENDER, add_css=False,
			subject="Missing work: " + str(len(box["rows"])) + " worker-day(s) with no actuals",
			message=render_email(box["rows"], box["all_farms"], url))
		sent = sent + 1
	return sent
