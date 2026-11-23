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


def classify(presence, actuals, excuses, crews, home_farm):
	"""One row per present day with no actuals:
	{employee, day, farm, crews, excuse}, sorted by farm, day, employee."""
	out = []
	for emp, day in sorted(set(presence)):
		if (emp, day) in actuals:
			continue
		on = crews.get((emp, day)) or []
		out.append({
			"employee": emp,
			"day": day,
			"farm": on[0]["farm"] if on else home_farm.get(emp),
			"crews": on,
			"excuse": excuses.get((emp, day)),
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


def find(farms, from_date, to_date, include_excused=False):
	"""Missing days for these farms between from_date and to_date (inclusive)."""
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
	if not employees:
		return []
	args["e"] = tuple(employees)

	scans = {(r[0], str(r[1])) for r in frappe.db.sql("""
		SELECT DISTINCT employee, DATE(`time`) FROM `tabEmployee Checkin`
		WHERE employee IN %(e)s AND `time` >= %(f)s AND `time` < DATE_ADD(%(t)s, INTERVAL 1 DAY)""", args)}
	present, absent = set(), set()
	for emp, day, status in frappe.db.sql("""
		SELECT employee, attendance_date, status FROM `tabAttendance`
		WHERE docstatus = 1 AND employee IN %(e)s AND attendance_date BETWEEN %(f)s AND %(t)s""", args):
		(present if status in PRESENT else absent if status == "Absent" else set()).add((emp, str(day)))
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

	actuals = {(r[0], str(r[1])) for r in frappe.db.sql("""
		SELECT DISTINCT we.employee, we.work_date FROM `tabWork Actuals Employee` we
		INNER JOIN `tabWork Management Actuals` ac ON ac.name = we.parent
		WHERE ac.docstatus < 2 AND we.employee IN %(e)s AND we.work_date BETWEEN %(f)s AND %(t)s""", args)}
	crew_rows = frappe.db.sql("""
		SELECT we.employee, a.name assignment, TRIM(a.farm) farm, IFNULL(tk.subject, a.task) task_name,
			IFNULL(a.block_section, '') block, IFNULL(a.planner_request, '') planner,
			IFNULL(pl.team_leader, '') team_leader, IFNULL(pl.master_plan, '') master_plan,
			GREATEST(COALESCE(we.start_date, a.from_date), a.from_date) start,
			LEAST(COALESCE(CASE WHEN IFNULL(we.status, 'Active') = 'Left' THEN we.left_date END, a.to_date), a.to_date) end
		FROM `tabWork Assignment Employee` we
		INNER JOIN `tabWork Management Assigner` a ON a.name = we.parent
		LEFT JOIN `tabWork Management Planner` pl ON pl.name = a.planner_request
		LEFT JOIN `tabTask` tk ON tk.name = a.task
		WHERE a.docstatus < 2 AND a.workflow_state IN %(s)s AND we.employee IN %(e)s
		AND a.from_date <= %(t)s AND a.to_date >= %(f)s""", dict(args, s=CREW_STATES), as_dict=True)
	crews = crew_days([dict(r) for r in crew_rows if r.start and r.end and r.start <= r.end], f, t)
	excuses = {}
	for r in frappe.db.sql("""
		SELECT name, employee, work_date, reason, IFNULL(note, '') note, marked_by, marked_at,
			IFNULL(payroll_check, '') payroll_check
		FROM `tabWork Missing Day Excuse`
		WHERE employee IN %(e)s AND work_date BETWEEN %(f)s AND %(t)s""", args, as_dict=True):
		excuses[(r.employee, str(r.work_date))] = {"name": r.name, "reason": r.reason, "note": r.note,
			"marked_by": r.marked_by, "marked_at": str(r.marked_at or ""), "payroll_check": r.payroll_check}

	wanted = set(farms or [])
	return [r for r in classify(presence, actuals, excuses, crews, home)
		if r["farm"] in wanted and (include_excused or not r["excuse"])]


def counts(farms, from_date, to_date):
	"""Unexcused missing days per farm."""
	out = {farm: 0 for farm in farms or []}
	for r in find(farms, from_date, to_date):
		out[r["farm"]] = out.get(r["farm"], 0) + 1
	return out
