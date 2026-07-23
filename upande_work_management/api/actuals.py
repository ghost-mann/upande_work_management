# Ported from Kaitet live Server Script "wm_actuals" (API) — logic unchanged.
# Farms / projects / company / approver roles now come from Work Management Settings
# (falls back to the original Kaitet defaults) — see upande_work_management/api/config.py.

import frappe

from upande_work_management.api.config import get_config


@frappe.whitelist()
def wm_actuals(**kwargs):
    _cfg = get_config()
    FARM_PROJECT = _cfg["farm_project"]
    DEFAULT_COMPANY = _cfg["default_company"]
    FARMS = _cfg["farms"]
    BLOCK_EXCLUDE = _cfg["block_exclude"]
    FARM_APPROVER_ROLE = _cfg["farm_approver_role"]

    # ==================================================================
    # SERVER SCRIPT — "WM Actuals" (API, api_method=wm_actuals)
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
    if action == "act_assigned":
        asgs = frappe.db.get_all("Work Management Assigner", filters={"workflow_state":"Assigned"},
            fields=["name","farm","block_section","task","task_kpi","from_date","to_date",
                    "planned_people","planned_cost","planner_request","assigned_count"],
            order_by="approval_date desc", limit=200)
        # plan target + fulfilled, so we can show remaining and only hide FULLY fulfilled assignments
        plan_target = {}
        plan_done = {}
        plan_closed = {}
        for a in asgs:
            pr = a.planner_request
            if pr and pr not in plan_target:
                plan_target[pr] = frappe.utils.flt(frappe.db.get_value("Work Management Planner", pr, "quantity"))
                plan_closed[pr] = (frappe.db.get_value("Work Management Planner", pr, "custom_close_state") or "")
        # sum confirmed actuals per plan
        for r in frappe.db.sql("""
            SELECT a2.planner_request pr, COALESCE(SUM(ac.total_actual_qty),0) q
            FROM `tabWork Management Actuals` ac
            INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
            WHERE ac.workflow_state = 'CONFIRMED'
            GROUP BY a2.planner_request
        """, as_dict=True):
            plan_done[r.pr] = frappe.utils.flt(r.q)
        # sum NOT-yet-confirmed recorded actuals per plan (Draft + in-review), for the overlay bar
        plan_pending = {}
        for r in frappe.db.sql("""
            SELECT a2.planner_request pr, COALESCE(SUM(ac.total_actual_qty),0) q
            FROM `tabWork Management Actuals` ac
            INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
            WHERE ac.workflow_state IN ('Draft','Pending Farm Manager','Pending HR Head','Pending GM')
            GROUP BY a2.planner_request
        """, as_dict=True):
            plan_pending[r.pr] = frappe.utils.flt(r.q)
        # count entries currently in review (pending) per assignment, to warn the clerk
        inreview = {}
        for r in frappe.db.sql("""
            SELECT assignment, COUNT(name) n
            FROM `tabWork Management Actuals`
            WHERE workflow_state IN ('Pending HR Head','Pending GM')
            GROUP BY assignment
        """, as_dict=True):
            inreview[r.assignment] = r.n
        rows = []
        for a in asgs:
            pr = a.planner_request
            target = plan_target.get(pr, 0)
            done = plan_done.get(pr, 0)
            pending = plan_pending.get(pr, 0)
            recorded = done + pending
            remaining = target - recorded
            a["target_qty"] = target
            a["fulfilled_qty"] = done
            a["pending_qty"] = pending
            a["recorded_qty"] = recorded
            a["remaining_qty"] = remaining
            a["pct"] = (done / target * 100) if target > 0 else 0
            a["pct_recorded"] = (recorded / target * 100) if target > 0 else 0
            a["in_review"] = inreview.get(a.name, 0)
            a["fulfilled_done"] = 1 if (target > 0 and recorded >= target) else 0
            # CLOSED-EARLY: drop plans an approver closed early, so they aren't offered for fresh entry
            if plan_closed.get(pr, "") in ("Closed", "Completed"):
                continue
            # PENDING-ONLY: hide assignments whose plan target is already fully met (reduce clutter).
            # Keep those with remaining work, and those with no target set (target==0) so they aren't lost.
            if a["fulfilled_done"]:
                continue
            rows.append(a)
        # attach multi-block display (primary + plan extra_blocks) to each assignment in view
        pr_set = {}
        for a in rows:
            if a.get("planner_request"):
                pr_set[a.planner_request] = 1
        pr_list = []
        for k in pr_set:
            pr_list.append(k)
        extra_map = {}
        if pr_list:
            for eb in frappe.db.get_all("Work Planner Block",
                    filters={"parent": ["in", pr_list]}, fields=["parent", "block"], order_by="idx"):
                lst = extra_map.get(eb.parent)
                if not lst:
                    lst = []
                    extra_map[eb.parent] = lst
                if eb.block:
                    lst.append(eb.block)
        for a in rows:
            bl = []
            if a.get("block_section"):
                bl.append(a.block_section)
            for b in extra_map.get(a.get("planner_request"), []):
                if b not in bl:
                    bl.append(b)
            a["blocks"] = bl
            a["block_count"] = len(bl)
        out["assignments"] = rows
    elif action == "act_detail":
        name = frappe.form_dict.get("assignment")
        a = frappe.db.get_value("Work Management Assigner", name,
            ["name","farm","block_section","task","task_kpi","from_date","to_date",
             "planned_people","planned_cost","planner_request"], as_dict=True)
        rate = 0
        target = 0
        uom = None
        pr = a.planner_request if a else None
        if pr:
            pinfo = frappe.db.get_value("Work Management Planner", pr,
                ["rate","quantity","uom","daily_target","custom_close_state"], as_dict=True)
            if pinfo:
                rate = frappe.utils.flt(pinfo.rate)
                target = frappe.utils.flt(pinfo.quantity)
                uom = pinfo.uom
                a["daily_target"] = frappe.utils.flt(pinfo.daily_target)
                a["close_state"] = pinfo.custom_close_state
        a["rate"] = rate
        a["target_qty"] = target
        a["uom"] = uom
        # total block area (Ha) = primary block_section + extra_blocks, summed from Warehouse.custom_area_ha
        block_area = 0
        bset = {}
        prim_block = a.block_section
        if prim_block:
            bset[prim_block] = 1
        if pr:
            for eb in frappe.db.sql("""SELECT block FROM `tabWork Planner Block` WHERE parent = %s""", (pr,), as_dict=True):
                if eb.block:
                    bset[eb.block] = 1
        for bn in bset:
            block_area = block_area + frappe.utils.flt(frappe.db.get_value("Warehouse", bn, "custom_area_ha"))
        a["block_area"] = block_area
        # blocks list for display (primary first, then extras) — assigner/actuals show all, not just primary
        blist_d = []
        if prim_block:
            blist_d.append(prim_block)
        for bn in bset:
            if bn not in blist_d:
                blist_d.append(bn)
        a["blocks"] = blist_d
        a["block_count"] = len(blist_d)
        # fulfilled so far (confirmed only)
        done = 0
        if pr:
            dr = frappe.db.sql("""
                SELECT COALESCE(SUM(ac.total_actual_qty),0) q
                FROM `tabWork Management Actuals` ac
                INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
                WHERE a2.planner_request = %s AND ac.workflow_state = 'CONFIRMED'
            """, (pr,), as_dict=True)
            done = frappe.utils.flt(dr[0].q) if dr else 0
        a["fulfilled_qty"] = done
        a["remaining_qty"] = target - done
        a["pct"] = (done / target * 100) if target > 0 else 0
        a["over_target"] = 1 if (target > 0 and done > target) else 0
        # done_elsewhere: qty committed on OTHER docs for this plan (Pending+Confirmed), EXCLUDING this assignment's own doc.
        # Front-end cap uses this so the running total in the grid matches the server hard-block.
        done_elsewhere = 0
        if pr:
            de = frappe.db.sql("""
                SELECT COALESCE(SUM(ac.total_actual_qty),0) q
                FROM `tabWork Management Actuals` ac
                INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
                WHERE a2.planner_request = %s
                  AND ac.workflow_state IN ('Pending HR Head','Pending GM','CONFIRMED')
                  AND ac.assignment != %s
            """, (pr, name), as_dict=True)
            done_elsewhere = frappe.utils.flt(de[0].q) if de else 0
        a["done"] = done_elsewhere
        a["remaining_for_entry"] = target - done_elsewhere
        # raw SQL (not get_all) so the child rows aren't permission-filtered to empty
        # for users without explicit read perm on Work Assignment Employee (e.g. HR Head).
        workers = frappe.db.sql("""
            SELECT employee, employee_name, designation, employment_type,
                   status, start_date, left_date
            FROM `tabWork Assignment Employee`
            WHERE parent = %s
            ORDER BY idx
        """, (name,), as_dict=True)
        # off-days per worker within the plan period (from their Employee.holiday_list)
        fromd = a.from_date
        tod = a.to_date
        # check Leave Application availability ONCE (avoids per-worker failures blanking the grid)
        leave_ok = 0
        try:
            if frappe.db.exists("DocType", "Leave Application"):
                leave_ok = 1
        except Exception:
            leave_ok = 0
        for w in workers:
            offs = []
            hl = frappe.db.get_value("Employee", w.employee, "holiday_list")
            if hl and fromd and tod:
                for h in frappe.db.sql("""SELECT holiday_date FROM `tabHoliday`
                        WHERE parent = %s AND holiday_date BETWEEN %s AND %s""",
                        (hl, fromd, tod), as_dict=True):
                    offs.append(str(h.holiday_date))
            w["off_dates"] = offs
            # approved + pending leave overlapping the plan period (ERPNext Leave Application).
            # Defensive: any failure here must NOT stop workers loading, so we swallow errors
            # and fall back to empty leave lists.
            leave_appr = []
            leave_pend = []
            if leave_ok and fromd and tod:
                try:
                    la_rows = frappe.get_all("Leave Application",
                        filters={"employee": w.employee,
                                 "from_date": ["<=", tod],
                                 "to_date": [">=", fromd],
                                 "status": ["in", ["Approved", "Open"]]},
                        fields=["from_date", "to_date", "status"])
                except Exception:
                    la_rows = []
                for la in la_rows:
                    ds = la.get("from_date")
                    de = la.get("to_date")
                    if not ds or not de:
                        continue
                    cur = frappe.utils.getdate(ds)
                    endd = frappe.utils.getdate(de)
                    guard = 0
                    while cur <= endd and guard < 400:
                        iso = str(cur)
                        if (iso >= str(fromd)) and (iso <= str(tod)):
                            if la.get("status") == "Approved":
                                leave_appr.append(iso)
                            else:
                                leave_pend.append(iso)
                        cur = frappe.utils.add_days(cur, 1)
                        guard = guard + 1
            w["leave_dates"] = leave_appr
            w["leave_pending_dates"] = leave_pend
        a["workers"] = workers
        # calendar: confirmed daily rollup for this plan
        daymap = {}
        if pr:
            for r in frappe.db.sql("""
                SELECT ac.entry_date d,
                       COALESCE(SUM(ac.total_actual_qty),0) qty,
                       COALESCE(SUM(ac.payroll_people),0) workers,
                       COALESCE(SUM(ac.total_payment),0) pay,
                       COUNT(ac.name) entries
                FROM `tabWork Management Actuals` ac
                INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
                WHERE a2.planner_request = %s AND ac.workflow_state = 'CONFIRMED'
                GROUP BY ac.entry_date ORDER BY ac.entry_date
            """, (pr,), as_dict=True):
                daymap[str(r.d)] = {"qty": r.qty, "workers": r.workers, "pay": r.pay, "entries": r.entries}
        a["days"] = daymap
        # per-day per-worker confirmed breakdown (for the calendar day panel)
        dayw = {}
        if pr:
            for r in frappe.db.sql("""
                SELECT wae.work_date d, wae.employee emp,
                       COALESCE(e.employee_name, wae.employee) nm,
                       COALESCE(e.employment_type, '') et,
                       COALESCE(SUM(wae.actual_quantity),0) qty
                FROM `tabWork Actuals Employee` wae
                INNER JOIN `tabWork Management Actuals` ac ON wae.parent = ac.name
                INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
                LEFT JOIN `tabEmployee` e ON e.name = wae.employee
                WHERE a2.planner_request = %s AND ac.workflow_state = 'CONFIRMED'
                  AND COALESCE(wae.actual_quantity,0) > 0
                GROUP BY wae.work_date, wae.employee
                ORDER BY qty DESC
            """, (pr,), as_dict=True):
                k = str(r.d)
                if k not in dayw:
                    dayw[k] = []
                dayw[k].append({"employee": r.emp, "name": r.nm, "et": r.et, "qty": r.qty})
        a["day_workers"] = dayw
        # existing Draft/Rejected doc for this assignment -> return its cells so the grid resumes.
        # Raw SQL (not get_all) so a low-privilege user without doctype read still loads the grid.
        draft = frappe.db.sql("""
            SELECT name, workflow_state FROM `tabWork Management Actuals`
            WHERE assignment = %s AND workflow_state IN ('Draft','Rejected') LIMIT 1
        """, (name,), as_dict=True)
        a["draft_name"] = draft[0].name if draft else None
        a["draft_state"] = draft[0].workflow_state if draft else None
        cells = {}
        if draft:
            for r in frappe.db.sql("""
                    SELECT employee, work_date, actual_quantity
                    FROM `tabWork Actuals Employee` WHERE parent = %s
            """, (draft[0].name,), as_dict=True):
                cells[str(r.employee) + "~" + str(r.work_date)] = r.actual_quantity
        a["cells"] = cells
        # also: is there a live (in-review/confirmed) doc blocking new entry?
        live = frappe.db.sql("""
            SELECT name, workflow_state FROM `tabWork Management Actuals`
            WHERE assignment = %s AND workflow_state IN ('Pending HR Head','Pending GM','CONFIRMED') LIMIT 1
        """, (name,), as_dict=True)
        a["live_name"] = live[0].name if live else None
        a["live_state"] = live[0].workflow_state if live else None
        out["detail"] = a

    elif action == "act_submit":
        # payload = per-worker-per-day cells: "emp~date~qty|emp~date~qty|..."
        assignment = frappe.form_dict.get("assignment")
        payload = frappe.form_dict.get("rows")
        submit_now = frappe.form_dict.get("submit_now")
        err = None
        if not assignment: err = "Assignment is required"
        if err:
            out["error"] = err
        else:
            # read the assignment's plan link without get_doc (which hits the doctype-access gate
            # for farm managers / section heads / clerks who lack broad DocPerms)
            a_pr = frappe.db.get_value("Work Management Assigner", assignment, "planner_request")
            rate = 0
            if a_pr:
                rate = frappe.utils.flt(frappe.db.get_value("Work Management Planner", a_pr, "rate"))
            edit_doc = frappe.form_dict.get("edit_doc")  # approver editing a pending doc in place
            # ONE doc per assignment: resume existing Draft/Rejected, else create new.
            existing = frappe.db.get_all("Work Management Actuals",
                filters={"assignment": assignment, "workflow_state": ["in", ["Draft", "Rejected"]]},
                pluck="name", limit=1)
            live = frappe.db.get_all("Work Management Actuals",
                filters={"assignment": assignment, "workflow_state": ["in", ["Pending Farm Manager","Pending HR Head","Pending GM","CONFIRMED"]]},
                pluck="name", limit=1)
            editing_pending = 0
            if edit_doc and frappe.db.exists("Work Management Actuals", edit_doc):
                estate = frappe.db.get_value("Work Management Actuals", edit_doc, "workflow_state")
                if estate in ("Pending Farm Manager","Pending HR Head","Pending GM"):
                    editing_pending = 1
            if live and not existing and not editing_pending:
                out["error"] = "This assignment already has an actuals record in progress (" + live[0] + ")."
            else:
                # trusted write path; bypass DocPerms so low-privilege enterers (clerks, section
                # heads, farm managers) can save. Scoped to this action only.
                frappe.flags.ignore_permissions = True
                is_new = 0
                if editing_pending:
                    # approver updates the pending doc in place, KEEPING its workflow_state
                    d = frappe.get_doc("Work Management Actuals", edit_doc)
                    d.set("employees", [])
                elif existing:
                    d = frappe.get_doc("Work Management Actuals", existing[0])
                    d.set("employees", [])
                else:
                    d = frappe.new_doc("Work Management Actuals")
                    d.assignment = assignment
                    is_new = 1
                # enterer may have a User Permission on Employee excluding some workers on this
                # actual; the workflow validator's check_permission("read") would throw. Doc-level
                # flag makes validation skip the caller's row-access enforcement.
                d.flags.ignore_permissions = True
                d.rate = rate
                total_qty = 0
                total_pay = 0
                tw_qty = 0
                sal_qty = 0
                seen_people = {}
                seen_pay_people = {}
                cells = payload.split("|") if payload else []
                for c in cells:
                    if not c:
                        continue
                    bits = c.split("~")
                    if len(bits) < 3:
                        continue
                    emp = bits[0]
                    wdate = bits[1]
                    qty = frappe.utils.flt(bits[2])
                    if qty <= 0:
                        continue
                    etype = frappe.db.get_value("Employee", emp, "employment_type")
                    in_pay = 1 if etype == "Task Worker" else 0
                    amt = (qty * rate) if in_pay else 0
                    row = d.append("employees", {})
                    row.employee = emp
                    row.work_date = wdate
                    row.employment_type = etype
                    row.actual_quantity = qty
                    row.count_in_payroll = in_pay
                    row.amount = amt
                    total_qty = total_qty + qty
                    seen_people[emp] = 1
                    if in_pay:
                        total_pay = total_pay + amt
                        seen_pay_people[emp] = 1
                        tw_qty = tw_qty + qty
                    else:
                        sal_qty = sal_qty + qty
                d.total_actual_qty = total_qty
                d.custom_tw_qty = tw_qty
                d.custom_salaried_qty = sal_qty
                d.actual_people = len(seen_people)
                d.payroll_people = len(seen_pay_people)
                d.total_payment = total_pay
                d.cost_variance = total_pay - frappe.utils.flt(d.planned_cost)
                d.entered_by = frappe.session.user
                d.entry_date = frappe.utils.today()
                # ===== HARD TARGET CAP (budget guard) =====
                # total confirmed/in-progress qty on this plan from OTHER actuals docs + this doc must not exceed plan target
                cap_error = None
                if a_pr:
                    plan_target = frappe.utils.flt(frappe.db.get_value("Work Management Planner", a_pr, "quantity"))
                    if plan_target > 0:
                        this_doc = d.name if not is_new else "__none__"
                        other_done_rows = frappe.db.sql("""
                            SELECT COALESCE(SUM(ac.total_actual_qty),0) q
                            FROM `tabWork Management Actuals` ac
                            INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
                            WHERE a2.planner_request = %s
                              AND ac.workflow_state IN ('Pending HR Head','Pending GM','CONFIRMED')
                              AND ac.name != %s
                        """, (a_pr, this_doc), as_dict=True)
                        other_done = frappe.utils.flt(other_done_rows[0].q) if other_done_rows else 0
                        projected = other_done + total_qty
                        if projected > plan_target:
                            allowed = plan_target - other_done
                            if allowed < 0:
                                allowed = 0
                            cap_error = ("Exceeds plan target. Target is " + str(plan_target) +
                                         ", already recorded elsewhere: " + str(other_done) +
                                         ". This entry (" + str(total_qty) + ") would total " + str(projected) +
                                         ". You can enter at most " + str(allowed) + " more.")
                if cap_error:
                    out["error"] = cap_error
                else:
                    # COMPLETION GATE: submit is only allowed when the plan reaches 100% of target.
                    # Below target -> force Draft and tell the user how much more is needed.
                    completed = 0
                    submit_blocked_msg = None
                    if a_pr:
                        plan_target2 = frappe.utils.flt(frappe.db.get_value("Work Management Planner", a_pr, "quantity"))
                        if plan_target2 > 0:
                            odr = frappe.db.sql("""
                                SELECT COALESCE(SUM(ac.total_actual_qty),0) q
                                FROM `tabWork Management Actuals` ac
                                INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
                                WHERE a2.planner_request = %s
                                  AND ac.workflow_state IN ('Pending HR Head','Pending GM','CONFIRMED')
                                  AND ac.assignment != %s
                            """, (a_pr, assignment), as_dict=True)
                            other_done2 = frappe.utils.flt(odr[0].q) if odr else 0
                            projected2 = other_done2 + total_qty
                            # salaried-only actuals are paid a fixed wage, not qty x rate, so they
                            # are NOT required to finish the target. Allow submit; document the shortfall.
                            salaried_only = (tw_qty <= 0) and (sal_qty > 0)
                            if projected2 >= plan_target2 - 0.0001:
                                completed = 1
                            elif salaried_only:
                                completed = 1
                                d.custom_closed_early = 0
                            else:
                                need2 = plan_target2 - projected2
                                submit_blocked_msg = ("Target not yet completed \\u2014 " + str(projected2) + " of " +
                                                      str(plan_target2) + " done. Enter " + str(need2) +
                                                      " more before submitting. Saved as Draft.")
                            # document the balance vs target on THIS actual (snapshot)
                            d.custom_balance_qty = plan_target2 - projected2
                    if a_pr and not d.get("custom_balance_qty"):
                        d.custom_balance_qty = 0
                    if is_new:
                        d.insert(ignore_permissions=True)
                    elif editing_pending:
                        # keep the current workflow_state (approver edit-in-place)
                        d.save(ignore_permissions=True)
                    else:
                        d.workflow_state = "Draft"
                        d.save(ignore_permissions=True)
                    if submit_now and completed and not editing_pending:
                        # bypass the workflow engine (save() enforces transition roles the
                        # enterer doesn't hold) — write the state directly. Access is gated by
                        # the completion check above.
                        frappe.db.set_value("Work Management Actuals", d.name, "workflow_state", "Pending Farm Manager", update_modified=False)
                        d.workflow_state = "Pending Farm Manager"
                    elif submit_now and not completed and not editing_pending:
                        # keep as Draft; report why submit didn't go through
                        out["submit_blocked"] = submit_blocked_msg or "Target not completed; saved as Draft."
                    out["name"] = d.name
                    out["workflow_state"] = d.workflow_state
                    out["total_payment"] = d.total_payment
                    out["payroll_people"] = d.payroll_people
                    out["actual_people"] = d.actual_people
                    out["total_actual_qty"] = d.total_actual_qty
                    out["tw_qty"] = d.custom_tw_qty
                    out["salaried_qty"] = d.custom_salaried_qty
                    out["balance_qty"] = d.custom_balance_qty
    elif action == "act_my":
        out["actuals"] = frappe.db.get_all("Work Management Actuals",
            filters={"entered_by":frappe.session.user},
            fields=["name","assignment","farm","task","total_actual_qty","actual_people","payroll_people",
                    "total_payment","cost_variance","workflow_state","entry_date"],
            order_by="creation desc", limit=200)

    elif action == "act_pending":
        stage = frappe.form_dict.get("stage") or "Pending HR Head"
        fmflt = {"workflow_state": stage}
        if stage == "Pending Farm Manager":
            fmrl = frappe.db.get_all("Has Role", filters={"parent": frappe.session.user}, pluck="role")
            fmbypass = ("System Manager" in fmrl) or ("General Manager" in fmrl)
            if not fmbypass:
                fmallowed = []
                for _farm_, _role_ in FARM_APPROVER_ROLE.items():
                    if _role_ in fmrl: fmallowed.append(_farm_)
                fmflt["farm"] = ["in", fmallowed] if fmallowed else ["in", ["__none__"]]
        out["pending"] = frappe.db.get_all("Work Management Actuals",
            filters=fmflt,
            fields=["name","assignment","farm","task","block_section","planned_people","actual_people","payroll_people",
                    "planned_cost","total_payment","cost_variance","total_actual_qty","entered_by","entry_date"],
            order_by="entry_date desc", limit=200)

    elif action == "act_fm_approve":
        nm = frappe.form_dict.get("name")
        cur = frappe.db.get_value("Work Management Actuals", nm, ["workflow_state","farm"], as_dict=True)
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
            frappe.db.set_value("Work Management Actuals", nm, "workflow_state", "Pending HR Head", update_modified=False)
            try:
                frappe.db.set_value("Work Management Actuals", nm, "fm_approved_by", frappe.session.user, update_modified=False)
                frappe.db.set_value("Work Management Actuals", nm, "fm_approval_date", frappe.utils.today(), update_modified=False)
            except Exception:
                pass
            out["name"] = nm; out["workflow_state"] = "Pending HR Head"

    elif action == "act_hr_approve":
        nm = frappe.form_dict.get("name")
        cur_ws = frappe.db.get_value("Work Management Actuals", nm, "workflow_state")
        if cur_ws != "Pending HR Head":
            out["error"] = "Not at HR stage (state: " + str(cur_ws) + ")"
        else:
            frappe.db.set_value("Work Management Actuals", nm, "workflow_state", "Pending GM", update_modified=False)
            frappe.db.set_value("Work Management Actuals", nm, "hr_approved_by", frappe.session.user, update_modified=False)
            frappe.db.set_value("Work Management Actuals", nm, "hr_approval_date", frappe.utils.today(), update_modified=False)
            out["name"] = nm; out["workflow_state"] = "Pending GM"

    elif action == "act_gm_approve":
        nm = frappe.form_dict.get("name")
        cur = frappe.db.get_value("Work Management Actuals", nm, ["workflow_state","assignment"], as_dict=True)
        if not cur or cur.workflow_state != "Pending GM":
            out["error"] = "Not at GM stage (state: " + str(cur.workflow_state if cur else "not found") + ")"
        else:
            # move to CONFIRMED (a docstatus=1 workflow state) via direct DB writes, bypassing the
            # get_doc doctype-access gate and the workflow engine. Trusted script; GM stage verified above.
            frappe.db.set_value("Work Management Actuals", nm, "workflow_state", "CONFIRMED", update_modified=False)
            frappe.db.set_value("Work Management Actuals", nm, "docstatus", 1, update_modified=False)
            for kid in frappe.db.get_all("Work Actuals Employee", filters={"parent": nm}, pluck="name"):
                frappe.db.set_value("Work Actuals Employee", kid, "docstatus", 1, update_modified=False)
            frappe.db.set_value("Work Management Actuals", nm, "gm_approved_by", frappe.session.user, update_modified=False)
            frappe.db.set_value("Work Management Actuals", nm, "gm_approval_date", frappe.utils.today(), update_modified=False)
            fulfilled = 0
            remaining = 0
            asg = cur.assignment and frappe.db.get_value("Work Management Assigner", cur.assignment, "planner_request")
            if asg:
                conf = frappe.db.sql("""
                    SELECT COALESCE(SUM(ac.total_actual_qty),0) q
                    FROM `tabWork Management Actuals` ac
                    INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
                    WHERE a2.planner_request = %s AND ac.workflow_state = 'CONFIRMED'
                """, (asg,), as_dict=True)
                fulfilled = frappe.utils.flt(conf[0].q) if conf else 0
                target = frappe.utils.flt(frappe.db.get_value("Work Management Planner", asg, "quantity"))
                remaining = target - fulfilled
                pct = (fulfilled / target * 100) if target > 0 else 0
                over = 1 if fulfilled > target else 0
                frappe.db.set_value("Work Management Planner", asg, "fulfilled_qty", fulfilled, update_modified=False)
                frappe.db.set_value("Work Management Planner", asg, "remaining_qty", remaining, update_modified=False)
                frappe.db.set_value("Work Management Planner", asg, "fulfilment_pct", pct, update_modified=False)
                frappe.db.set_value("Work Management Planner", asg, "over_target", over, update_modified=False)
            # AUTO-RELEASE ON FULL FULFILMENT: when a plan reaches its target, the work is done,
            # so free every still-Active worker on the plan (mark Left, left_date=today) so they
            # can be assigned elsewhere. Confirmed work + pay are untouched. Only runs once: skip
            # if already released or the plan was closed early.
            released_auto = 0
            if asg:
                target_r = frappe.utils.flt(frappe.db.get_value("Work Management Planner", asg, "quantity"))
                cstate_r = frappe.db.get_value("Work Management Planner", asg, "custom_close_state") or ""
                if target_r > 0 and fulfilled >= (target_r - 0.0001) and cstate_r != "Closed":
                    today_r = frappe.utils.today()
                    free_r = frappe.db.sql("""
                        SELECT we.name row_id
                        FROM `tabWork Assignment Employee` we
                        INNER JOIN `tabWork Management Assigner` a2 ON we.parent = a2.name
                        WHERE a2.planner_request = %s AND IFNULL(we.status,'Active') = 'Active'
                    """, (asg,), as_dict=True)
                    for fr in free_r:
                        frappe.db.set_value("Work Assignment Employee", fr.row_id, "status", "Left", update_modified=False)
                        frappe.db.set_value("Work Assignment Employee", fr.row_id, "left_date", today_r, update_modified=False)
                        released_auto = released_auto + 1
                    # mark the plan complete so it drops out of the pickers (target kept)
                    frappe.db.set_value("Work Management Planner", asg, "custom_close_state", "Completed", update_modified=False)
            out["name"] = nm
            out["workflow_state"] = "CONFIRMED"
            out["fulfilled_qty"] = fulfilled
            out["remaining_qty"] = remaining
            out["workers_released"] = released_auto

    elif action == "act_reject":
        nm = frappe.form_dict.get("name")
        cur = frappe.db.get_value("Work Management Actuals", nm, ["workflow_state","docstatus","assignment"], as_dict=True)
        if not cur or cur.workflow_state not in ("Pending Farm Manager","Pending HR Head","Pending GM","CONFIRMED"):
            out["error"] = "Not rejectable (state: " + str(cur.workflow_state if cur else "not found") + ")"
        else:
            # if submitted, "cancel" it by flipping docstatus to 2 (Cancelled) directly, then mark Rejected.
            if cur.docstatus == 1:
                frappe.db.set_value("Work Management Actuals", nm, "docstatus", 2, update_modified=False)
                for kid in frappe.db.get_all("Work Actuals Employee", filters={"parent": nm}, pluck="name"):
                    frappe.db.set_value("Work Actuals Employee", kid, "docstatus", 2, update_modified=False)
            frappe.db.set_value("Work Management Actuals", nm, "workflow_state", "Rejected", update_modified=False)
            asg = cur.assignment and frappe.db.get_value("Work Management Assigner", cur.assignment, "planner_request")
            if asg:
                conf = frappe.db.sql("""
                    SELECT COALESCE(SUM(ac.total_actual_qty),0) q
                    FROM `tabWork Management Actuals` ac
                    INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
                    WHERE a2.planner_request = %s AND ac.workflow_state = 'CONFIRMED'
                """, (asg,), as_dict=True)
                fulfilled = frappe.utils.flt(conf[0].q) if conf else 0
                target = frappe.utils.flt(frappe.db.get_value("Work Management Planner", asg, "quantity"))
                remaining = target - fulfilled
                pct = (fulfilled / target * 100) if target > 0 else 0
                over = 1 if fulfilled > target else 0
                frappe.db.set_value("Work Management Planner", asg, "fulfilled_qty", fulfilled, update_modified=False)
                frappe.db.set_value("Work Management Planner", asg, "remaining_qty", remaining, update_modified=False)
                frappe.db.set_value("Work Management Planner", asg, "fulfilment_pct", pct, update_modified=False)
                frappe.db.set_value("Work Management Planner", asg, "over_target", over, update_modified=False)
            out["name"] = nm
            out["workflow_state"] = "Rejected"

    # ===== PAYMENT (pay_) =====
    elif action == "act_close_roles":
        plan = frappe.form_dict.get("plan")
        assignment = frappe.form_dict.get("assignment")
        if not plan and assignment:
            plan = frappe.db.get_value("Work Management Assigner", assignment, "planner_request")
        crl = frappe.db.get_all("Has Role", filters={"parent": frappe.session.user}, pluck="role")
        is_gm = ("General Manager" in crl) or ("System Manager" in crl)
        is_requester = False
        for r in crl:
            if r.startswith("Farm Manager") or r == "Production Section Head":
                is_requester = True
        out["user"] = frappe.session.user
        out["is_gm"] = 1 if is_gm else 0
        out["can_request"] = 1 if is_requester else 0
        out["can_close_now"] = 1 if is_gm else 0
        if plan:
            cs = frappe.db.get_value("Work Management Planner", plan,
                ["custom_close_state", "custom_close_requested_by", "custom_close_request_date",
                 "custom_closed_by", "custom_closed_date", "custom_close_reason",
                 "fulfilled_qty", "quantity", "remaining_qty"], as_dict=True)
            out["plan"] = plan
            out["close_state"] = (cs.custom_close_state if cs else "") or ""
            out["close_requested_by"] = cs.custom_close_requested_by if cs else None
            out["closed_by"] = cs.custom_closed_by if cs else None
            out["close_reason"] = cs.custom_close_reason if cs else None
            out["fulfilled_qty"] = frappe.utils.flt(cs.fulfilled_qty) if cs else 0
            out["target_qty"] = frappe.utils.flt(cs.quantity) if cs else 0
        else:
            out["plan"] = None
            out["close_state"] = ""


    # ---------------------------------------------------------------------
    # ACTION: act_close_request  (POST) — FM / Section head asks GM to close
    # params: plan (or assignment), reason
    # ---------------------------------------------------------------------
    elif action == "act_close_request":
        plan = frappe.form_dict.get("plan")
        assignment = frappe.form_dict.get("assignment")
        reason = (frappe.form_dict.get("reason") or "").strip()
        if not plan and assignment:
            plan = frappe.db.get_value("Work Management Assigner", assignment, "planner_request")
        crl = frappe.db.get_all("Has Role", filters={"parent": frappe.session.user}, pluck="role")
        is_gm = ("General Manager" in crl) or ("System Manager" in crl)
        is_requester = False
        for r in crl:
            if r.startswith("Farm Manager") or r == "Production Section Head":
                is_requester = True
        err = None
        if not plan:
            err = "No plan resolved for this close request"
        if not reason:
            err = "A reason is required to request a close"
        if not err and not (is_requester or is_gm):
            err = "You are not allowed to request a close (need Farm Manager or Section Head)"
        if not err:
            cstate = frappe.db.get_value("Work Management Planner", plan, "custom_close_state") or ""
            if cstate == "Closed":
                err = "This plan is already closed"
            elif cstate == "Close Requested":
                err = "A close request is already pending GM approval"
        if err:
            out["error"] = err
        else:
            frappe.db.set_value("Work Management Planner", plan, "custom_close_state", "Close Requested", update_modified=False)
            frappe.db.set_value("Work Management Planner", plan, "custom_close_requested_by", frappe.session.user, update_modified=False)
            frappe.db.set_value("Work Management Planner", plan, "custom_close_request_date", frappe.utils.today(), update_modified=False)
            frappe.db.set_value("Work Management Planner", plan, "custom_close_reason", reason, update_modified=False)
            frappe.db.commit()
            out["plan"] = plan
            out["close_state"] = "Close Requested"


    # ---------------------------------------------------------------------
    # ACTION: act_close_pending  (GET) — GM's queue of plans awaiting close approval
    # ---------------------------------------------------------------------
    elif action == "act_close_pending":
        crl = frappe.db.get_all("Has Role", filters={"parent": frappe.session.user}, pluck="role")
        is_gm = ("General Manager" in crl) or ("System Manager" in crl)
        if not is_gm:
            out["pending"] = []
            out["not_gm"] = 1
        else:
            rows = frappe.db.get_all("Work Management Planner",
                filters={"custom_close_state": "Close Requested"},
                fields=["name", "farm", "block_section", "task", "quantity", "fulfilled_qty",
                        "remaining_qty", "uom", "custom_close_requested_by", "custom_close_request_date",
                        "custom_close_reason"],
                order_by="custom_close_request_date desc", limit=200)
            out["pending"] = rows


    # ---------------------------------------------------------------------
    # ACTION: act_close_confirm  (POST) — GM closes (instant, or approving a request)
    # params: plan (or assignment), reason (required if none stored yet)
    # Finalises any open Draft/Rejected actuals on the plan to Confirmed,
    # then marks the plan Closed. Target qty is KEPT; fulfilled/remaining refreshed.
    # ---------------------------------------------------------------------
    elif action == "act_close_confirm":
        plan = frappe.form_dict.get("plan")
        assignment = frappe.form_dict.get("assignment")
        reason = (frappe.form_dict.get("reason") or "").strip()
        if not plan and assignment:
            plan = frappe.db.get_value("Work Management Assigner", assignment, "planner_request")
        crl = frappe.db.get_all("Has Role", filters={"parent": frappe.session.user}, pluck="role")
        is_gm = ("General Manager" in crl) or ("System Manager" in crl)
        err = None
        if not plan:
            err = "No plan resolved for this close"
        if not err and not is_gm:
            err = "Only the General Manager can confirm a close"
        stored_reason = None
        if not err:
            cstate = frappe.db.get_value("Work Management Planner", plan, "custom_close_state") or ""
            stored_reason = frappe.db.get_value("Work Management Planner", plan, "custom_close_reason")
            if cstate == "Closed":
                err = "This plan is already closed"
        # reason: use the one supplied now, else the one stored on a pending request
        use_reason = reason or (stored_reason or "")
        if not err and not use_reason:
            err = "A reason is required to close"
        if err:
            out["error"] = err
        else:
            # 1) finalise any OPEN (Draft/Rejected) actuals on this plan's assignments to Confirmed.
            #    We only touch docs that actually have quantity; empty drafts are left alone.
            open_acts = frappe.db.sql("""
                SELECT ac.name nm, ac.total_actual_qty q, ac.docstatus ds, ac.workflow_state ws
                FROM `tabWork Management Actuals` ac
                INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
                WHERE a2.planner_request = %s
                  AND (
                        ac.workflow_state IN ('Draft','Rejected','Pending Farm Manager','Pending HR Head','Pending GM')
                        OR (ac.workflow_state = 'CONFIRMED' AND ac.docstatus = 0)
                      )
            """, (plan,), as_dict=True)
            finalised = 0
            for ar in open_acts:
                if frappe.utils.flt(ar.q) <= 0:
                    continue
                # The doctype has a Workflow that only allows Pending GM -> CONFIRMED. There is NO
                # Draft/Rejected/Pending* -> CONFIRMED transition, so doc.save() with a CONFIRMED state
                # raises WorkflowPermissionError. A close is an explicit GM override, so we set the
                # final state + docstatus DIRECTLY at the DB level, bypassing the workflow engine.
                # This also confirms below-target work (the whole point of an early close).
                frappe.db.set_value("Work Management Actuals", ar.nm, "workflow_state", "CONFIRMED", update_modified=False)
                frappe.db.set_value("Work Management Actuals", ar.nm, "docstatus", 1, update_modified=False)
                # child rows must carry the same docstatus as the parent submitted doc
                for kid in frappe.db.get_all("Work Actuals Employee", filters={"parent": ar.nm}, pluck="name"):
                    frappe.db.set_value("Work Actuals Employee", kid, "docstatus", 1, update_modified=False)
                try:
                    frappe.db.set_value("Work Management Actuals", ar.nm, "gm_approved_by", frappe.session.user, update_modified=False)
                    frappe.db.set_value("Work Management Actuals", ar.nm, "gm_approval_date", frappe.utils.today(), update_modified=False)
                    frappe.db.set_value("Work Management Actuals", ar.nm, "custom_closed_early", 1, update_modified=False)
                    frappe.db.set_value("Work Management Actuals", ar.nm, "custom_close_reason", use_reason, update_modified=False)
                except Exception:
                    pass
                finalised = finalised + 1
            # 2) recompute fulfilled/remaining from CONFIRMED actuals (target kept as-is)
            conf = frappe.db.sql("""
                SELECT COALESCE(SUM(ac.total_actual_qty),0) q
                FROM `tabWork Management Actuals` ac
                INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
                WHERE a2.planner_request = %s AND ac.workflow_state = 'CONFIRMED'
            """, (plan,), as_dict=True)
            fulfilled = frappe.utils.flt(conf[0].q) if conf else 0
            target = frappe.utils.flt(frappe.db.get_value("Work Management Planner", plan, "quantity"))
            remaining = target - fulfilled
            pct = (fulfilled / target * 100) if target > 0 else 0
            over = 1 if (target > 0 and fulfilled > target) else 0
            frappe.db.set_value("Work Management Planner", plan, "fulfilled_qty", fulfilled, update_modified=False)
            frappe.db.set_value("Work Management Planner", plan, "remaining_qty", remaining, update_modified=False)
            frappe.db.set_value("Work Management Planner", plan, "fulfilment_pct", pct, update_modified=False)
            frappe.db.set_value("Work Management Planner", plan, "over_target", over, update_modified=False)
            # 3) mark the plan Closed (target KEPT; workflow_state untouched at Approved)
            frappe.db.set_value("Work Management Planner", plan, "custom_close_state", "Closed", update_modified=False)
            frappe.db.set_value("Work Management Planner", plan, "custom_closed_by", frappe.session.user, update_modified=False)
            frappe.db.set_value("Work Management Planner", plan, "custom_closed_date", frappe.utils.today(), update_modified=False)
            # roll up delivered split + balance onto the plan (documentation)
            split_rows = frappe.db.sql("""
                SELECT COALESCE(SUM(ac.custom_tw_qty),0) tw,
                       COALESCE(SUM(ac.custom_salaried_qty),0) sal
                FROM `tabWork Management Actuals` ac
                INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
                WHERE a2.planner_request = %s
                  AND ac.workflow_state = 'CONFIRMED'
            """, (plan,), as_dict=True)
            tw_tot = frappe.utils.flt(split_rows[0].tw) if split_rows else 0
            sal_tot = frappe.utils.flt(split_rows[0].sal) if split_rows else 0
            frappe.db.set_value("Work Management Planner", plan, "custom_tw_qty", tw_tot, update_modified=False)
            frappe.db.set_value("Work Management Planner", plan, "custom_salaried_qty", sal_tot, update_modified=False)
            frappe.db.set_value("Work Management Planner", plan, "custom_balance_qty", target - (tw_tot + sal_tot), update_modified=False)
            if reason:
                frappe.db.set_value("Work Management Planner", plan, "custom_close_reason", use_reason, update_modified=False)
            # 4) release workers: mark every still-Active worker on this plan's assignments
            #    as Left (left_date = today) so they are free for other tasks. Recorded
            #    work + pay is untouched; busy/overlap checks treat 'Left' as free.
            released = 0
            close_day = frappe.utils.today()
            freerows = frappe.db.sql("""
                SELECT we.name row_id
                FROM `tabWork Assignment Employee` we
                INNER JOIN `tabWork Management Assigner` a2 ON we.parent = a2.name
                WHERE a2.planner_request = %s
                  AND IFNULL(we.status,'Active') = 'Active'
            """, (plan,), as_dict=True)
            for fr in freerows:
                frappe.db.set_value("Work Assignment Employee", fr.row_id, "status", "Left", update_modified=False)
                frappe.db.set_value("Work Assignment Employee", fr.row_id, "left_date", close_day, update_modified=False)
                released = released + 1
            frappe.db.commit()
            out["plan"] = plan
            out["close_state"] = "Closed"
            out["finalised_actuals"] = finalised
            out["workers_released"] = released
            out["fulfilled_qty"] = fulfilled
            out["remaining_qty"] = remaining
            out["target_qty"] = target

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
