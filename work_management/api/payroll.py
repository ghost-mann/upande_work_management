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
from work_management.api.config import get_config
from work_management.api.payment import weekly_earnings


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

    elif action == "feed_week_to_payroll":
        # ONE PAY WEEK'S TOTAL, ONTO Employee.custom_basic_pay.
        #
        # A colleague owns the Salary Structure whose Basic component fetches that
        # field, so this writes the number and stops. What the number IS: the
        # confirmed, unpaid, payroll-counted actuals the payment run would send for
        # this week -- weekly_earnings() in api/payment.py, so the two cannot
        # disagree -- plus the weekly off-day bonus where the worker earned it.
        #
        # PREVIEW FIRST, always. The write lands on a live Employee record that
        # payroll reads, so nothing is written until somebody has seen the table:
        # who, what their actuals came to, which day is their off day, whether the
        # bonus was earned and why not where it was not, and the total.
        fw_write = frappe.utils.cint(frappe.form_dict.get("write"))
        fw_from = frappe.form_dict.get("week_from")
        fw_to = frappe.form_dict.get("week_to")
        fw_farm = frappe.form_dict.get("farm") or None
        fw_only = frappe.form_dict.get("employee") or None

        fw_shape = pay_week.shape(
            frappe.db.get_single_value("Work Management Settings", "pay_week_starts_on"),
            frappe.db.get_single_value("Work Management Settings", "pay_week_ends_on"),
            frappe.db.get_single_value("Work Management Settings", "pay_day"))
        fw_bonus_on = frappe.utils.cint(frappe.db.get_single_value(
            "Work Management Settings", "pay_weekly_off_on_full_attendance"))
        fw_bonus_amt = frappe.utils.flt(frappe.db.get_single_value(
            "Work Management Settings", "weekly_off_bonus_amount"))
        fw_today = frappe.utils.today()

        # The week: the one the caller asked for, snapped to its real boundaries so
        # a date in the middle names the whole week, or the last one that closed.
        # Never the week in progress by default -- feeding it would write a figure
        # that is still growing, and payroll would read whichever value it happened
        # to catch.
        fw_span = None
        if fw_from:
            fw_span = pay_week.week_of(fw_from, fw_shape)
            if not fw_span:
                out["error"] = (str(fw_from) + " falls on a weekday that belongs to no pay "
                                "week -- this project's week runs " + str(fw_shape["days"]) +
                                " days, from " + pay_week.WEEKDAYS[fw_shape["start_wd"]] +
                                " to " + pay_week.WEEKDAYS[fw_shape["end_wd"]] + ".")
        else:
            fw_span = pay_week.last_complete_week(fw_today, fw_shape)
        if not out.get("error") and not fw_span:
            out["error"] = "No pay week has closed yet."
        if not out.get("error"):
            fw_a = str(fw_span[0])
            fw_b = str(fw_span[1])
            if fw_to and str(fw_to)[:10] != fw_b:
                # the caller named a range that is not one pay week. Say so rather
                # than quietly paying the week their start date happens to land in.
                out["error"] = (str(fw_from) + " to " + str(fw_to) + " is not one pay week. "
                                "The week containing " + str(fw_from) + " runs " + fw_a +
                                " to " + fw_b + ".")
        if not out.get("error"):
            fw_pay_on = str(pay_week.pay_date(fw_b, fw_shape))
            fw_stamp = fw_a + " → " + fw_b
            fw_days = [str(d) for d in pay_week.days_in(fw_a, fw_b)]
            out["week_from"] = fw_a
            out["week_to"] = fw_b
            out["pay_date"] = fw_pay_on
            out["week_stamp"] = fw_stamp
            out["bonus_enabled"] = fw_bonus_on
            out["bonus_amount"] = fw_bonus_amt
            out["field"] = "custom_basic_pay"
            out["complete"] = 1 if pay_week.is_complete(fw_b, fw_today) else 0

            # CONFIGURATION THE BUTTON NEEDS. The bonus half is optional; the field
            # is not, and writing to a fieldname that does not exist on this site
            # would fail one Employee at a time with nothing said up front.
            fw_missing = []
            if not frappe.get_meta("Employee").get_field("custom_basic_pay"):
                fw_missing.append("Employee.custom_basic_pay does not exist on this site")
            if fw_bonus_on and fw_bonus_amt <= 0:
                fw_missing.append("the off-day bonus is switched on and its amount is 0")
            out["config_missing"] = fw_missing

            fw_rows = []
            fw_skipped = []
            fw_written = 0
            for fw_e in weekly_earnings(fw_a, fw_b, employee=fw_only, farm=fw_farm):
                fw_emp = frappe.db.get_value("Employee", fw_e.employee,
                    ["status", "date_of_joining", "relieving_date", "employee_name",
                     "custom_basic_pay", "custom_basic_pay_week"], as_dict=True) or {}
                fw_name = fw_e.employee_name or fw_emp.get("employee_name") or fw_e.employee

                # WHICH DAY IS THEIRS OFF. Never Sunday by assumption -- workers sit
                # on different weekly offs and assuming would pay a bonus for a day
                # somebody actually worked, or refuse one they earned.
                fw_list = holiday_list_for(fw_e.employee, fw_b)
                fw_off = off_days_in(fw_list, fw_a, fw_b)
                fw_assumed = 0
                fw_rest = fw_off["weekly_off"]
                if not fw_list or not fw_rest:
                    # No off-day data at all. Sunday is the default this project has
                    # always run on, and it is FLAGGED rather than applied silently:
                    # a bonus paid on a guessed rest day is a bonus nobody can check.
                    fw_assumed = 1
                    fw_rest = [d for d in fw_days
                               if frappe.utils.getdate(d).weekday() == 6]

                # Every day of the week that is NOT their rest day, PUBLIC HOLIDAYS
                # INCLUDED. A public holiday is a working day for a casual: missing
                # it forfeits the bonus, attending it earns doubled actuals and keeps
                # the streak. Holiday.weekly_off is what separates the two, and
                # reading it the other way round would pay a bonus for every public
                # holiday in the calendar.
                fw_working = [d for d in fw_days if d not in fw_rest]
                fw_present = []
                if fw_working:
                    for fw_at in frappe.db.sql("""
                        SELECT attendance_date d, status s FROM `tabAttendance`
                        WHERE employee = %(e)s AND docstatus < 2
                          AND attendance_date IN %(days)s
                    """, {"e": fw_e.employee, "days": tuple(fw_working)}, as_dict=True):
                        if fw_at.s in PRESENT_STATUSES:
                            fw_present.append(str(fw_at.d))
                fw_absent = [d for d in fw_working if d not in fw_present]

                fw_earned = 0
                fw_why = None
                if not fw_bonus_on:
                    fw_why = "off-day bonus is switched off in Settings"
                elif not fw_working:
                    fw_why = "no working days in this week to attend"
                elif fw_absent:
                    # name the days, and say when one of them was a public holiday:
                    # "missed holiday" is the reason HR asked to see, because a
                    # worker who thought a holiday was a day off will ask.
                    fw_hol = [d for d in fw_absent if d in fw_off["public"]]
                    fw_why = ("no attendance on " + ", ".join(fw_absent[:4])
                              + ("..." if len(fw_absent) > 4 else ""))
                    if fw_hol:
                        fw_why = fw_why + " (missed holiday: " + ", ".join(fw_hol) + ")"
                else:
                    fw_earned = fw_bonus_amt

                fw_total = frappe.utils.flt(fw_e.owed) + fw_earned
                fw_row = {
                    "employee": fw_e.employee, "employee_name": fw_name,
                    "actuals": frappe.utils.flt(fw_e.owed, 2),
                    "days_worked": frappe.utils.cint(fw_e.days),
                    "qty": frappe.utils.flt(fw_e.qty),
                    "holiday_list": fw_list,
                    "off_day": ", ".join(fw_rest) or None,
                    "off_day_assumed": fw_assumed,
                    "public_holidays": ", ".join(fw_off["public"]) or None,
                    "working_days": len(fw_working),
                    "attended": len(fw_present),
                    "bonus": fw_earned,
                    "bonus_reason": fw_why,
                    "total": frappe.utils.flt(fw_total, 2),
                    "was": frappe.utils.flt(fw_emp.get("custom_basic_pay"), 2),
                    "was_week": fw_emp.get("custom_basic_pay_week"),
                }

                # PRECONDITIONS, checked before anything is written. The same gates
                # the payment run applies, for the same reason: a worker payroll
                # cannot pay is a worker this must not quietly hand a figure to.
                fw_block = None
                if fw_emp.get("status") == "Inactive":
                    fw_block = "employee is Inactive"
                elif fw_emp.get("relieving_date") and fw_pay_on > str(fw_emp["relieving_date"]):
                    fw_block = ("pay date " + fw_pay_on + " is after the relieving date "
                                + str(fw_emp["relieving_date"]))
                elif fw_emp.get("date_of_joining") and fw_pay_on < str(fw_emp["date_of_joining"]):
                    fw_block = ("pay date " + fw_pay_on + " is before the joining date "
                                + str(fw_emp["date_of_joining"]))
                else:
                    fw_ssa = frappe.db.sql("""
                        SELECT name FROM `tabSalary Structure Assignment`
                        WHERE employee = %(e)s AND docstatus = 1 AND from_date <= %(d)s LIMIT 1
                    """, {"e": fw_e.employee, "d": fw_pay_on}, as_dict=True)
                    if not fw_ssa:
                        fw_block = "no submitted Salary Structure Assignment"
                if fw_total <= 0:
                    # A worker with a week of nothing is SKIPPED, not written as 0.
                    # Writing 0 would say "this person earned nothing this week",
                    # which is a claim; not writing says "this feed has nothing to
                    # say about them", which is the truth. Reported all the same,
                    # because a task worker with no confirmed work for a whole week
                    # is a question for HR either way.
                    fw_block = "no confirmed unpaid work in this week"
                    fw_row["hr_question"] = 1
                if fw_block:
                    fw_row["skipped"] = fw_block
                    fw_skipped.append(fw_row)
                    continue
                if str(fw_emp.get("custom_basic_pay_week") or "") == fw_stamp:
                    # RE-FEEDING IS A NO-OP. The week is stamped the way the payment
                    # flow stamps payment_ref, so a second run of the same week says
                    # so instead of silently rewriting the same figure -- or a
                    # different one, if actuals moved underneath it.
                    fw_row["skipped"] = "already fed for " + fw_stamp
                    fw_row["already_fed"] = 1
                    fw_skipped.append(fw_row)
                    continue
                fw_rows.append(fw_row)

                if fw_write and not fw_missing:
                    # A PROPER DOC UPDATE, not frappe.db.set_value(...,
                    # update_modified=False). This is somebody's pay: the change
                    # belongs in the Employee's version history with who made it and
                    # when, which is exactly what a raw column write throws away.
                    fw_doc = frappe.get_doc("Employee", fw_e.employee)
                    fw_doc.custom_basic_pay = fw_row["total"]
                    fw_doc.custom_basic_pay_week = fw_stamp
                    fw_doc.flags.ignore_permissions = True
                    fw_doc.save(ignore_permissions=True)
                    fw_doc.add_comment("Comment",
                        "Basic pay fed from Work Management for " + fw_stamp + ": KES "
                        + str(fw_row["total"]) + " (" + str(fw_row["actuals"])
                        + " actuals" + (" + " + str(fw_earned) + " off-day bonus"
                                        if fw_earned else "") + ") by "
                        + frappe.session.user)
                    fw_written = fw_written + 1

            if fw_write and fw_missing:
                out["error"] = ("Cannot write: " + "; ".join(fw_missing) + ".")
            elif fw_write:
                frappe.db.commit()
            out["preview"] = 0 if fw_write else 1
            out["rows"] = fw_rows
            out["skipped"] = fw_skipped
            out["written"] = fw_written
            out["would_write"] = len(fw_rows)
            out["total"] = frappe.utils.flt(sum(r["total"] for r in fw_rows), 2)
            out["hr_questions"] = [r for r in fw_skipped if r.get("hr_question")]
            out["assumed_off_day"] = [r for r in (fw_rows + fw_skipped)
                                      if r.get("off_day_assumed")]

    else:
        out["error"] = "unknown action: " + str(action)

    return out
