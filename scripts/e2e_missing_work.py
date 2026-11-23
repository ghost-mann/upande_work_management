"""End-to-end test of Actuals > Missing work, in real browsers, as real users.

Run from the bench's sites folder, against a site with a copy of live data and
a dev server running:

    cd ~/frappe-v16-bench/sites
    ../env/bin/python ~/vscodeProjects/work_management/scripts/e2e_missing_work.py \
        --site webstore.localhost --url http://127.0.0.1:8003

Users (password "admin" on the copy): a clerk who records work (brendaw@, Work
Entry), Vale's farm manager (kibett@), HR (hro@) and the GM (koskey@).

Everything the run creates is removed at the end, and anything it changed
(a plan's quantity, an employee's holiday list) is put back. Never run it on a
live site.
"""

import argparse
import json
import sys
import time
import traceback

import frappe
from playwright.sync_api import sync_playwright

CLERK = "brendaw@lokitelaorchards.com"
FM = "kibett@lokitelaorchards.com"
HR = "hro@endebesscoffee.com"
GM = "koskey@lokitelaorchards.com"
FARM = "Vale"
PASSWORD = "admin"

RESULTS = []
RESTORE = []   # (doctype, name, field, old value)
CREATED = []   # (doctype, name) made by the run
CHECKS = []    # payroll checks made by the run


def check(name, ok, detail=""):
	RESULTS.append((name, bool(ok), detail))
	print(("PASS  " if ok else "FAIL  ") + name + (("  -- " + str(detail)) if detail and not ok else ""))
	return ok


def fresh():
	frappe.db.rollback()


def as_user(user):
	frappe.set_user(user)


def mw(user, **kw):
	from work_management import missing_work
	fresh()
	as_user(user)
	out = missing_work.wm_missing_work(**kw)
	frappe.db.commit()
	return out


def actuals_api(user, **kw):
	from work_management.api.actuals import wm_actuals
	fresh()
	as_user(user)
	frappe.local.form_dict = frappe._dict(kw)
	out = wm_actuals()
	frappe.db.commit()
	return out


def payment_api(user, **kw):
	from work_management.api.payment import wm_payment
	fresh()
	as_user(user)
	frappe.local.form_dict = frappe._dict(kw)
	out = wm_payment()
	frappe.db.commit()
	return out


def day_state(emp, day):
	from work_management.missing_work import find
	fresh()
	as_user("Administrator")
	rows = [r for r in find([FARM], day, day, include_excused=True) if r["employee"] == emp]
	return rows[0] if rows else None


def set_temp(doctype, name, field, value):
	old = frappe.db.get_value(doctype, name, field)
	RESTORE.append((doctype, name, field, old))
	frappe.db.set_value(doctype, name, field, value, update_modified=False)
	frappe.db.commit()


# ---- browser helpers -------------------------------------------------------------

class UI:
	def __init__(self, browser, url):
		self.browser = browser
		self.url = url
		self.pages = {}
		self.errors = []

	def page(self, user):
		if user not in self.pages:
			ctx = self.browser.new_context(viewport={"width": 1400, "height": 1000})
			pg = ctx.new_page()
			pg.on("pageerror", lambda e, u=user: self.errors.append(u + ": " + str(e)))
			pg.goto(self.url + "/login")
			pg.evaluate("""([u, p]) => fetch('/api/method/login', {method: 'POST',
				headers: {'Content-Type': 'application/x-www-form-urlencoded'},
				body: 'usr=' + encodeURIComponent(u) + '&pwd=' + encodeURIComponent(p)})""", [user, PASSWORD])
			self.pages[user] = pg
		return self.pages[user]

	def grid(self, user, frm, to, farm=None):
		pg = self.page(user)
		pg.goto(self.url + "/work-actuals?tab=missing&farm=" + (farm or FARM) + "&from=" + frm + "&to=" + to)
		pg.wait_for_selector("table.mw-grid, .mw-clear", timeout=90000)
		return pg

	def waiting(self, user):
		pg = self.page(user)
		pg.goto(self.url + "/work-actuals?tab=missing&farm=" + FARM)
		pg.wait_for_selector("[data-mw-view='wait']", timeout=90000)
		pg.click("[data-mw-view='wait']")
		pg.wait_for_selector("#mw-body .mw-group, #mw-body .mw-clear", timeout=90000)
		return pg

	@staticmethod
	def toast(pg):
		pg.wait_for_timeout(300)
		return pg.locator("#ac-toast").inner_text()

	def open_cell(self, pg, emp, day):
		cell = pg.locator('[data-mw-cell="%s|%s"]' % (emp, day))
		cell.scroll_into_view_if_needed()
		cell.click()
		pg.wait_for_selector("#mw-pn:not([hidden])")

	def wait_reload(self, pg):
		pg.wait_for_timeout(2500)
		pg.wait_for_selector("#mw-body table.mw-grid, #mw-body .mw-group, #mw-body .mw-clear", timeout=90000)

	def approve_work(self, user, name, quality=None):
		pg = self.waiting(user)
		btn = pg.locator('[data-mw-ok="%s"]' % name)
		if not btn.count():
			return "no Approve button for " + user
		if quality:
			grp = pg.locator(".mw-group", has=btn)
			grp.locator('[data-mw-q="%s"]' % quality).click()
		btn.click()
		self.wait_reload(pg)
		return ""

	def approve_reason(self, user, name):
		pg = self.waiting(user)
		btn = pg.locator('[data-mw-ok="%s"]' % name)
		if not btn.count():
			return "no Approve button for " + user
		btn.click()
		self.wait_reload(pg)
		return ""

	def send_back(self, user, name, why):
		pg = self.waiting(user)
		opener = pg.locator('[data-mw-backopen="%s"]' % name)
		if not opener.count():
			return "no Send back button for " + user
		opener.click()
		pg.fill('[data-mw-backwhy="%s"]' % name, why)
		pg.click('[data-mw-back="%s"]' % name)
		self.wait_reload(pg)
		return ""


# ---- picking test days --------------------------------------------------------------

def plan_room(asg):
	pr = frappe.db.get_value("Work Management Assigner", asg, "planner_request")
	target = frappe.utils.flt(frappe.db.get_value("Work Management Planner", pr, "quantity"))
	done = frappe.utils.flt(frappe.db.sql("""SELECT COALESCE(SUM(ac.total_actual_qty), 0)
		FROM `tabWork Management Actuals` ac INNER JOIN `tabWork Management Assigner` a ON a.name = ac.assignment
		WHERE a.planner_request = %s AND ac.workflow_state IN ('Pending Farm Manager','Pending HR Head','Pending GM','CONFIRMED')""",
		(pr,))[0][0])
	return pr, target - done


def make_room(asg, need):
	pr, room = plan_room(asg)
	if room < need:
		set_temp("Work Management Planner", pr, "quantity",
			frappe.utils.flt(frappe.db.get_value("Work Management Planner", pr, "quantity")) + need - room + 1)


def has_main_record(asg):
	return bool(frappe.db.sql("""SELECT 1 FROM `tabWork Management Actuals` WHERE assignment = %s
		AND IFNULL(missing_work_fix, 0) = 0 AND workflow_state IN
		('Pending Farm Manager','Pending HR Head','Pending GM','CONFIRMED') LIMIT 1""", (asg,)))


def fix_record(emp, day):
	fresh()
	r = frappe.db.sql("""SELECT ac.name, ac.workflow_state FROM `tabWork Management Actuals` ac
		INNER JOIN `tabWork Actuals Employee` we ON we.parent = ac.name
		WHERE ac.missing_work_fix = 1 AND we.employee = %s AND we.work_date = %s AND ac.docstatus < 2""",
		(emp, day), as_dict=True)
	return r[0] if r else None


def excuse(emp, day):
	fresh()
	return frappe.db.get_value("Work Missing Day Excuse", {"employee": emp, "work_date": day},
		["name", "status", "sent_back_reason", "payroll_check"], as_dict=True)


# ---- scenarios --------------------------------------------------------------------------

def s1_on_crew(ui, day_row, period):
	emp, day, asg = day_row["employee"], day_row["day"], day_row["crews"][0]["assignment"]
	make_room(asg, 2)
	pg = ui.grid(CLERK, *period)
	ui.open_cell(pg, emp, day)
	pg.fill("#mw-qty", "1")
	pg.click("#mw-send")
	ui.wait_reload(pg)
	rec = fix_record(emp, day)
	if not check("1. clerk enters work for an on-crew day -> own record at the farm manager",
			rec and rec.workflow_state == "Pending Farm Manager", rec):
		return
	st = day_state(emp, day)
	check("1. the day now shows as waiting", st and st["state"] == "waiting", st and st["state"])
	pgc = ui.waiting(CLERK)
	check("1. the clerk sees it waiting, with no Approve button for them",
		pgc.locator("text=" + rec.name).count() == 0 and not pgc.locator('[data-mw-ok="%s"]' % rec.name).count())
	err = ui.approve_work(FM, rec.name, quality="1")
	check("1. farm manager approves (quality Good) in Waiting", not err and fix_record(emp, day).workflow_state == "Pending HR Head", err)
	err = ui.approve_work(HR, rec.name)
	check("1. HR approves", not err and fix_record(emp, day).workflow_state == "Pending GM", err)
	err = ui.approve_work(GM, rec.name)
	check("1. GM approves -> CONFIRMED", not err and fix_record(emp, day).workflow_state == "CONFIRMED", err)
	st = day_state(emp, day)
	check("1. the day is cleared (not in To clear, not waiting)", st is None, st and st["state"])
	g = mw(CLERK, action="mw_grid", farm=FARM, from_date=day, to_date=day)
	cell = [w["cells"] for w in g["workers"] if w["emp"] == emp]
	check("1. grid shows work recorded (lower case) for that day", cell and cell[0].islower(), cell)


def s2_no_crew(ui, day_row, period):
	emp, day = day_row["employee"], day_row["day"]
	pg = ui.grid(FM, *period)
	ui.open_cell(pg, emp, day)
	if pg.locator("#mw-why").count():
		pg.fill("#mw-why", "e2e: forgot to put them on the crew")
	# try each crew that covers the day until one takes them (one may refuse, e.g. "already on it")
	options = pg.locator("#mw-asg option").evaluate_all("os => os.map(o => o.value)")
	asg, refusals = None, []
	for opt in options:
		pg.select_option("#mw-asg", opt)
		make_room(opt, 2)
		pg.click("#mw-add")
		pg.wait_for_selector("#mw-qty, #mw-pn-msg:not([hidden])", timeout=30000)
		if pg.locator("#mw-qty").count():
			asg = opt
			break
		refusals.append(opt + ": " + pg.locator("#mw-pn-msg").inner_text())
	if not check("2. farm manager can add the worker to one of the crews covering the day", asg, refusals):
		return
	check("2. farm manager adds a no-crew worker to a crew (late, inside the open check)",
		frappe.db.sql("SELECT 1 FROM `tabWork Assignment Employee` WHERE parent=%s AND employee=%s AND left_date=%s",
			(asg, emp, day)) or (fresh() or frappe.db.sql("SELECT 1 FROM `tabWork Assignment Employee` WHERE parent=%s AND employee=%s AND left_date=%s",
			(asg, emp, day))), asg)
	pg.fill("#mw-qty", "1")
	pg.click("#mw-send")
	ui.wait_reload(pg)
	rec = fix_record(emp, day)
	if not check("2. then enters the quantity in the same panel -> own record", rec and rec.workflow_state == "Pending Farm Manager", rec):
		return
	err = ui.approve_work(GM, rec.name, quality="1")
	check("2. GM takes the farm manager step (the enterer is the farm manager)", not err and fix_record(emp, day).workflow_state == "Pending HR Head", err)
	err = ui.approve_work(HR, rec.name)
	check("2. HR approves", not err and fix_record(emp, day).workflow_state == "Pending GM", err)
	err = ui.approve_work(GM, rec.name)
	check("2. GM approves -> CONFIRMED", not err and fix_record(emp, day).workflow_state == "CONFIRMED", err)
	issues = payment_api(HR, action="chk_issues", check="WMPC-00798", farm=FARM).get("issues") or []
	check("2. the check shows the late add to HR (added late)",
		any(i["code"] == "added_late" and i["employee"] == emp for i in issues))


def s3_reason(ui, day_row, period):
	emp, day = day_row["employee"], day_row["day"]
	pg = ui.grid(CLERK, *period)
	ui.open_cell(pg, emp, day)
	pg.click('[data-mw-reason="Other"]')
	check("3. the note box appears only for Other", pg.locator("#mw-note").is_visible())
	pg.click("#mw-no")
	check("3. Other without a note is refused", "Say what happened" in pg.locator("#mw-no-msg").inner_text())
	pg.click('[data-mw-reason="Rain / weather"]')
	pg.click("#mw-no")
	ui.wait_reload(pg)
	ex = excuse(emp, day)
	if not check("3. clerk gives a reason -> waiting for the farm manager", ex and ex.status == "Pending Farm Manager", ex):
		return
	err = ui.approve_reason(FM, ex.name)
	check("3. farm manager approves the reason", not err and excuse(emp, day).status == "Pending HR", err)
	err = ui.approve_reason(HR, ex.name)
	check("3. HR approves", not err and excuse(emp, day).status == "Pending GM", err)
	err = ui.approve_reason(GM, ex.name)
	check("3. GM approves -> Approved", not err and excuse(emp, day).status == "Approved", err)
	g = mw(CLERK, action="mw_grid", farm=FARM, from_date=day, to_date=day)
	cell = [w["cells"] for w in g["workers"] if w["emp"] == emp]
	check("3. grid shows the approved reason (R)", cell and cell[0] == "R", cell)


def s4_send_back(ui, work_row, reason_row, period):
	emp, day, asg = work_row["employee"], work_row["day"], work_row["crews"][0]["assignment"]
	make_room(asg, 2)
	pg = ui.grid(CLERK, *period)
	ui.open_cell(pg, emp, day)
	pg.fill("#mw-qty", "2")
	pg.click("#mw-send")
	ui.wait_reload(pg)
	rec = fix_record(emp, day)
	if not rec:
		check("4. work entered for send-back test", False, "no record")
		return
	ui.approve_work(FM, rec.name, quality="2")
	err = ui.send_back(HR, rec.name, "e2e: quantity is wrong, check with the team leader")
	st = day_state(emp, day)
	check("4. HR sends the work back -> record deleted, day open again with the reason",
		not err and fix_record(emp, day) is None and st and st["state"] == "open"
		and (st.get("sent_back") or {}).get("reason", "").startswith("e2e:"), err or st)
	pg = ui.grid(CLERK, *period)
	ui.open_cell(pg, emp, day)
	check("4. the panel shows who sent it back and why", "Sent back by" in pg.locator("#mw-pn").inner_text())
	pg.fill("#mw-qty", "1")
	pg.click("#mw-send")
	ui.wait_reload(pg)
	rec = fix_record(emp, day)
	ok = rec and not ui.approve_work(FM, rec.name, quality="1") and not ui.approve_work(HR, rec.name) and not ui.approve_work(GM, rec.name)
	check("4. entered again and approved through all three steps", ok and fix_record(emp, day).workflow_state == "CONFIRMED")
	# a reason sent back at the farm manager step
	e2, d2 = reason_row["employee"], reason_row["day"]
	mw(CLERK, action="mw_excuse", rows=json.dumps([{"employee": e2, "day": d2}]), reason="Sick / left early")
	err = ui.send_back(FM, excuse(e2, d2).name, "e2e: he was at work, enter it")
	st = day_state(e2, d2)
	check("4. farm manager sends a reason back -> day open again", not err and excuse(e2, d2).status == "Sent back"
		and st and st["state"] == "open", err or st)


def s5_refusals(day_rows):
	(r1, r2, r3) = day_rows
	mw(FM, action="mw_excuse", rows=json.dumps([{"employee": r1["employee"], "day": r1["day"]}]), reason="Rain / weather")
	ex = excuse(r1["employee"], r1["day"])
	o = mw(FM, action="mw_approve", names=json.dumps([ex.name]))
	check("5. nobody approves a reason they gave", "yourself" in (o.get("error") or ""), o)
	o = mw(HR, action="mw_approve", names=json.dumps([ex.name]))
	check("5. HR cannot take the farm manager step", "not you" in (o.get("error") or ""), o)
	mw(GM, action="mw_approve", names=json.dumps([ex.name]))
	o = mw(GM, action="mw_approve", names=json.dumps([ex.name]))   # koskey holds HOD HR too: takes HR step
	o2 = mw(GM, action="mw_approve", names=json.dumps([ex.name]))  # then may not take the GM step
	check("5. the same person cannot take both the HR and the GM step", "HR step" in (o2.get("error") or ""), (o, o2))
	o = mw(GM, action="mw_send_back", names=json.dumps([ex.name]))
	check("5. send back needs a reason", "Say why" in (o.get("error") or ""), o)
	o = actuals_api(CLERK, action="act_submit", assignment=r2["crews"][0]["assignment"], missing_fix=1, submit_now=1,
		rows=r2["employee"] + "~2026-09-01~1")
	check("5. a missing-day save for a day that is not missing is refused", "not a missing day" in (o.get("error") or ""), o)
	other = r3 if r3["crews"] and r3["crews"][0]["assignment"] != r2["crews"][0]["assignment"] else None
	if other:
		o = actuals_api(CLERK, action="act_submit", assignment=r2["crews"][0]["assignment"], missing_fix=1, submit_now=1,
			rows=other["employee"] + "~" + other["day"] + "~1")
		check("5. a save for a worker not on that crew is refused", "crew" in (o.get("error") or ""), o)
	o = actuals_api(CLERK, action="act_submit", assignment=r2["crews"][0]["assignment"], missing_fix=1, submit_now=1,
		rows=r2["employee"] + "~" + r2["day"] + "~1|" + (other or r1)["employee"] + "~" + r2["day"] + "~1")
	check("5. one worker per missing-day record", "One worker" in (o.get("error") or ""), o)


def s6_locked(ui, day_row, period):
	emp, day, asg = day_row["employee"], day_row["day"], day_row["crews"][0]["assignment"]
	make_room(asg, 2)
	pg = ui.grid(CLERK, period[0], period[1], farm=day_row["farm"])
	ui.open_cell(pg, emp, day)
	pg.fill("#mw-qty", "1")
	pg.click("#mw-send")
	ui.wait_reload(pg)
	rec = fix_record(emp, day)
	check("6. a crew whose main record is already approved (" + day_row["farm"] + ") still takes a missing day",
		rec and rec.workflow_state == "Pending Farm Manager", rec)
	d = actuals_api(CLERK, action="act_detail", assignment=asg).get("detail") or {}
	check("6. the crew's grid is still locked by its main record, not by the fix",
		d.get("live_name") and rec and d.get("live_name") != rec.name, d.get("live_name"))


def s7_payroll_check(ui):
	day = "2026-11-12"
	o = payment_api(HR, action="chk_create", from_date=day, to_date=day)
	pc = o.get("name") or o.get("check")
	CHECKS.append(pc)
	if not check("7. HR creates a one-day payroll check (12 Nov)", pc, o):
		return None
	o = payment_api(FM, action="chk_farm_approve", check=pc, farm=FARM)
	from work_management.missing_work import find
	fresh()
	as_user("Administrator")
	open_rows = find([FARM], day, day)
	check("7. Vale cannot approve while it has days to clear", open_rows and "Missing work" in (o.get("error") or ""),
		(len(open_rows), o.get("error")))
	if open_rows:
		pg = ui.grid(CLERK, day, day)
		pg.check("#mw-tickmode")
		for r in open_rows:
			pg.locator('[data-mw-cell="%s|%s"]' % (r["employee"], r["day"])).click()
		pg.click('[data-mw-bulkreason="Sent home – no work"]')
		pg.click("#mw-bulk-go")
		ui.wait_reload(pg)
		o = payment_api(FM, action="chk_farm_approve", check=pc, farm=FARM)
		check("7. reasons given but not approved still block Vale", "Missing work" in (o.get("error") or ""), o.get("error"))
		for user in (FM, HR, GM):
			pgw = ui.waiting(user)
			grp = pgw.locator('.mw-group[data-mw-kind="reason"]', has=pgw.locator("[data-mw-approveall]"))
			if grp.count():
				grp.first.locator("[data-mw-all]").check()
				grp.first.locator("[data-mw-approveall]").click()
				ui.wait_reload(pgw)
		fresh()
		left = frappe.db.sql("SELECT COUNT(*) FROM `tabWork Missing Day Excuse` WHERE work_date=%s AND farm=%s AND status!='Approved'", (day, FARM))[0][0]
		check("7. bulk 'Approve ticked' by farm manager, HR and GM approves them all", left == 0, left)
	o = payment_api(FM, action="chk_farm_approve", check=pc, farm=FARM)
	ok = check("7. with every fix approved, Vale's approval is no longer held by missing work",
		"Missing work" not in (o.get("error") or ""), o.get("error"))
	if ok and not o.get("error"):
		fresh()
		n = frappe.db.sql("SELECT COUNT(*) FROM `tabWork Missing Day Excuse` WHERE payroll_check=%s", (pc,))[0][0]
		check("7. Vale approved and its reasons are locked into the check", n == len(open_rows), (n, len(open_rows)))
		det = payment_api(HR, action="chk_detail", check=pc)
		check("7. HR sees the 'No work given' summary", sum(x["n"] for x in det.get("excused") or []) == len(open_rows), det.get("excused"))
		o = payment_api(HR, action="chk_send_back", check=pc, reason="e2e: send back")
		fresh()
		n = frappe.db.sql("SELECT COUNT(*) FROM `tabWork Missing Day Excuse` WHERE payroll_check=%s", (pc,))[0][0]
		check("7. sending the check back unlocks the reasons", n == 0, (o.get("error"), n))
	elif o.get("error"):
		print("      (Vale still has other things to fix that day: " + o["error"] + ")")
	return pc


def s8_ask_hr(ui, period):
	fresh()
	ab = frappe.db.sql("""SELECT a.employee, a.attendance_date FROM tabAttendance a INNER JOIN tabEmployee e ON e.name = a.employee
		WHERE a.status = 'Absent' AND a.docstatus = 1 AND e.status = 'Active' AND TRIM(e.custom_farm) = %s
		AND a.attendance_date BETWEEN %s AND %s AND NOT EXISTS (SELECT 1 FROM tabAttendance p WHERE p.employee = a.employee
			AND p.attendance_date = a.attendance_date AND p.docstatus = 1 AND p.status IN ('Present','Half Day','Work From Home'))
		AND NOT EXISTS (SELECT 1 FROM `tabAttendance Request` q WHERE q.employee = a.employee
			AND q.from_date <= a.attendance_date AND q.to_date >= a.attendance_date AND q.docstatus < 2) LIMIT 1""",
		(FARM, period[0], period[1]))
	if not ab:
		check("8. an Absent day to test with", False, "none found")
		return
	emp, day = ab[0][0], str(ab[0][1])
	# an Attendance Request needs a holiday list covering today; the copy may lack one
	today = frappe.utils.today()
	hl = frappe.db.get_value("Holiday List", {"from_date": ["<=", today], "to_date": [">=", today]}, "name")
	if not hl:
		doc = frappe.get_doc({"doctype": "Holiday List", "holiday_list_name": "E2E Missing Work",
			"from_date": today[:4] + "-01-01", "to_date": today[:4] + "-12-31"}).insert(ignore_permissions=True)
		frappe.db.commit()
		hl = doc.name
		CREATED.append(("Holiday List", hl))
	set_temp("Employee", emp, "holiday_list", hl)
	if frappe.db.exists("DocType", "Holiday List Assignment"):
		hla = frappe.get_doc({"doctype": "Holiday List Assignment", "applicable_for": "Employee", "assigned_to": emp,
			"holiday_list": hl, "from_date": today[:4] + "-01-01"})
		hla.insert(ignore_permissions=True)
		hla.submit()
		frappe.db.commit()
		CREATED.insert(0, ("Holiday List Assignment", hla.name))
	pg = ui.grid(FM, *period)
	ui.open_cell(pg, emp, day)
	pg.click("#mw-ask")
	ui.wait_reload(pg)
	fresh()
	ar = frappe.db.get_value("Attendance Request", {"employee": emp, "from_date": day}, ["name", "reason"], as_dict=True)
	check("8. clicking an Absent day and 'ask HR' raises an On Duty attendance request", ar and ar.reason == "On Duty", ar)
	g = mw(FM, action="mw_grid", farm=FARM, from_date=day, to_date=day)
	cell = [w["cells"] for w in g["workers"] if w["emp"] == emp]
	check("8. the grid shows HR has been asked (X)", cell and cell[0] == "X", cell)
	o = mw(FM, action="mw_ask_hr", employee=emp, day=day)
	check("8. asking twice is refused", "already asked" in (o.get("error") or ""), o)


# ---- setup / teardown ---------------------------------------------------------------------

def teardown(start, checks):
	fresh()
	as_user("Administrator")
	fixes = [r[0] for r in frappe.db.sql("SELECT name FROM `tabWork Management Actuals` WHERE missing_work_fix = 1 AND creation >= %s", (start,))]
	for n in fixes:
		frappe.db.sql("DELETE FROM `tabWork Actuals Employee` WHERE parent = %s", (n,))
		frappe.db.sql("DELETE FROM `tabWork Management Actuals` WHERE name = %s", (n,))
		frappe.db.sql("DELETE FROM tabComment WHERE reference_name = %s", (n,))
	frappe.db.sql("DELETE FROM `tabWork Missing Day Excuse` WHERE creation >= %s", (start,))
	frappe.db.sql("DELETE FROM `tabWork Management Deleted Actuals` WHERE creation >= %s", (start,))
	frappe.db.sql("DELETE FROM `tabWork Assignment Employee` WHERE IFNULL(added_for_check, '') != '' AND creation >= %s", (start,))
	frappe.db.sql("DELETE FROM `tabWork Assignment Employee` WHERE creation >= %s", (start,))
	frappe.db.sql("DELETE FROM tabComment WHERE reference_doctype = 'Work Management Assigner' AND creation >= %s", (start,))
	frappe.db.sql("DELETE FROM `tabAttendance Request` WHERE creation >= %s", (start,))
	frappe.db.sql("DELETE FROM `tabWork Management Payroll Check Fix` WHERE creation >= %s", (start,))
	for pc in checks:
		if pc:
			frappe.db.sql("UPDATE `tabWork Actuals Employee` SET payroll_check = '' WHERE payroll_check = %s", (pc,))
			frappe.db.sql("DELETE FROM `tabWork Management Payroll Check Farm` WHERE parent = %s", (pc,))
			frappe.db.sql("DELETE FROM `tabWork Management Payroll Check` WHERE name = %s", (pc,))
			frappe.db.sql("DELETE FROM tabComment WHERE reference_name = %s", (pc,))
	for doctype, name, field, old in reversed(RESTORE):
		frappe.db.set_value(doctype, name, field, old, update_modified=False)
	for doctype, name in CREATED:
		if frappe.db.get_value(doctype, name, "docstatus") == 1:
			frappe.db.set_value(doctype, name, "docstatus", 2, update_modified=False)
		frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
	frappe.db.sql("DELETE FROM `tabEmail Queue` WHERE creation >= %s", (start,))
	frappe.db.commit()
	print("teardown: removed %d missing-day records and everything else created since %s; restored %d values"
		% (len(fixes), start, len(RESTORE)))


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument("--site", default="webstore.localhost")
	ap.add_argument("--url", default="http://127.0.0.1:8003")
	args = ap.parse_args()
	frappe.init(site=args.site, sites_path=".")
	frappe.connect()
	if "upande.com" in (frappe.local.conf.get("host_name") or "") or args.site.endswith(".upande.com"):
		sys.exit("Refusing to run on a live site.")
	frappe.flags.mute_emails = True
	time.sleep(1)
	start = frappe.utils.now()
	checks = []
	from work_management.missing_work import find
	period = ("2026-10-21", "2026-11-11")
	as_user("Administrator")
	rows = find([FARM], *period)
	on_crew = [r for r in rows if r["crews"]]
	free = [r for r in on_crew if not has_main_record(r["crews"][0]["assignment"])]
	# a crew whose main record is already in approval or confirmed, on any farm the clerk works
	locked = [r for r in find(["Vale", "Endebess"], *period)
		if r["crews"] and has_main_record(r["crews"][0]["assignment"])]
	oldest = frappe.utils.add_days(frappe.utils.today(), -7)
	from work_management.missing_work import assignment_options
	opts = assignment_options(FARM, *period)
	no_crew = [r for r in rows if not r["crews"] and r["day"] < oldest
		and any(a["from_date"] <= r["day"] <= a["to_date"] for a in opts)]
	used = set()

	def take(pool, n=1):
		got = []
		for r in pool:
			k = (r["employee"], r["day"])
			if k in used or any(x["employee"] == r["employee"] for x in got):
				continue
			used.add(k)
			got.append(r)
			if len(got) == n:
				break
		return got

	print("test days: %d open on %s (%d on a crew, %d crews with an approved main record, %d no-crew with a crew to join)"
		% (len(rows), FARM, len(on_crew), len(locked), len(no_crew)))
	with sync_playwright() as p:
		browser = p.chromium.launch()
		ui = UI(browser, args.url)
		try:
			for name, fn in (
				("1. on-crew day, full approval", lambda: s1_on_crew(ui, take(free)[0], period)),
				("2. no-crew day, add then approve", lambda: s2_no_crew(ui, take(no_crew)[0], period) if no_crew else check("2. a no-crew day with a crew to join", False, "none")),
				("3. reason, full approval", lambda: s3_reason(ui, take(rows)[0], period)),
				("4. send back", lambda: s4_send_back(ui, take(free)[0], take(rows)[0], period)),
				("5. refusals", lambda: s5_refusals(take(rows, 1) + take(on_crew, 2))),
				("6. locked crew", lambda: s6_locked(ui, take(locked)[0], period) if locked else check("6. a locked crew", False, "none")),
				("7. payroll check", lambda: s7_payroll_check(ui)),
				("8. ask HR", lambda: s8_ask_hr(ui, period)),
			):
				print("\n== " + name)
				try:
					fn()
				except Exception as exc:
					traceback.print_exc()
					check(name + " ran without crashing", False, exc)
			check("no JavaScript errors in any page", not ui.errors, ui.errors[:3])
		finally:
			browser.close()
			teardown(start, CHECKS)
	passed = len([r for r in RESULTS if r[1]])
	print("\n%d of %d checks passed" % (passed, len(RESULTS)))
	for name, ok, detail in RESULTS:
		if not ok:
			print("FAILED: " + name + "  -- " + str(detail))
	frappe.destroy()
	sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
	main()
