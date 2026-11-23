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
		WHERE IFNULL(x.payroll_check, '') = '' AND x.status = 'Approved' AND x.farm = %s
		AND x.work_date BETWEEN %s AND %s
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


# ---- approving "no work" reasons ----------------------------------------------------

# a reason's status for each Actuals approval step, in the Settings chain's order
REASON_STATUS = {"actuals_farm_manager": "Pending Farm Manager", "actuals_hr_head": "Pending HR",
	"actuals_gm": "Pending GM"}


def reason_chain(stage_rows):
	"""The statuses a reason goes through: the Actuals approval steps switched on
	in Settings, in order (farm manager, HR, GM)."""
	return [REASON_STATUS[r["key"]] for r in stage_rows or []
		if r.get("key") in REASON_STATUS and frappe.utils.cint(r.get("on"))] or ["Pending Farm Manager"]


REASON_ORDER = ["Pending Farm Manager", "Pending HR", "Pending GM"]
# a reason step's row in Settings > Approval stand-ins
STAND_IN_STAGE = {"Pending Farm Manager": "actuals_fm", "Pending HR": "actuals_hr", "Pending GM": "actuals_gm"}


def next_status(status, chain):
	"""The status after this step: the next step switched on, else Approved. A reason
	sitting at a step switched off since goes on to the next step that is on."""
	if status in chain:
		i = chain.index(status)
		return chain[i + 1] if i + 1 < len(chain) else "Approved"
	if status in REASON_ORDER:
		for later in REASON_ORDER[REASON_ORDER.index(status) + 1:]:
			if later in chain:
				return later
	return "Approved"


def reason_stand_ins():
	"""Settings > Approval stand-ins rows (stage, user, farm)."""
	if not frappe.db.exists("DocType", "Work Management Approval Stand In"):
		return []
	return frappe.get_all("Work Management Approval Stand In", filters={"parenttype": "Work Management Settings"},
		fields=["stage", "user", "farm"])


def may_step(status, roles, farm, cfg, user=None, stand_ins=None):
	"""May someone holding `roles` take the step a reason is waiting at? Farm manager
	step: that farm's farm manager, or the GM. HR step: the HR head. GM step: the
	General Manager. System Manager may take any step, and so may a stand-in listed
	for that step (and farm) in Settings > Approval stand-ins."""
	held = set(roles or [])
	if status not in ("Pending Farm Manager", "Pending HR", "Pending GM"):
		return False
	if "System Manager" in held:
		return True
	for si in stand_ins or []:
		if (user and si.get("user") == user and si.get("stage") == STAND_IN_STAGE[status]
				and (not si.get("farm") or str(si.get("farm")).strip() == str(farm or "").strip())):
			return True
	if status == "Pending Farm Manager":
		return "General Manager" in held or (cfg.get("farm_approver_role") or {}).get(farm) in held
	if status == "Pending HR":
		return bool(held & set(cfg.get("hr_head_roles") or []))
	return "General Manager" in held


def two_people_err(excuse, user):
	"""Strict two pairs of eyes on a reason: nobody approves a reason they gave,
	and nobody takes the GM step after taking the HR step. "" when fine."""
	if user and user == excuse.get("marked_by"):
		return "You marked this reason yourself, so somebody else must approve it."
	if excuse.get("status") == "Pending GM" and user and user == excuse.get("hr_by"):
		return "You took the HR step on this reason, so somebody else must give the GM approval."
	if user and user in (excuse.get("fm_by"), excuse.get("hr_by")):
		return "You already took a step on this reason, so somebody else must take this one."
	return ""


def stage_label(status):
	return {"Pending Farm Manager": "farm manager", "Pending HR": "HR", "Pending GM": "GM",
		"Pending HR Head": "HR", "Draft": "the enterer"}.get(status, status)


# ---- the Actuals > Missing work endpoint ---------------------------------------------

def assignment_options(farm, from_date, to_date):
	"""Approved assignments on `farm` overlapping the dates whose crew still has an
	active worker -- where a worker who was on no crew can be added for a day. The
	Enter Actuals list hides plans already at target; a forgotten worker's day may
	belong to one of those."""
	return [dict(r, from_date=str(r.from_date), to_date=str(r.to_date)) for r in frappe.db.sql("""
		SELECT a.name, IFNULL(tk.subject, a.task) task_name, IFNULL(a.block_section, '') block,
			a.from_date, a.to_date, IFNULL(pl.uom, '') uom
		FROM `tabWork Management Assigner` a
		LEFT JOIN `tabTask` tk ON tk.name = a.task
		LEFT JOIN `tabWork Management Planner` pl ON pl.name = a.planner_request
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
			chain = reason_chain(cfg.get("stage_rows"))
			days = sorted({r["day"] for r in rows})
			missing = {(m["employee"], m["day"]): m for m in find(farms, days[0], days[-1], include_excused=True)}
			for r in rows:
				m = missing.get((r["employee"], r["day"]))
				ex = (m or {}).get("excuse") or {}
				if not m:
					err = r["employee"] + " on " + r["day"] + " is not a missing day (work is recorded, or not a farm of yours)."
				elif not may_record(cfg, roles, m["farm"]):
					err = "You may not record work on " + str(m["farm"]) + "."
				elif m.get("fix"):
					err = r["employee"] + " on " + r["day"] + " has work waiting for approval."
				elif ex.get("payroll_check"):
					err = (r["employee"] + " on " + r["day"] + " is locked in payroll check " +
						ex["payroll_check"] + ".")
				elif ex and ex.get("status") not in ("Sent back", chain[0]):
					err = (r["employee"] + " on " + r["day"] + "'s reason is already approved by the " +
						stage_label(chain[0]) + "; ask for it to be sent back to change it.")
				if err:
					break
		if err:
			out["error"] = err
		else:
			now = frappe.utils.now()
			for r in rows:
				m = missing[(r["employee"], r["day"])]
				if m["excuse"]:
					# marked again (after a send back, or before anyone approved it): starts over
					frappe.db.set_value("Work Missing Day Excuse", m["excuse"]["name"], {"reason": reason,
						"note": note, "marked_by": frappe.session.user, "marked_at": now, "status": chain[0],
						"sent_back_by": None, "sent_back_at": None, "sent_back_reason": None,
						"fm_by": None, "fm_at": None, "hr_by": None, "hr_at": None, "gm_by": None, "gm_at": None})
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
				doc.status = chain[0]
				doc.insert(ignore_permissions=True)
			frappe.db.commit()
			out["excused"] = len(rows)

	elif action == "mw_unexcuse":
		names = kwargs.get("names")
		if isinstance(names, str):
			names = frappe.parse_json(names or "[]")
		err = None
		docs = frappe.get_all("Work Missing Day Excuse", filters={"name": ["in", names or ["__none__"]]},
			fields=["name", "farm", "payroll_check", "employee", "work_date", "status"])
		first = reason_chain(cfg.get("stage_rows"))[0]
		if not docs:
			err = "Nothing to undo."
		for d in docs:
			if d.payroll_check:
				err = d.employee + " on " + str(d.work_date) + " is locked in payroll check " + d.payroll_check + "."
			elif d.status not in (first, "Sent back"):
				err = d.employee + " on " + str(d.work_date) + "'s reason is already approved by the " + stage_label(first) + "."
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

	elif action == "mw_approve" or action == "mw_send_back":
		names = kwargs.get("names")
		if isinstance(names, str):
			names = frappe.parse_json(names or "[]")
		why = (kwargs.get("reason") or "").strip()
		chain = reason_chain(cfg.get("stage_rows"))
		docs = frappe.get_all("Work Missing Day Excuse", filters={"name": ["in", names or ["__none__"]]},
			fields=["name", "farm", "employee", "work_date", "status", "marked_by", "fm_by", "hr_by", "payroll_check"])
		sis = reason_stand_ins()
		err = None
		if not docs:
			err = "Nothing picked."
		elif action == "mw_send_back" and not why:
			err = "Say why it is being sent back."
		for d in docs:
			if err:
				break
			label = d.employee + " on " + str(d.work_date)
			if not may_step(d.status, roles, d.farm, cfg, frappe.session.user, sis):
				err = label + ": waiting for the " + stage_label(d.status) + ", which is not you."
			elif action == "mw_approve" and two_people_err(d, frappe.session.user):
				err = label + ": " + two_people_err(d, frappe.session.user)
		if err:
			out["error"] = err
		else:
			now = frappe.utils.now()
			for d in docs:
				if action == "mw_send_back":
					frappe.db.set_value("Work Missing Day Excuse", d.name, {"status": "Sent back",
						"sent_back_by": frappe.session.user, "sent_back_at": now, "sent_back_reason": why})
					continue
				step = {"Pending Farm Manager": "fm", "Pending HR": "hr", "Pending GM": "gm"}[d.status]
				frappe.db.set_value("Work Missing Day Excuse", d.name, {"status": next_status(d.status, chain),
					step + "_by": frappe.session.user, step + "_at": now})
			frappe.db.commit()
			out["done"] = len(docs)

	elif action == "mw_waiting":
		farm = (kwargs.get("farm") or "").strip()
		chosen = tuple([f for f in ([farm] if farm else farms) if f in farms]) or ("__none__",)
		me = frappe.session.user
		held = set(roles)
		work = []
		for r in frappe.db.sql("""
			SELECT ac.name, ac.farm, ac.workflow_state stage, ac.entered_by, ac.owner, ac.hr_approved_by,
				IFNULL(tk.subject, ac.task) task_name, we.employee, we.employee_name, we.work_date,
				we.actual_quantity qty, we.amount, IFNULL(pl.uom, '') uom
			FROM `tabWork Management Actuals` ac
			INNER JOIN `tabWork Actuals Employee` we ON we.parent = ac.name
			LEFT JOIN `tabTask` tk ON tk.name = ac.task
			LEFT JOIN `tabWork Management Assigner` a ON a.name = ac.assignment
			LEFT JOIN `tabWork Management Planner` pl ON pl.name = a.planner_request
			WHERE ac.missing_work_fix = 1 AND ac.docstatus < 2 AND ac.workflow_state != 'CONFIRMED'
			AND ac.farm IN %s ORDER BY ac.workflow_state, we.work_date""", (chosen,), as_dict=True):
			entered = r.entered_by or r.owner
			stage = r.stage
			can = me != entered and (("System Manager" in held) or (
				stage == "Pending Farm Manager" and ("General Manager" in held or
					(cfg.get("farm_approver_role") or {}).get(r.farm) in held)) or (
				stage == "Pending HR Head" and bool(held & set(cfg.get("hr_head_roles") or []))) or (
				stage == "Pending GM" and "General Manager" in held and me != r.hr_approved_by))
			work.append({"name": r.name, "farm": r.farm, "employee": r.employee, "employee_name": r.employee_name,
				"day": str(r.work_date), "task_name": r.task_name, "qty": frappe.utils.flt(r.qty), "uom": r.uom,
				"amount": frappe.utils.flt(r.amount), "stage": stage, "stage_label": stage_label(stage),
				"entered_by": entered, "can_act": 1 if can else 0})
		reasons = []
		sis = reason_stand_ins()
		for r in frappe.db.sql("""
			SELECT x.name, x.farm, x.employee, x.employee_name, x.work_date, x.reason, IFNULL(x.note, '') note,
				x.status, x.marked_by, x.fm_by, x.hr_by
			FROM `tabWork Missing Day Excuse` x
			WHERE x.status LIKE 'Pending%%' AND x.farm IN %s ORDER BY x.status, x.work_date""", (chosen,), as_dict=True):
			can = may_step(r.status, roles, r.farm, cfg, me, sis) and not two_people_err(r, me)
			reasons.append({"name": r.name, "farm": r.farm, "employee": r.employee, "employee_name": r.employee_name,
				"day": str(r.work_date), "reason": r.reason, "note": r.note, "stage": r.status,
				"stage_label": stage_label(r.status), "marked_by": r.marked_by, "can_act": 1 if can else 0})
		out["work"] = work
		out["reasons"] = reasons
		out["your_turn"] = len([x for x in work if x["can_act"]]) + len([x for x in reasons if x["can_act"]])

	elif action == "mw_ask_hr":
		emp = (kwargs.get("employee") or "").strip()
		day = str(kwargs.get("day") or "").strip()
		efarm = str(frappe.db.get_value("Employee", emp, "custom_farm") or "").strip() if emp else ""
		err = None
		if not emp or not day:
			err = "Pick the worker and the day."
		elif not may_record(cfg, roles, efarm):
			err = "You may not record work on " + (efarm or "that farm") + "."
		elif frappe.db.get_value("Employee", emp, "status") != "Active":
			err = (emp + " is no longer active, so an attendance request cannot be raised for them. "
				"Ask HR to correct " + day + " directly.")
		elif not frappe.db.sql("""SELECT 1 FROM `tabAttendance` WHERE employee = %s AND attendance_date = %s
			AND docstatus = 1 AND status = 'Absent' LIMIT 1""", (emp, day)):
			err = emp + " is not marked Absent on " + day + "."
		elif frappe.db.sql("""SELECT 1 FROM `tabAttendance Request` WHERE employee = %s AND from_date <= %s
			AND to_date >= %s AND docstatus < 2 LIMIT 1""", (emp, day, day)):
			err = "HR was already asked to correct " + emp + "'s attendance on " + day + "."
		if err:
			out["error"] = err
		else:
			try:
				ar = frappe.new_doc("Attendance Request")
				ar.employee = emp
				ar.company = frappe.db.get_value("Employee", emp, "company")
				ar.from_date = day
				ar.to_date = day
				ar.reason = "On Duty"
				ar.explanation = ("Marked Absent on " + day + " but at work, says " + frappe.session.user +
					" (Actuals > Missing work). Approving this makes the day Present so the work can be recorded.")
				ar.insert(ignore_permissions=True)
				# into HR's queue: the state its own workflow moves a draft to when sent for approval
				nxt = frappe.db.sql("""SELECT t.next_state FROM `tabWorkflow Transition` t
					INNER JOIN `tabWorkflow` w ON w.name = t.parent
					WHERE w.document_type = 'Attendance Request' AND w.is_active = 1
					AND t.state = %s AND t.next_state IN (SELECT s.state FROM `tabWorkflow Document State` s
						WHERE s.parent = w.name AND s.doc_status = '0')
					AND t.next_state != t.state ORDER BY t.idx LIMIT 1""", (ar.get("workflow_state") or "",))
				if nxt:
					frappe.db.set_value("Attendance Request", ar.name, "workflow_state", nxt[0][0], update_modified=False)
				frappe.db.commit()
				out["request"] = ar.name
			except Exception as exc:
				frappe.db.rollback()
				frappe.log_error(frappe.get_traceback(), "Missing work: attendance request for " + emp + " " + day)
				out["error"] = ("The attendance request could not be raised: " +
					frappe.utils.strip_html(str(exc)).strip().rstrip(".") + ". Ask HR to correct " + day + " directly.")

	elif action == "mw_grid":
		farm = (kwargs.get("farm") or "").strip()
		chosen = farm if farm in farms else (farms[0] if farms else "")
		if not chosen:
			out["farms"] = []
			out["workers"] = []
			return out
		check = current_check(chosen)
		from_date = kwargs.get("from_date") or (check or {}).get("period_from") or frappe.utils.add_days(
			frappe.utils.today(), -14)
		to_date = kwargs.get("to_date") or (check or {}).get("period_to") or frappe.utils.add_days(
			frappe.utils.today(), -1)
		g = grid(chosen, from_date, to_date)
		L = g.pop("L")
		rows = classify(L["presence"], L["normal_actuals"], L["excuses"], L["crews"], L["home"], L["fix_states"])
		out["farm_counts"] = {f: len([r for r in rows if r["farm"] == f and r["state"] == "open"]) for f in farms}
		# what a click on a cell needs: the worker-days with something to show
		details = {}
		for r in rows:
			if r["farm"] == chosen:
				details[r["employee"] + "|" + r["day"]] = {"crews": r["crews"], "excuse": r["excuse"], "fix": r["fix"],
					"state": r["state"], "sent_back": L["sent_back"].get((r["employee"], r["day"]))}
		wanted = [w["emp"] for w in g["workers"]]
		if wanted:
			for emp, day, t1, t2 in frappe.db.sql("""SELECT employee, DATE(`time`), MIN(`time`), MAX(`time`)
				FROM `tabEmployee Checkin` WHERE employee IN %s AND `time` >= %s
				AND `time` < DATE_ADD(%s, INTERVAL 1 DAY) GROUP BY employee, DATE(`time`)""",
				(tuple(wanted), from_date, to_date)):
				k = emp + "|" + str(day)
				if k in details:
					details[k]["scan"] = [str(t1)[11:16], str(t2)[11:16]]
		out.update(g)
		out["details"] = details
		out["farm"] = chosen
		out["farms"] = farms
		out["from_date"] = str(from_date)
		out["to_date"] = str(to_date)
		out["open_check"] = check
		out["assignments"] = assignment_options(chosen, from_date, to_date)
		out["late_farms"] = [chosen] if may_add_late(cfg, roles, chosen) else []
		out["reasons"] = REASONS
		out["can_ask_hr"] = 1 if may_record(cfg, roles, chosen) else 0

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
