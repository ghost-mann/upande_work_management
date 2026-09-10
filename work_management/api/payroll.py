# Ported from the upstream mirror's Server Script "wm_payroll" (API) — logic unchanged.
# Farms / projects / company / approver roles now come from Work Management Settings
# and the Work Management Farm doctype — see work_management/api/config.py.
# ON THE `altura` BRANCH THIS FILE IS SOURCE, not a port. Altura deploys the
# packaged app rather than Kaitet's Server Scripts, so no port_app.py run
# follows this file and nothing reverts an edit made here. Edit it directly,
# and do not run the mirror's porter against this checkout — see
# docs/ALTURA_FORK.md. On master the opposite still holds.

import json

import frappe

from work_management import pay_week
from work_management.api.config import ACCOUNTS_RELEASE, PAYROLL_FEED, get_config
from work_management.api.payment import (payroll_feed_run, payroll_preconditions,
                                          weekly_earnings, weekly_spoken_for)


#: Attendance statuses that count as having turned up. "Half Day" deliberately
#: does not: the bonus pays a full rest day for a full week, and half a day is
#: the case a human should look at rather than one this should decide silently.
#: It is reported as the forfeit reason by name, so the decision is visible.
PRESENT_STATUSES = ("Present", "Work From Home")


def holiday_list_for(employee, on_date):
    """Which Holiday List applies to this worker on this date.

    Each worker's rest day is their OWN -- employees sit on different weekly offs
    (with Sundays, with Thursdays, with Fridays), so there is no company-wide
    working day and no company-wide off day either. api/payroll.py has said so
    since its first line and every off-day read in this app follows it.

    On Altura the assignment is date-effective: upande_ta's `Bulk Week Off`
    assigns lists through hrms `Holiday List Assignment`, so a worker's list in
    March need not be their list in September. Ask hrms first, because
    `Employee.holiday_list` on such a site is whatever was assigned last rather
    than what applied in the week being paid. Fall back to the Employee field for
    a site with no hrms assignment machinery, which is every other site.
    """
    try:
        from hrms.utils.holiday_list import get_assigned_holiday_list

        assigned = get_assigned_holiday_list(employee, on_date)
        if assigned:
            return assigned
    except Exception:
        # hrms absent, or the helper's shape changed under us. Neither is a
        # reason to fail a payroll preview -- the Employee field is the answer
        # every other site has always used.
        pass
    return frappe.db.get_value("Employee", employee, "holiday_list")


def off_days_in(holiday_list, week_from, week_to):
    """{"weekly_off": [dates], "public": [dates]} for one list over one week.

    **`Holiday.weekly_off` is the field that separates the two features.** A row
    with it ticked is the worker's rest day, and working every OTHER day of the
    week earns the bonus for it. A row without it is a public holiday, which is a
    working day for this rule -- missing it forfeits the bonus -- and is what the
    holiday pay multiplier doubles. Reading one as the other pays a bonus on
    every public holiday, or double on every rest day.
    """
    out = {"weekly_off": [], "public": []}
    if not holiday_list:
        return out
    for row in frappe.db.sql("""
        SELECT holiday_date d, IFNULL(weekly_off, 0) wo
        FROM `tabHoliday`
        WHERE parent = %(p)s AND holiday_date BETWEEN %(a)s AND %(b)s
        ORDER BY holiday_date
    """, {"p": holiday_list, "a": week_from, "b": week_to}, as_dict=True):
        out["weekly_off" if frappe.utils.cint(row.wo) else "public"].append(str(row.d))
    return out


def wants_post():
    """True unless this arrived over HTTP as something other than POST.

    A write reached by GET is a write anything can trigger with a link, a
    prefetch or a browser tab restore, and it will not carry a CSRF token
    either. Frappe's own `methods=["POST"]` is per WHITELISTED FUNCTION, and
    this module answers several actions through one of those -- some of which
    must stay readable -- so the check lives on the action instead.

    No request at all is a console or a background job, and those may write:
    that is how every hygiene action in this app is run.
    """
    request = getattr(frappe.local, "request", None)
    return request is None or request.method == "POST"


def feed_preview(week_from=None, week_to=None, farm=None, employee=None):
    """What feeding a pay week WOULD do. Reads; never writes.

    This is the panel's loader, so it has to answer honestly when the answer is
    "you cannot do this yet": `can_feed` is 0 with `cannot_feed` naming the reason
    in words a person can act on. A panel that fails to load because the feature
    is unconfigured tells its reader nothing except that something is broken.

    Every figure the panel shows comes from here, and the write below consumes
    the same dict, so what somebody approves is exactly what gets written.
    """
    out = {}
    shape = pay_week.shape(
        frappe.db.get_single_value("Work Management Settings", "pay_week_starts_on"),
        frappe.db.get_single_value("Work Management Settings", "pay_week_ends_on"),
        frappe.db.get_single_value("Work Management Settings", "pay_day"))
    bonus_on = frappe.utils.cint(frappe.db.get_single_value(
        "Work Management Settings", "pay_weekly_off_on_full_attendance"))
    bonus_amt = frappe.utils.flt(frappe.db.get_single_value(
        "Work Management Settings", "weekly_off_bonus_amount"))
    today = frappe.utils.today()

    # The week: the one the caller asked for, snapped to its real boundaries so a
    # date in the middle names the whole week, or the last one that closed. Never
    # the week in progress by default -- feeding it would write a figure that is
    # still growing, and payroll would read whichever value it happened to catch.
    span = None
    if week_from:
        span = pay_week.week_of(week_from, shape)
        if not span:
            out["error"] = (str(week_from) + " falls on a weekday that belongs to no pay "
                "week -- this project's week runs " + str(shape["days"]) +
                " days, from " + pay_week.WEEKDAYS[shape["start_wd"]] +
                " to " + pay_week.WEEKDAYS[shape["end_wd"]] + ".")
            return out
    else:
        span = pay_week.last_complete_week(today, shape)
    if not span:
        out["error"] = "No pay week has closed yet."
        return out
    week_a = str(span[0])
    week_b = str(span[1])
    if week_to and str(week_to)[:10] != week_b:
        # the caller named a range that is not one pay week. Say so rather than
        # quietly paying the week their start date happens to land in.
        out["error"] = (str(week_from) + " to " + str(week_to) + " is not one pay week. "
            "The week containing " + str(week_from) + " runs " + week_a + " to " + week_b + ".")
        return out

    pay_on = str(pay_week.pay_date(week_b, shape))
    stamp = week_a + " \u2192 " + week_b
    days = [str(d) for d in pay_week.days_in(week_a, week_b)]
    complete = 1 if pay_week.is_complete(week_b, today) else 0
    out["week_from"] = week_a
    out["week_to"] = week_b
    out["pay_date"] = pay_on
    out["week_stamp"] = stamp
    out["bonus_enabled"] = bonus_on
    out["bonus_amount"] = bonus_amt
    out["field"] = "custom_basic_pay"
    out["complete"] = complete

    # CONFIGURATION THE BUTTON NEEDS. The bonus half is optional; the field is
    # not, and writing to a fieldname that does not exist on this site would fail
    # one Employee at a time with nothing said up front.
    missing = []
    if not frappe.get_meta("Employee").get_field("custom_basic_pay"):
        missing.append("Employee.custom_basic_pay does not exist on this site")
    if bonus_on and bonus_amt <= 0:
        missing.append("the off-day bonus is switched on and its amount is 0")
    out["config_missing"] = missing

    rows = []
    skipped = []
    for earned in weekly_earnings(week_a, week_b, employee=employee, farm=farm):
        emp = frappe.db.get_value("Employee", earned.employee,
            ["status", "date_of_joining", "relieving_date", "employee_name",
             "custom_basic_pay", "custom_basic_pay_week"], as_dict=True) or {}
        name = earned.employee_name or emp.get("employee_name") or earned.employee

        # WHICH DAY IS THEIRS OFF. Never Sunday by assumption -- workers sit on
        # different weekly offs and assuming would pay a bonus for a day somebody
        # actually worked, or refuse one they earned.
        holiday_list = holiday_list_for(earned.employee, week_b)
        off = off_days_in(holiday_list, week_a, week_b)
        assumed = 0
        rest = off["weekly_off"]
        if not holiday_list or not rest:
            # No off-day data at all. Sunday is the default this project has always
            # run on, and it is FLAGGED rather than applied silently: a bonus paid
            # on a guessed rest day is a bonus nobody can check.
            assumed = 1
            rest = [d for d in days if frappe.utils.getdate(d).weekday() == 6]

        # Every day of the week that is NOT their rest day, PUBLIC HOLIDAYS
        # INCLUDED. A public holiday is a working day for a casual: missing it
        # forfeits the bonus, attending it earns doubled actuals and keeps the
        # streak. Holiday.weekly_off is what separates the two, and reading it the
        # other way round would pay a bonus for every public holiday in the year.
        working = [d for d in days if d not in rest]
        present = []
        if working:
            for att in frappe.db.sql("""
                SELECT attendance_date d, status s FROM `tabAttendance`
                WHERE employee = %(e)s AND docstatus < 2
                  AND attendance_date IN %(days)s
            """, {"e": earned.employee, "days": tuple(working)}, as_dict=True):
                if att.s in PRESENT_STATUSES:
                    present.append(str(att.d))
        absent = [d for d in working if d not in present]

        bonus = 0
        why = None
        if not bonus_on:
            why = "off-day bonus is switched off in Settings"
        elif not working:
            why = "no working days in this week to attend"
        elif absent:
            # name the days, and say when one of them was a public holiday:
            # "missed holiday" is the reason HR asked to see, because a worker who
            # thought a holiday was a day off will come and ask.
            missed_holiday = [d for d in absent if d in off["public"]]
            why = ("no attendance on " + ", ".join(absent[:4])
                + ("..." if len(absent) > 4 else ""))
            if missed_holiday:
                why = why + " (missed holiday: " + ", ".join(missed_holiday) + ")"
        else:
            bonus = bonus_amt

        total = frappe.utils.flt(earned.owed) + bonus
        row = {
            "employee": earned.employee, "employee_name": name,
            "actuals": frappe.utils.flt(earned.owed, 2),
            "days_worked": frappe.utils.cint(earned.days),
            "qty": frappe.utils.flt(earned.qty),
            "holiday_list": holiday_list,
            "off_day": ", ".join(rest) or None,
            "off_day_assumed": assumed,
            "public_holidays": ", ".join(off["public"]) or None,
            "working_days": len(working),
            "attended": len(present),
            "bonus": bonus,
            "bonus_reason": why,
            "total": frappe.utils.flt(total, 2),
            "was": frappe.utils.flt(emp.get("custom_basic_pay"), 2),
            "was_week": emp.get("custom_basic_pay_week"),
        }

        # PRECONDITIONS, checked before anything is written. The same gates the
        # payment run applies, for the same reason: a worker payroll cannot pay is
        # a worker this must not quietly hand a figure to. Shared with the worker
        # review sheet, so the two screens give one answer rather than two.
        block = payroll_preconditions(earned.employee, pay_on, emp=emp)
        if total <= 0:
            # A worker with a week of nothing is SKIPPED, not written as 0. Writing
            # 0 would say "this person earned nothing this week", which is a claim;
            # not writing says "this feed has nothing to say about them", which is
            # the truth. Reported all the same, because a task worker with no
            # confirmed work for a whole week is a question for HR either way.
            block = "no confirmed unpaid work in this week"
            row["hr_question"] = 1
        if block:
            row["skipped"] = block
            skipped.append(row)
            continue
        if str(emp.get("custom_basic_pay_week") or "") == stamp:
            # RE-FEEDING IS A NO-OP. The week is stamped the way the payment flow
            # stamps payment_ref, so a second run of the same week says so instead
            # of silently rewriting the same figure -- or a different one, if
            # actuals moved underneath it.
            row["skipped"] = "already fed for " + stamp
            row["already_fed"] = 1
            skipped.append(row)
            continue
        rows.append(row)

    # ALREADY SPOKEN FOR. A worker sent to accounts has no eligible rows left, so
    # they drop out of the loop above without a word -- and "where did Brian go"
    # is then a question the panel cannot answer. Listed with the run that claimed
    # them, which is also the shape of the exclusion in the other direction: a fed
    # row cannot be sent, a sent row cannot be fed, and both are visible.
    for taken in weekly_spoken_for(week_a, week_b, employee=employee, farm=farm):
        skipped.append({
            "employee": taken.employee,
            "employee_name": taken.employee_name or taken.employee,
            "actuals": frappe.utils.flt(taken.owed, 2),
            "days_worked": frappe.utils.cint(taken.days),
            "off_day": None, "off_day_assumed": 0, "public_holidays": None,
            "working_days": 0, "attended": 0, "bonus": 0, "bonus_reason": None,
            "total": frappe.utils.flt(taken.owed, 2),
            "was": 0, "was_week": None,
            "skipped": (("paid by payroll feed " if frappe.utils.cint(taken.paid)
                         else "already sent to accounts as ")
                        + str(taken.runs or "another run")),
            "spoken_for": 1,
        })

    out["preview"] = 1
    out["rows"] = rows
    out["skipped"] = skipped
    out["would_write"] = len(rows)
    out["total"] = frappe.utils.flt(sum(r["total"] for r in rows), 2)
    out["hr_questions"] = [r for r in skipped if r.get("hr_question")]
    out["assumed_off_day"] = [r for r in (rows + skipped) if r.get("off_day_assumed")]
    out["already_fed"] = [r for r in skipped if r.get("already_fed")]

    # WHETHER THE BUTTON MAY BE PRESSED, and if not, why -- in a sentence, not a
    # flag. Ordered so the reader is told the thing they have to fix FIRST: the
    # configuration, then the week, then whether there is anything left to do.
    mode = get_config().get("payment_mode")
    out["payment_mode"] = mode
    reason = None
    if mode != PAYROLL_FEED:
        # ONE PAYMENT PATH AT A TIME, EVER. On a site that releases through
        # accounts, feeding a week would pay work that is also queued for
        # accounts to release -- so the panel is visible, explains itself, and
        # does nothing.
        reason = ("this project's payment mode is \u201c" + str(mode or ACCOUNTS_RELEASE)
            + "\u201d, so workers are paid by sending runs to accounts rather than "
            "by feeding payroll")
    elif missing:
        reason = "not configured: " + "; ".join(missing)
    elif not complete:
        reason = ("the pay week " + stamp + " has not closed yet -- it can be fed "
            "once it does")
    elif not rows and out["already_fed"]:
        reason = ("every worker with work in " + stamp + " has already been fed "
            "(" + str(len(out["already_fed"])) + ")")
    elif not rows and skipped:
        reason = (str(len(skipped)) + " worker" + ("" if len(skipped) == 1 else "s")
            + " have work in " + stamp + " and none can be fed -- see the reasons below")
    elif not rows:
        reason = "no confirmed unpaid work in " + stamp
    out["can_feed"] = 0 if reason else 1
    out["cannot_feed"] = reason
    return out


def feed_write(plan):
    """Write what `plan` -- a feed_preview() result -- said it would.

    Takes the preview rather than recomputing: what somebody approved on screen
    is then exactly what lands, and a week that changed underneath them cannot be
    written on the strength of a figure they never saw.

    IN PAYROLL-FEED MODE THE FEED IS THE PAYMENT, so each worker gets three
    things or none of them: a payment run created already paid, their day-rows
    stamped paid against it, and custom_basic_pay carrying the week's total. A
    savepoint per worker is what makes that "or none" true -- half of it is worse
    than nothing, because a stamped row with no figure is unpaid work nobody can
    find, and a figure with no run is money with no evidence.

    One worker failing does not stop the rest: the others are independent, and
    the report names who was left out.
    """
    written = 0
    runs = []
    failed = []
    company = frappe.db.get_single_value("Work Management Settings", "default_company")
    feeding = get_config().get("payment_mode") == PAYROLL_FEED
    for row in plan.get("rows") or []:
        point = "wmfeed_" + frappe.generate_hash(length=8)
        frappe.db.savepoint(point)
        try:
            run = None
            if feeding:
                run = payroll_feed_run(row["employee"], row["employee_name"],
                    plan["week_from"], plan["week_to"], plan["pay_date"], company)
                if not run:
                    raise ValueError("no payable actuals left for this worker")
            written = written + _write_basic_pay(plan, row, run)
            if run:
                runs.append({"employee": row["employee"],
                             "employee_name": row["employee_name"],
                             "payment": run, "amount": row["total"]})
        except Exception as failure:
            frappe.db.rollback(save_point=point)
            failed.append({"employee": row["employee"],
                           "employee_name": row["employee_name"],
                           "reason": str(failure)})
    frappe.db.commit()
    plan["runs"] = runs
    plan["failed"] = failed
    return written


def _write_basic_pay(plan, row, run=None):
    """The Employee half of a feed. Returns 1 so the caller can count."""
    # A PROPER DOC UPDATE, not frappe.db.set_value(..., update_modified=False).
    # This is somebody's pay: the change belongs in the Employee's version
    # history with who made it and when, which is exactly what a raw column
    # write throws away.
    doc = frappe.get_doc("Employee", row["employee"])
    doc.custom_basic_pay = row["total"]
    doc.custom_basic_pay_week = plan["week_stamp"]
    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)
    doc.add_comment("Comment",
        "Basic pay fed from Work Management for " + plan["week_stamp"] + ": KES "
        + str(row["total"]) + " (" + str(row["actuals"]) + " actuals"
        + (" + " + str(row["bonus"]) + " off-day bonus" if row["bonus"] else "")
        + ") by " + frappe.session.user
        + (" \u2014 payment run " + str(run) if run else ""))
    return 1


@frappe.whitelist()
def wm_payroll(**kwargs):
    _cfg = get_config()
    FARM_PROJECT = _cfg["farm_project"]
    DEFAULT_COMPANY = _cfg["default_company"]
    FARMS = _cfg["farms"]
    BLOCK_EXCLUDE = _cfg["block_exclude"]
    FARM_APPROVER_ROLE = _cfg["farm_approver_role"]
    HR_HEAD_ROLES = _cfg["hr_head_roles"]
    STAGE_ROWS = _cfg["stage_rows"]
    STAGE_STATES = _cfg["stage_states"]
    CAPABILITIES = _cfg["capabilities"]
    ALLOW_CONCURRENT_PLANS = _cfg["allow_concurrent_master_plans"]
    ALLOW_SPLIT_DAY = _cfg["allow_split_day"]
    STANDARD_DAY = _cfg["standard_day"]

    # ==================================================================
    # Master plan attribution: none. period_to here is the PAYMENT's pay week, which
    # is what a payroll date is derived from. No master plan is read at all.
    # SERVER SCRIPT — "WM Payroll" (API, api_method=wm_payroll)
    #
    # Work Management Payment -> ERPNext payroll.
    #
    # A payment document is per worker, so "last working day" is resolved against
    # that worker's own Holiday List — employees may sit on different weekly
    # offs (w/ Sundays, w/ Thursdays, w/ Fridays ...), so there is no single
    # company-wide working day.
    #
    # Actions:
    #   meta                 - configuration and coverage
    #   backfill_fields      - populate payroll_date / amount on existing documents
    #   as_preview           - what Additional Salary would be created for a document
    #   preview              - what feeding a pay week would do (read-only)
    #   feed_week_to_payroll - one pay week's total onto Employee.custom_basic_pay
    # ==================================================================
    action = frappe.form_dict.get("action") or "meta"
    out = {}

    # how far back to walk looking for a working day before giving up
    MAX_LOOKBACK = 21

    if action == "meta":
        out["component"] = frappe.db.get_single_value(
            "Work Management Settings", "salary_component")
        out["payments"] = frappe.db.count("Work Management Payment")
        out["with_payroll_date"] = frappe.db.count(
            "Work Management Payment", {"payroll_date": ["is", "set"]})
        out["with_amount"] = frappe.db.count(
            "Work Management Payment", {"amount": [">", 0]})
        out["states"] = frappe.db.sql("""
            SELECT workflow_state st, COUNT(*) n FROM `tabWork Management Payment`
            GROUP BY workflow_state ORDER BY n DESC
        """, as_dict=True)
        out["additional_salaries"] = frappe.db.count(
            "Additional Salary", {"ref_doctype": "Work Management Payment"})

    elif action == "backfill_fields":
        # payroll_date = the day the pay week closes, which IS the pay day. Periods
        # are pay weeks, so that is simply period_to. Kept as an action so a bulk
        # import or a change of pay day can be re-applied.
        bf_dry = frappe.utils.cint(frappe.form_dict.get("dry_run") or 1)
        bf_force = frappe.utils.cint(frappe.form_dict.get("force"))
        bf_limit = frappe.utils.cint(frappe.form_dict.get("limit") or 5000)
        bf_cond = "" if bf_force else " AND IFNULL(p.payroll_date,'') = ''"
        rows = frappe.db.sql("""
            SELECT p.name, p.period_from, p.period_to, p.payroll_date
            FROM `tabWork Management Payment` p
            WHERE IFNULL(p.period_to,'') != ''""" + bf_cond + """
            ORDER BY p.creation
            LIMIT %(lim)s
        """, {"lim": bf_limit}, as_dict=True)
        done = []
        for r in rows:
            want = str(r.period_to)[:10]
            if str(r.payroll_date or "")[:10] == want:
                continue
            done.append({"name": r.name, "was": str(r.payroll_date or ""), "now": want})
            if not bf_dry:
                frappe.db.set_value("Work Management Payment", r.name,
                                    "payroll_date", want, update_modified=False)
        if not bf_dry:
            frappe.db.commit()
        out["dry_run"] = bf_dry
        out["considered"] = len(rows)
        out["changed"] = len(done)
        out["sample"] = done[:12]

    elif action == "migrate_state":
        # Workflow State masters cannot be renamed in Frappe, so the move from
        # "Pending Accounts" to "Unpaid" is a create-new + repoint.
        ms_dry = frappe.utils.cint(frappe.form_dict.get("dry_run") or 1)
        ms_from = frappe.form_dict.get("old") or "Pending Accounts"
        ms_to = frappe.form_dict.get("new") or "Unpaid"
        ms_rows = frappe.db.sql("""
            SELECT name FROM `tabWork Management Payment` WHERE workflow_state = %(s)s
        """, {"s": ms_from}, as_dict=True)
        if not ms_dry:
            for m in ms_rows:
                frappe.db.set_value("Work Management Payment", m.name,
                                    "workflow_state", ms_to, update_modified=False)
            frappe.db.commit()
        out["dry_run"] = ms_dry
        out["from_state"] = ms_from
        out["to_state"] = ms_to
        out["documents"] = len(ms_rows)

    elif action == "as_preview":
        ap_name = frappe.form_dict.get("name")
        if not ap_name:
            out["error"] = "name is required"
        else:
            p = frappe.db.get_value("Work Management Payment", ap_name,
                ["name", "employee", "employee_name", "company", "amount",
                 "payroll_date", "period_from", "period_to",
                 "workflow_state"], as_dict=True)
            if not p:
                out["error"] = "no such payment: " + str(ap_name)
            else:
                out["payment"] = p
                out["component"] = frappe.db.get_single_value(
                    "Work Management Settings", "salary_component")
                out["existing"] = frappe.db.get_all("Additional Salary",
                    filters={"ref_doctype": "Work Management Payment", "ref_docname": ap_name},
                    fields=["name", "docstatus", "amount", "payroll_date", "salary_component"])

    elif action == "preview":
        # THE PANEL'S LOADER. Read-only by construction -- it calls feed_preview()
        # and returns it -- so opening the payroll tab can never write, and a site
        # that has not configured the feature gets a panel explaining that rather
        # than an error.
        out = feed_preview(
            week_from=frappe.form_dict.get("week_from"),
            week_to=frappe.form_dict.get("week_to"),
            farm=frappe.form_dict.get("farm") or None,
            employee=frappe.form_dict.get("employee") or None)

    elif action == "feed_week_to_payroll":
        # THE WRITE. One pay week's total onto Employee.custom_basic_pay, which a
        # colleague's Salary Structure fetches for its Basic component -- so this
        # lands on a live payroll record and is never something a page load does.
        if not wants_post():
            out["error"] = ("Feeding a week to payroll writes to Employee records, "
                            "so it has to be sent as a POST with a CSRF token. Load "
                            "the panel with action=preview and press the button.")
        else:
            out = feed_preview(
                week_from=frappe.form_dict.get("week_from"),
                week_to=frappe.form_dict.get("week_to"),
                farm=frappe.form_dict.get("farm") or None,
                employee=frappe.form_dict.get("employee") or None)
            if out.get("error"):
                pass
            elif not out.get("can_feed"):
                out["error"] = "Cannot feed this week: " + str(out.get("cannot_feed"))
            else:
                out["written"] = feed_write(out)
                out["preview"] = 0

    else:
        out["error"] = "unknown action: " + str(action)

    return out
