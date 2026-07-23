# Ported from Kaitet live Server Script "wm_assigner" (API) — logic unchanged.
# Farms / projects / company / approver roles now come from Work Management Settings
# (falls back to the original Kaitet defaults) — see upande_work_management/api/config.py.

import frappe

from upande_work_management.api.config import get_config


@frappe.whitelist()
def wm_assigner(**kwargs):
    _cfg = get_config()
    FARM_PROJECT = _cfg["farm_project"]
    DEFAULT_COMPANY = _cfg["default_company"]
    FARMS = _cfg["farms"]
    BLOCK_EXCLUDE = _cfg["block_exclude"]
    FARM_APPROVER_ROLE = _cfg["farm_approver_role"]

    # ==================================================================
    # SERVER SCRIPT — "WM Assigner" (API, api_method=wm_assigner)
    # Powers: Planner + Assigner (a_) + Actuals (act_) + Payment (pay_) + dash
    # Multi-block planner (Option A) + fast grouped-query dashboard.
    # ==================================================================

    # Hours model: Mon-Fri = 8h, Sat = 6h, Sun counts as a workday = 8h.
    # (No def/return allowed at module top-level in the sandbox, so hours are computed inline
    #  wherever needed using frappe.utils.getdate(d).weekday(): Mon=0 .. Sun=6.)
    WEEKDAY_HOURS = 8
    SATURDAY_HOURS = 6
    SUNDAY_HOURS = 8

    action = frappe.form_dict.get("action") or "meta"
    out = {}

    # ===== PLANNER =====
    if action == "a_approved_planners":
        plans = frappe.db.get_all("Work Management Planner", filters={"workflow_state":"Approved"},
            fields=["name","farm","block_section","task","task_kpi","from_date","to_date","people_per_day","total_cost","quantity","custom_close_state"],
            order_by="approval_date desc", limit=200)
        assigned = frappe.db.get_all("Work Management Assigner",
            filters={"workflow_state":["in",["Pending Farm Manager","Pending HR Head","Pending GM","Assigned"]]}, fields=["planner_request"], limit=500)
        taken = {}
        for a in assigned:
            taken[a.planner_request] = 1
        # fully-fulfilled plans (confirmed actuals >= target) also drop out of the picker
        plan_done_pl = {}
        for r in frappe.db.sql("""
            SELECT a2.planner_request pr, COALESCE(SUM(ac.total_actual_qty),0) q
            FROM `tabWork Management Actuals` ac
            INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
            WHERE ac.workflow_state = 'CONFIRMED'
            GROUP BY a2.planner_request
        """, as_dict=True):
            plan_done_pl[r.pr] = frappe.utils.flt(r.q)
        rows = []
        for p in plans:
            # PENDING-ONLY: skip plans already tied to a live assignment...
            if taken.get(p.name):
                continue
            # ...skip plans closed early by an approver
            if (p.get("custom_close_state") or "") == "Closed":
                continue
            # ...and skip plans whose target is already fully met by confirmed actuals
            ptgt = frappe.utils.flt(p.get("quantity"))
            pdone = plan_done_pl.get(p.name, 0)
            if ptgt > 0 and pdone >= ptgt:
                continue
            p["already_assigned"] = 0
            rows.append(p)
        # attach multi-block display (primary + extra_blocks) to each row in view
        pnames_bl = []
        for p in rows:
            pnames_bl.append(p.name)
        extra_map = {}
        if pnames_bl:
            for eb in frappe.db.get_all("Work Planner Block",
                    filters={"parent": ["in", pnames_bl]}, fields=["parent", "block"], order_by="idx"):
                lst = extra_map.get(eb.parent)
                if not lst:
                    lst = []
                    extra_map[eb.parent] = lst
                if eb.block:
                    lst.append(eb.block)
        for p in rows:
            bl = []
            if p.get("block_section"):
                bl.append(p.block_section)
            for b in extra_map.get(p.name, []):
                if b not in bl:
                    bl.append(b)
            p["blocks"] = bl
            p["block_count"] = len(bl)
        out["planners"] = rows

    elif action == "a_planner_detail":
        nm = frappe.form_dict.get("planner")
        out["planner"] = frappe.db.get_value("Work Management Planner", nm,
            ["name","farm","company","block_section","task","task_kpi","from_date","to_date","people_per_day","total_cost"],
            as_dict=True)
        # include full block list for display
        blist = []
        prim = out["planner"].block_section if out["planner"] else None
        if prim:
            blist.append(prim)
        for r in frappe.db.get_all("Work Planner Block", filters={"parent":nm}, fields=["block"], order_by="idx"):
            if r.block:
                blist.append(r.block)
        out["blocks"] = blist

    elif action == "a_employees":
        emps = frappe.db.get_all("Employee",
            filters={"status":"Active","custom_farm":frappe.form_dict.get("farm")},
            fields=["name","employee_name","designation","employment_type","holiday_list"],
            order_by="employee_name", limit=1000)
        # off-day count within an optional plan period, so the Assigner can warn
        pf = frappe.form_dict.get("from_date")
        pt = frappe.form_dict.get("to_date")
        # DOUBLE-ALLOCATION GUARD: find workers already on a live assignment whose period OVERLAPS this plan.
        # Live states = Pending Farm Manager / Pending HR Head / Pending GM / Assigned. Exclude the doc being edited.
        exclude_asg = frappe.form_dict.get("exclude_assignment") or "__none__"
        allocated = {}
        if pf and pt:
            rows = frappe.db.sql("""
                SELECT we.employee emp, a.name asg, a.farm farm, a.task task, a.from_date fd, a.to_date td
                FROM `tabWork Assignment Employee` we
                INNER JOIN `tabWork Management Assigner` a ON we.parent = a.name
                WHERE a.workflow_state IN ('Pending Farm Manager','Pending HR Head','Pending GM','Assigned')
                  AND a.name != %s
                  AND IFNULL(we.status,'Active') = 'Active'
                  AND a.from_date <= %s AND a.to_date >= %s
            """, (exclude_asg, pt, pf), as_dict=True)
            for r in rows:
                if r.emp and r.emp not in allocated:
                    allocated[r.emp] = {"assignment": r.asg, "farm": r.farm, "task": r.task}
        for e in emps:
            oc = 0
            if e.holiday_list and pf and pt:
                oc = frappe.db.count("Holiday", {"parent": e.holiday_list, "holiday_date": ["between", [pf, pt]]})
            e["off_days"] = oc
            al = allocated.get(e.name)
            if al:
                e["allocated_elsewhere"] = 1
                e["allocated_asg"] = al["assignment"]
                e["allocated_task"] = al["task"]
                e["allocated_farm"] = al["farm"]
            else:
                e["allocated_elsewhere"] = 0
        out["employees"] = emps

    elif action == "a_my_assignments":
        out["assignments"] = frappe.db.get_all("Work Management Assigner",
            filters={"assigned_by":frappe.session.user},
            fields=["name","planner_request","farm","task","block_section","planned_people","assigned_count",
                    "variance","workflow_state","assign_date"], order_by="creation desc", limit=200)

    elif action == "a_pending":
        stage = frappe.form_dict.get("stage") or "Pending HR Head"
        fmflt = {"workflow_state": stage}
        # at the FM stage, a farm manager only sees their own farm(s)
        if stage == "Pending Farm Manager":
            fmrl = frappe.db.get_all("Has Role", filters={"parent": frappe.session.user}, pluck="role")
            fmbypass = ("System Manager" in fmrl) or ("General Manager" in fmrl)
            if not fmbypass:
                fmallowed = []
                for _farm_, _role_ in FARM_APPROVER_ROLE.items():
                    if _role_ in fmrl: fmallowed.append(_farm_)
                fmflt["farm"] = ["in", fmallowed] if fmallowed else ["in", ["__none__"]]
        out["pending"] = frappe.db.get_all("Work Management Assigner",
            filters=fmflt,
            fields=["name","planner_request","farm","task","block_section","from_date","to_date","planned_people",
                    "assigned_count","variance","planned_cost","assigned_by","assign_date"],
            order_by="assign_date desc", limit=200)

    elif action == "a_submit":
        planner = frappe.form_dict.get("planner"); emps_raw = frappe.form_dict.get("employees")
        submit_now = frappe.form_dict.get("submit_now")
        asg_name = frappe.form_dict.get("assignment")  # editing an existing draft
        err = None
        if not planner: err = "Planner request is required"
        emp_list = []
        if emps_raw:
            for e in emps_raw.split(","):
                ev = e.strip()
                if ev and ev not in emp_list:
                    emp_list.append(ev)
        if not emp_list: err = "Assign at least one employee"
        # HARD CAP: active assigned workers may not exceed the plan's people_per_day
        planned = 0
        if planner:
            planned = frappe.utils.cint(frappe.db.get_value("Work Management Planner", planner, "people_per_day"))
        if not err and planned > 0 and len(emp_list) > planned:
            err = "Too many workers: plan allows " + str(planned) + " per day, you selected " + str(len(emp_list)) + ". Remove " + str(len(emp_list) - planned) + "."
        # DOUBLE-ALLOCATION GUARD (server enforcement): reject workers already on an overlapping live assignment
        if not err and planner and emp_list:
            p_dates = frappe.db.get_value("Work Management Planner", planner, ["from_date","to_date"], as_dict=True)
            if p_dates and p_dates.from_date and p_dates.to_date:
                clash = frappe.db.sql("""
                    SELECT DISTINCT we.employee emp
                    FROM `tabWork Assignment Employee` we
                    INNER JOIN `tabWork Management Assigner` a ON we.parent = a.name
                    WHERE a.workflow_state IN ('Pending Farm Manager','Pending HR Head','Pending GM','Assigned')
                      AND a.name != %s
                      AND IFNULL(we.status,'Active') = 'Active'
                      AND a.from_date <= %s AND a.to_date >= %s
                      AND we.employee IN %s
                """, (asg_name or "__none__", p_dates.to_date, p_dates.from_date, tuple(emp_list)), as_dict=True)
                if clash:
                    names = []
                    for c in clash:
                        nm = frappe.db.get_value("Employee", c.emp, "employee_name") or c.emp
                        names.append(nm)
                    err = "These workers are already assigned elsewhere for an overlapping period: " + ", ".join(names[:8]) + (" and more" if len(names) > 8 else "") + ". Remove them to avoid double-allocation."
        if err:
            out["error"] = err
        else:
            editing = 0
            editing_pending = 0  # approver editing a doc mid-approval (keep its state)
            if asg_name and frappe.db.exists("Work Management Assigner", asg_name):
                state = frappe.db.get_value("Work Management Assigner", asg_name, "workflow_state")
                if state in ("Draft", "Rejected"):
                    d = frappe.get_doc("Work Management Assigner", asg_name)
                    d.set("employees", [])
                    editing = 1
                elif state in ("Pending Farm Manager", "Pending HR Head", "Pending GM"):
                    d = frappe.get_doc("Work Management Assigner", asg_name)
                    d.set("employees", [])
                    editing = 1
                    editing_pending = 1
                else:
                    d = frappe.new_doc("Work Management Assigner")
                    d.planner_request = planner
            else:
                d = frappe.new_doc("Work Management Assigner")
                d.planner_request = planner
            for ev in emp_list:
                row = d.append("employees", {})
                row.employee = ev
                row.status = "Active"
            # the enterer may have a User Permission on Employee that excludes some workers on
            # this assignment; the workflow validator calls check_permission("read") which would
            # throw. Set the doc-level flag so validation doesn't enforce the caller's row access.
            d.flags.ignore_permissions = True
            if not editing:
                d.assigned_by = frappe.session.user; d.assign_date = frappe.utils.today()
            if editing:
                if not submit_now and not editing_pending:
                    d.workflow_state = "Draft"
                d.save(ignore_permissions=True)
            else:
                d.insert(ignore_permissions=True)
            # assigned_count counts ACTIVE only
            active = 0
            for r in d.employees:
                if (r.status or "Active") == "Active":
                    active = active + 1
            d.assigned_count = active
            d.variance = active - frappe.utils.cint(d.planned_people)
            d.save(ignore_permissions=True)
            if submit_now and not editing_pending:
                # bypass workflow engine transition-role gate
                frappe.db.set_value("Work Management Assigner", d.name, "workflow_state", "Pending Farm Manager", update_modified=False)
                d.workflow_state = "Pending Farm Manager"
            out["name"] = d.name; out["workflow_state"] = d.workflow_state
            out["assigned_count"] = d.assigned_count; out["variance"] = d.variance
            out["editing"] = editing; out["editing_pending"] = editing_pending

    elif action == "a_fm_approve":
        nm = frappe.form_dict.get("name")
        cur = frappe.db.get_value("Work Management Assigner", nm, ["workflow_state","farm"], as_dict=True)
        fmrl = frappe.db.get_all("Has Role", filters={"parent": frappe.session.user}, pluck="role")
        fmallowed = []
        for _farm_, _role_ in FARM_APPROVER_ROLE.items():
            if _role_ in fmrl: fmallowed.append(_farm_)
        fmbypass = ("System Manager" in fmrl) or ("General Manager" in fmrl)
        if not cur:
            out["error"] = "Record not found"
        elif cur.workflow_state != "Pending Farm Manager":
            out["error"] = "Not at Farm Manager stage (state: " + str(cur.workflow_state) + ")"
        elif not fmbypass and cur.farm not in fmallowed:
            if not fmallowed:
                out["error"] = "You have no farm assigned for approvals. Ask an admin to grant you a farm-specific Farm Manager role."
            else:
                out["error"] = "You can only approve records for your farm(s): " + ", ".join(fmallowed) + ". This record is for " + str(cur.farm) + "."
        else:
            frappe.db.set_value("Work Management Assigner", nm, "workflow_state", "Pending HR Head", update_modified=False)
            try:
                frappe.db.set_value("Work Management Assigner", nm, "fm_approved_by", frappe.session.user, update_modified=False)
                frappe.db.set_value("Work Management Assigner", nm, "fm_approval_date", frappe.utils.today(), update_modified=False)
            except Exception:
                pass
            out["name"] = nm; out["workflow_state"] = "Pending HR Head"

    elif action == "a_hr_approve":
        nm = frappe.form_dict.get("name")
        cur_ws = frappe.db.get_value("Work Management Assigner", nm, "workflow_state")
        if cur_ws != "Pending HR Head":
            out["error"] = "Not at HR stage (state: " + str(cur_ws) + ")"
        else:
            frappe.db.set_value("Work Management Assigner", nm, "workflow_state", "Pending GM", update_modified=False)
            try:
                frappe.db.set_value("Work Management Assigner", nm, "hr_approved_by", frappe.session.user, update_modified=False)
                frappe.db.set_value("Work Management Assigner", nm, "hr_approval_date", frappe.utils.today(), update_modified=False)
            except Exception:
                pass
            out["name"] = nm; out["workflow_state"] = "Pending GM"

    elif action == "a_gm_approve":
        nm = frappe.form_dict.get("name")
        cur_ws = frappe.db.get_value("Work Management Assigner", nm, "workflow_state")
        if cur_ws != "Pending GM":
            out["error"] = "Not at GM stage (state: " + str(cur_ws) + ")"
        else:
            frappe.db.set_value("Work Management Assigner", nm, "workflow_state", "Assigned", update_modified=False)
            frappe.db.set_value("Work Management Assigner", nm, "docstatus", 1, update_modified=False)
            for kid in frappe.db.get_all("Work Assignment Employee", filters={"parent": nm}, pluck="name"):
                frappe.db.set_value("Work Assignment Employee", kid, "docstatus", 1, update_modified=False)
            frappe.db.set_value("Work Management Assigner", nm, "approved_by", frappe.session.user, update_modified=False)
            frappe.db.set_value("Work Management Assigner", nm, "approval_date", frappe.utils.today(), update_modified=False)
            try:
                frappe.db.set_value("Work Management Assigner", nm, "gm_approved_by", frappe.session.user, update_modified=False)
                frappe.db.set_value("Work Management Assigner", nm, "gm_approval_date", frappe.utils.today(), update_modified=False)
            except Exception:
                pass
            out["name"] = nm; out["workflow_state"] = "Assigned"

    elif action == "a_reject":
        nm = frappe.form_dict.get("name")
        cur_ws = frappe.db.get_value("Work Management Assigner", nm, "workflow_state")
        if cur_ws not in ("Pending Farm Manager","Pending HR Head","Pending GM"):
            out["error"] = "Not awaiting approval (state: " + str(cur_ws) + ")"
        else:
            frappe.db.set_value("Work Management Assigner", nm, "workflow_state", "Rejected", update_modified=False)
            frappe.db.set_value("Work Management Assigner", nm, "approved_by", None, update_modified=False)
            frappe.db.set_value("Work Management Assigner", nm, "approval_date", None, update_modified=False)
            out["name"] = nm; out["workflow_state"] = "Rejected"

    elif action == "a_roles":
        roles = frappe.db.get_all("Has Role", filters={"parent":frappe.session.user}, fields=["role"])
        rl = []
        for r in roles:
            rl.append(r.role)
        out["user"] = frappe.session.user
        out["is_clerk"] = ("HR User" in rl) or ("HR Manager" in rl) or ("HR Clerk" in rl) or ("HOD HR" in rl)
        out["is_hr_head"] = ("HOD HR" in rl) or ("HR Manager Kaitet" in rl)
        out["is_gm"] = "General Manager" in rl
        out["is_accounts"] = ("Accounts Manager" in rl) or ("Accounts User" in rl)
        out["is_farm_manager"] = ("Farm Manager" in rl) or any(_r_ in rl for _r_ in FARM_APPROVER_ROLE.values())

    # ===== ACTUALS (act_) =====
    elif action == "a_detail":
        nm = frappe.form_dict.get("assignment")
        a = frappe.db.get_value("Work Management Assigner", nm,
            ["name","planner_request","farm","block_section","task","task_kpi","from_date","to_date",
             "planned_people","planned_cost","assigned_count","variance","workflow_state"], as_dict=True)
        if a:
            a["editable"] = 1 if a.workflow_state in ("Draft","Rejected","Pending Farm Manager","Pending HR Head","Pending GM") else 0
            a["can_substitute"] = 1 if a.workflow_state == "Assigned" else 0
            rows = frappe.db.get_all("Work Assignment Employee",
                filters={"parent": nm},
                fields=["employee","employee_name","designation","employment_type","status","start_date","left_date"],
                order_by="idx")
            # per-worker days worked + pay to date (confirmed actuals on this plan)
            pr2 = a.planner_request
            worked = {}
            if pr2:
                for w in frappe.db.sql("""
                    SELECT we.employee emp,
                           COUNT(DISTINCT we.work_date) days,
                           COALESCE(SUM(we.actual_quantity),0) qty,
                           COALESCE(SUM(we.amount),0) pay
                    FROM `tabWork Actuals Employee` we
                    INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
                    INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
                    WHERE a2.planner_request = %s AND ac.workflow_state = 'CONFIRMED'
                    GROUP BY we.employee
                """, (pr2,), as_dict=True):
                    worked[w.emp] = w
            fromd2 = a.from_date
            tod2 = a.to_date
            for r in rows:
                wk = worked.get(r.employee)
                r["days_worked"] = wk.days if wk else 0
                r["qty_done"] = wk.qty if wk else 0
                r["pay_to_date"] = wk.pay if wk else 0
                offc = 0
                hl2 = frappe.db.get_value("Employee", r.employee, "holiday_list")
                if hl2 and fromd2 and tod2:
                    offc = frappe.db.count("Holiday", {"parent": hl2, "holiday_date": ["between", [fromd2, tod2]]})
                r["off_days"] = offc
            a["workers"] = rows
            active = 0
            for r in rows:
                if (r.status or "Active") == "Active":
                    active = active + 1
            a["active_count"] = active
            # plan burn-down context
            a["fulfilled_qty"] = frappe.utils.flt(frappe.db.get_value("Work Management Planner", pr2, "fulfilled_qty")) if pr2 else 0
            a["target_qty"] = frappe.utils.flt(frappe.db.get_value("Work Management Planner", pr2, "quantity")) if pr2 else 0
            a["remaining_qty"] = a["target_qty"] - a["fulfilled_qty"]
            a["uom"] = frappe.db.get_value("Work Management Planner", pr2, "uom") if pr2 else ""
            a["rate"] = frappe.utils.flt(frappe.db.get_value("Work Management Planner", pr2, "rate")) if pr2 else 0
        out["detail"] = a

    elif action == "a_sub_candidates":
        # Task Workers on this farm NOT already on this assignment,
        # AND not Active on another live assignment overlapping this period.
        nm = frappe.form_dict.get("assignment")
        farm = frappe.db.get_value("Work Management Assigner", nm, "farm")
        adates = frappe.db.get_value("Work Management Assigner", nm, ["from_date", "to_date"], as_dict=True)
        already = frappe.db.get_all("Work Assignment Employee", filters={"parent": nm}, pluck="employee")
        already_map = {}
        for e in already:
            already_map[e] = 1
        # workers busy elsewhere on an overlapping live assignment
        busy_map = {}
        if adates and adates.from_date and adates.to_date:
            busyrows = frappe.db.sql("""
                SELECT DISTINCT we.employee emp
                FROM `tabWork Assignment Employee` we
                INNER JOIN `tabWork Management Assigner` a ON we.parent = a.name
                WHERE a.workflow_state IN ('Pending Farm Manager','Pending HR Head','Pending GM','Assigned')
                  AND a.name != %s
                  AND IFNULL(we.status,'Active') = 'Active'
                  AND a.from_date <= %s AND a.to_date >= %s
            """, (nm, adates.to_date, adates.from_date), as_dict=True)
            for r in busyrows:
                busy_map[r.emp] = 1
        cands = []
        for emp in frappe.db.get_all("Employee",
                filters={"status": "Active", "custom_farm": farm, "employment_type": "Task Worker"},
                fields=["name", "employee_name"], order_by="employee_name", limit=1000):
            if not already_map.get(emp.name) and not busy_map.get(emp.name):
                cands.append(emp)
        out["candidates"] = cands

    elif action == "a_substitute":
        # one-for-one: outgoing -> Left(+left_date); replacement appended Active(+start_date)
        nm = frappe.form_dict.get("assignment")
        outgoing = frappe.form_dict.get("outgoing")
        replacement = frappe.form_dict.get("replacement")
        left_date = frappe.form_dict.get("left_date")
        start_date = frappe.form_dict.get("start_date")
        err = None
        if not nm or not outgoing or not replacement: err = "Outgoing, replacement, and dates are required"
        if not left_date or not start_date: err = "Both the left date and the replacement start date are required"
        d = None
        if not err:
            d = frappe.get_doc("Work Management Assigner", nm)
            if d.workflow_state != "Assigned":
                err = "Substitution only allowed on an approved (Assigned) plan"
        if not err:
            # replacement must not already be on the roster
            for r in d.employees:
                if r.employee == replacement:
                    err = "Replacement is already on this plan"
            # verify replacement is a Task Worker
            rep_type = frappe.db.get_value("Employee", replacement, "employment_type")
            if rep_type != "Task Worker":
                err = "Replacement must be a Task Worker"
        if not err:
            # cross-assignment overlap guard: replacement must not be Active elsewhere over this period
            rdates = frappe.db.get_value("Work Management Assigner", nm, ["from_date", "to_date"], as_dict=True)
            if rdates and rdates.from_date and rdates.to_date:
                clash = frappe.db.sql("""
                    SELECT a.name asg
                    FROM `tabWork Assignment Employee` we
                    INNER JOIN `tabWork Management Assigner` a ON we.parent = a.name
                    WHERE a.workflow_state IN ('Pending Farm Manager','Pending HR Head','Pending GM','Assigned')
                      AND a.name != %s
                      AND IFNULL(we.status,'Active') = 'Active'
                      AND we.employee = %s
                      AND a.from_date <= %s AND a.to_date >= %s
                    LIMIT 1
                """, (nm, replacement, rdates.to_date, rdates.from_date), as_dict=True)
                if clash:
                    err = "Replacement is already assigned elsewhere for an overlapping period (" + str(clash[0].asg) + "). Pick someone else."
        if err:
            out["error"] = err
        else:
            # find the outgoing ACTIVE child row (by its child docname)
            out_rowname = None
            for r in d.employees:
                if r.employee == outgoing and (r.status or "Active") == "Active":
                    out_rowname = r.name
            if not out_rowname:
                out["error"] = "Outgoing worker not found or already Left"
            else:
                # This assignment is SUBMITTED (docstatus=1). doc.save() is blocked on submitted docs,
                # so we edit the child rows + parent counts via direct DB writes (allowed, no re-approval).
                rep_name = frappe.db.get_value("Employee", replacement, "employee_name")
                # 1) mark outgoing row Left + left_date
                frappe.db.set_value("Work Assignment Employee", out_rowname, "status", "Left", update_modified=False)
                frappe.db.set_value("Work Assignment Employee", out_rowname, "left_date", left_date, update_modified=False)
                # 2) insert the replacement as a new child row of this parent
                maxidx = frappe.db.sql("SELECT COALESCE(MAX(idx),0) m FROM `tabWork Assignment Employee` WHERE parent=%s", (nm,), as_dict=True)
                next_idx = (maxidx[0].m if maxidx else 0) + 1
                child = frappe.new_doc("Work Assignment Employee")
                child.parent = nm
                child.parenttype = "Work Management Assigner"
                child.parentfield = "employees"
                child.idx = next_idx
                child.employee = replacement
                child.employee_name = rep_name
                child.employment_type = "Task Worker"
                child.status = "Active"
                child.start_date = start_date
                child.count_in_payroll = 1
                child.db_insert()
                # 3) recount ACTIVE rows and update parent counts (direct write; parent is submitted)
                active_rows = frappe.db.sql("SELECT COUNT(*) c FROM `tabWork Assignment Employee` WHERE parent=%s AND (status IS NULL OR status='Active')", (nm,), as_dict=True)
                active = active_rows[0].c if active_rows else 0
                planned = frappe.utils.cint(d.planned_people)
                frappe.db.set_value("Work Management Assigner", nm, "assigned_count", active, update_modified=False)
                frappe.db.set_value("Work Management Assigner", nm, "variance", active - planned, update_modified=False)
                frappe.db.commit()
                out["name"] = nm
                out["substituted"] = outgoing
                out["replacement"] = replacement
                out["active_count"] = active

    else:
        out["error"] = "unknown action: " + str(action)


    return out
