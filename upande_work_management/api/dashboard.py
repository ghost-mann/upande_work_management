# Ported from Kaitet live Server Script "wm_dashboard" (API) — logic unchanged.
# Farms / projects / company / approver roles now come from Work Management Settings
# (falls back to the original Kaitet defaults) — see upande_work_management/api/config.py.

import frappe

from upande_work_management.api.config import get_config


@frappe.whitelist()
def wm_dashboard(**kwargs):
    _cfg = get_config()
    FARM_PROJECT = _cfg["farm_project"]
    DEFAULT_COMPANY = _cfg["default_company"]
    FARMS = _cfg["farms"]
    BLOCK_EXCLUDE = _cfg["block_exclude"]
    FARM_APPROVER_ROLE = _cfg["farm_approver_role"]

    # ==================================================================
    # SERVER SCRIPT — "WM Dashboard" (API, api_method=wm_dashboard)
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
    if action == "pipeline":
        # Full-visibility pipeline lists across all four stages, each with rich metadata.
        # Filters (all optional): farm, state, task, block, from_date, to_date, q (free-text on name/task/block)
        ffarm = frappe.form_dict.get("farm")
        fstate = frappe.form_dict.get("state")
        ftask = frappe.form_dict.get("task")
        fblock = frappe.form_dict.get("block")
        fdfrom = frappe.form_dict.get("from_date")
        fdto = frappe.form_dict.get("to_date")
        fq = (frappe.form_dict.get("q") or "").strip().lower()
        stage = frappe.form_dict.get("pstage") or "plans"

        def safe_get_all(dtype, want_fields, order, lim):
            # try the full field list; if a field is invalid, retry with only fields that exist on the doctype
            try:
                return frappe.db.get_all(dtype, fields=want_fields, order_by=order, limit=lim)
            except Exception:
                meta = frappe.get_meta(dtype)
                valid = ["name","creation","modified","owner"]
                for f in meta.fields:
                    valid.append(f.fieldname)
                keep = []
                for f in want_fields:
                    if f in valid:
                        keep.append(f)
                if "name" not in keep:
                    keep.append("name")
                return frappe.db.get_all(dtype, fields=keep, order_by=order, limit=lim)

        rows_out = []
        if stage == "plans":
            recs = safe_get_all("Work Management Planner",
                ["name","farm","block_section","task","quantity","uom","people_per_day","person_days",
                 "total_cost","from_date","to_date","workflow_state","requested_by","request_date",
                 "approved_by","approval_date","creation","custom_close_state"], "creation desc", 1000)
            for r in recs:
                if ffarm and r.get("farm") != ffarm:
                    continue
                if fstate and r.get("workflow_state") != fstate:
                    continue
                if ftask and ftask.lower() not in (r.get("task") or "").lower():
                    continue
                if fblock and fblock.lower() not in (r.get("block_section") or "").lower():
                    continue
                if fq:
                    hay = ((r.get("name") or "") + " " + (r.get("task") or "") + " " + (r.get("block_section") or "")).lower()
                    if fq not in hay:
                        continue
                if fdfrom and r.get("to_date") and str(r.get("to_date")) < str(fdfrom):
                    continue
                if fdto and r.get("from_date") and str(r.get("from_date")) > str(fdto):
                    continue
                rows_out.append(r)
        elif stage == "assignments":
            recs = safe_get_all("Work Management Assigner",
                ["name","planner_request","farm","block_section","task","planned_people","assigned_count",
                 "variance","planned_cost","from_date","to_date","workflow_state","assigned_by","assign_date",
                 "approved_by","approval_date","creation"], "creation desc", 1000)
            for r in recs:
                if ffarm and r.get("farm") != ffarm:
                    continue
                if fstate and r.get("workflow_state") != fstate:
                    continue
                if ftask and ftask.lower() not in (r.get("task") or "").lower():
                    continue
                if fblock and fblock.lower() not in (r.get("block_section") or "").lower():
                    continue
                if fq:
                    hay = ((r.get("name") or "") + " " + (r.get("task") or "") + " " + (r.get("block_section") or "")).lower()
                    if fq not in hay:
                        continue
                if fdfrom and r.get("to_date") and str(r.get("to_date")) < str(fdfrom):
                    continue
                if fdto and r.get("from_date") and str(r.get("from_date")) > str(fdto):
                    continue
                rows_out.append(r)
        elif stage == "actuals":
            recs = safe_get_all("Work Management Actuals",
                ["name","assignment","farm","block_section","task","total_actual_qty","actual_people",
                 "payroll_people","total_payment","workflow_state","entered_by","entry_date","creation"], "creation desc", 1000)
            for r in recs:
                if ffarm and r.get("farm") != ffarm:
                    continue
                if fstate and r.get("workflow_state") != fstate:
                    continue
                if ftask and ftask.lower() not in (r.get("task") or "").lower():
                    continue
                if fblock and fblock.lower() not in (r.get("block_section") or "").lower():
                    continue
                if fq:
                    hay = ((r.get("name") or "") + " " + (r.get("task") or "") + " " + (r.get("block_section") or "")).lower()
                    if fq not in hay:
                        continue
                rows_out.append(r)
        elif stage == "payments":
            recs = safe_get_all("Work Management Payment",
                ["name","run_title","workflow_state","period_from","period_to","grand_total","total_workers","creation"], "creation desc", 1000)
            for r in recs:
                if fstate and r.get("workflow_state") != fstate:
                    continue
                if fq and fq not in (r.get("name") or "").lower():
                    continue
                if fdfrom and r.get("period_to") and str(r.get("period_to")) < str(fdfrom):
                    continue
                if fdto and r.get("period_from") and str(r.get("period_from")) > str(fdto):
                    continue
                rows_out.append(r)
        # attach Standard (daily_target + uom) per row from the Task doctype, cached
        stdcache = {}
        uomcache = {}
        for r in rows_out:
            tk = r.get("task")
            if tk and tk not in stdcache:
                tinfo = frappe.db.get_value("Task", tk, ["custom_daily_target", "custom_uom"], as_dict=True)
                stdcache[tk] = frappe.utils.flt(tinfo.custom_daily_target) if tinfo else 0
                uomcache[tk] = (tinfo.custom_uom if tinfo else "") or ""
            r["std"] = stdcache.get(tk, 0)
            r["std_uom"] = uomcache.get(tk, "")
        # LIFECYCLE STATUS (plans stage only): furthest stage reached across the pipeline.
        # paid > done(confirmed) > assigned > planned; Closed shown distinctly.
        if stage == "plans":
            pnames = []
            for r in rows_out:
                if r.get("name"):
                    pnames.append(r.get("name"))
            has_asg = {}
            has_conf = {}
            has_paid = {}
            if pnames:
                # live assignment exists for the plan
                for row in frappe.db.sql("""
                    SELECT DISTINCT planner_request pr
                    FROM `tabWork Management Assigner`
                    WHERE workflow_state IN ('Pending Farm Manager','Pending HR Head','Pending GM','Assigned')
                      AND planner_request IN %(pl)s
                """, {"pl": tuple(pnames)}, as_dict=True):
                    has_asg[row.pr] = 1
                # confirmed actuals exist for the plan
                for row in frappe.db.sql("""
                    SELECT DISTINCT a2.planner_request pr
                    FROM `tabWork Management Actuals` ac
                    INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
                    WHERE ac.workflow_state = 'CONFIRMED'
                      AND a2.planner_request IN %(pl)s
                """, {"pl": tuple(pnames)}, as_dict=True):
                    has_conf[row.pr] = 1
                # any paid worker-row on a confirmed actual for the plan
                for row in frappe.db.sql("""
                    SELECT DISTINCT a2.planner_request pr
                    FROM `tabWork Actuals Employee` we
                    INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
                    INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
                    WHERE ac.workflow_state = 'CONFIRMED'
                      AND IFNULL(we.paid,0) = 1
                      AND a2.planner_request IN %(pl)s
                """, {"pl": tuple(pnames)}, as_dict=True):
                    has_paid[row.pr] = 1
            for r in rows_out:
                nm = r.get("name")
                stt = "planned"
                if has_paid.get(nm):
                    stt = "paid"
                elif has_conf.get(nm):
                    stt = "done"
                elif has_asg.get(nm):
                    stt = "assigned"
                r["life_status"] = stt
                r["is_closed"] = 1 if (r.get("custom_close_state") in ("Closed","Completed")) else 0
        out["rows"] = rows_out
        out["stage"] = stage
        # distinct filter options for the UI
        out["farms"] = FARMS

    elif action == "plan_lineage":
        # Full lineage for ONE plan: header + assignments (+ workers) + actuals (+ daily) + payments
        def lin_get(dtype, filt, want_fields, order, lim):
            try:
                return frappe.db.get_all(dtype, filters=filt, fields=want_fields, order_by=order, limit=lim)
            except Exception:
                meta = frappe.get_meta(dtype)
                valid = ["name","creation","modified","owner","parent","parentfield","parenttype","idx"]
                for f in meta.fields:
                    valid.append(f.fieldname)
                keep = []
                for f in want_fields:
                    if f in valid:
                        keep.append(f)
                if "name" not in keep:
                    keep.append("name")
                try:
                    return frappe.db.get_all(dtype, filters=filt, fields=keep, order_by=order, limit=lim)
                except Exception:
                    return frappe.db.get_all(dtype, filters=filt, fields=["name"], order_by=order, limit=lim)
        pname = frappe.form_dict.get("plan")
        p = frappe.db.get_value("Work Management Planner", pname,
            ["name","farm","block_section","task","task_kpi","quantity","uom","people_per_day","person_days",
             "total_cost","from_date","to_date","workflow_state","requested_by","request_date",
             "approved_by","approval_date","creation","rate","daily_target","working_days"], as_dict=True)
        out["plan"] = p or {}
        # quantity done vs remaining: sum CONFIRMED actual qty across all assignments on this plan
        done_qty = 0
        if p:
            dq = frappe.db.sql("""
                SELECT COALESCE(SUM(ac.total_actual_qty),0) q
                FROM `tabWork Management Actuals` ac
                INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
                WHERE a2.planner_request = %s AND ac.workflow_state = 'CONFIRMED'
            """, (pname,), as_dict=True)
            done_qty = frappe.utils.flt(dq[0].q) if dq else 0
            # also pending (in-approval) qty, shown separately
            pq = frappe.db.sql("""
                SELECT COALESCE(SUM(ac.total_actual_qty),0) q
                FROM `tabWork Management Actuals` ac
                INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
                WHERE a2.planner_request = %s AND ac.workflow_state IN ('Pending Farm Manager','Pending HR Head','Pending GM')
            """, (pname,), as_dict=True)
            out["plan"]["pending_qty"] = frappe.utils.flt(pq[0].q) if pq else 0
        tgt = frappe.utils.flt(p.get("quantity")) if p else 0
        out["plan"]["done_qty"] = done_qty
        rem = tgt - done_qty
        out["plan"]["remaining_qty"] = rem if rem > 0 else 0
        out["plan"]["over_qty"] = (done_qty - tgt) if done_qty > tgt else 0
        out["plan"]["is_complete"] = 1 if (tgt > 0 and done_qty >= tgt) else 0
        # ===== cost reconciliation: planned vs task-worker paid vs salaried-covered =====
        # payment only pays task-worker output (qty x rate); salaried output is delivered at
        # zero piece-rate cost. This makes an underspend legible as "salaried covered it".
        prate = frappe.utils.flt(p.get("rate")) if p else 0
        split = frappe.db.sql("""
            SELECT COALESCE(SUM(ac.custom_tw_qty),0) tw,
                   COALESCE(SUM(ac.custom_salaried_qty),0) sal
            FROM `tabWork Management Actuals` ac
            INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
            WHERE a2.planner_request = %s AND ac.workflow_state = 'CONFIRMED'
        """, (pname,), as_dict=True)
        tw_done = frappe.utils.flt(split[0].tw) if split else 0
        sal_done = frappe.utils.flt(split[0].sal) if split else 0
        bal_qty = tgt - (tw_done + sal_done)
        if bal_qty < 0:
            bal_qty = 0
        out["plan"]["tw_qty"] = tw_done
        out["plan"]["salaried_qty"] = sal_done
        out["plan"]["planned_value"] = tgt * prate
        out["plan"]["tw_paid_value"] = tw_done * prate
        out["plan"]["salaried_value"] = sal_done * prate
        out["plan"]["balance_value"] = bal_qty * prate
        out["plan"]["balance_qty"] = bal_qty
        # assignments tied to this plan
        asgs = lin_get("Work Management Assigner", {"planner_request": pname},
            ["name","farm","block_section","task","planned_people","assigned_count","variance",
             "planned_cost","from_date","to_date","workflow_state","assigned_by","assign_date",
             "fm_approved_by","hr_approved_by","gm_approved_by","approved_by","approval_date","creation"],
            "creation desc", 200)
        for a in asgs:
            # workers on this assignment
            a["workers"] = lin_get("Work Assignment Employee", {"parent": a.name},
                ["employee","employee_name","status","start_date","left_date"], "idx", 500)
            # actuals for this assignment
            acts = lin_get("Work Management Actuals", {"assignment": a.name},
                ["name","total_actual_qty","actual_people","payroll_people","total_payment",
                 "workflow_state","entered_by","entry_date","fm_approved_by","hr_approved_by",
                 "gm_approved_by","creation"], "creation desc", 200)
            for ac in acts:
                # daily entries from the child table (best-effort field set)
                ac["daily"] = lin_get("Work Actuals Employee", {"parent": ac.name},
                    ["employee","employee_name","employment_type","work_date","actual_quantity","amount","count_in_payroll","paid","payment_ref"],
                    "work_date", 1000)
            a["actuals"] = acts
        out["assignments"] = asgs
        # payments that include any actuals from this plan (via period + farm best-effort) — list all, UI notes linkage
        out["payments"] = lin_get("Work Management Payment", {},
            ["name","workflow_state","period_from","period_to","grand_total","creation"], "creation desc", 50)

    elif action == "actual_detail":
        aname = frappe.form_dict.get("actual")
        # field-tolerant header: only request fields that exist on the doctype (approval fields are optional)
        ac_meta = frappe.get_meta("Work Management Actuals")
        ac_valid = ["name","creation","modified","owner"]
        for f in ac_meta.fields:
            ac_valid.append(f.fieldname)
        ac_want = ["name","assignment","farm","block_section","task","total_actual_qty","actual_people",
                   "payroll_people","total_payment","workflow_state","entered_by","entry_date",
                   "fm_approved_by","hr_approved_by","gm_approved_by","fm_approval_date","hr_approval_date","gm_approval_date","creation"]
        ac_fields = []
        for f in ac_want:
            if f in ac_valid:
                ac_fields.append(f)
        if "name" not in ac_fields:
            ac_fields.append("name")
        ac = frappe.db.get_value("Work Management Actuals", aname, ac_fields, as_dict=True)
        out["actual"] = ac or {}
        plan_ref = None
        if ac and ac.get("assignment"):
            plan_ref = frappe.db.get_value("Work Management Assigner", ac.get("assignment"), "planner_request")
        out["plan_ref"] = plan_ref
        out["assignment_ref"] = ac.get("assignment") if ac else None
        # daily entries — field-tolerant
        de_meta = frappe.get_meta("Work Actuals Employee")
        de_valid = ["name","parent"]
        for f in de_meta.fields:
            de_valid.append(f.fieldname)
        de_want = ["employee","employee_name","employment_type","work_date","actual_quantity","amount","count_in_payroll","paid","payment_ref"]
        de_fields = []
        for f in de_want:
            if f in de_valid:
                de_fields.append(f)
        if "name" not in de_fields:
            de_fields.append("name")
        out["daily"] = frappe.db.get_all("Work Actuals Employee", filters={"parent": aname}, fields=de_fields, order_by="work_date", limit=1000)

    elif action == "payment_detail":
        pmname = frappe.form_dict.get("payment")
        pm_meta = frappe.get_meta("Work Management Payment")
        pm_valid = ["name","creation","modified","owner"]
        for f in pm_meta.fields:
            pm_valid.append(f.fieldname)
        pm_want = ["name","run_title","workflow_state","company","run_date","period_from","period_to",
                   "total_actuals","total_workers","grand_total","prepared_by","accounts_approved_by",
                   "accounts_approval_date","creation"]
        pm_fields = []
        for f in pm_want:
            if f in pm_valid:
                pm_fields.append(f)
        if "name" not in pm_fields:
            pm_fields.append("name")
        pm = frappe.db.get_value("Work Management Payment", pmname, pm_fields, as_dict=True)
        out["payment"] = pm or {}
        pl_meta = frappe.get_meta("Work Payment Line")
        pl_valid = ["name","parent"]
        for f in pl_meta.fields:
            pl_valid.append(f.fieldname)
        pl_want = ["actuals","employee","employee_name","farm","task","days","qty","paid_workers","amount"]
        pl_fields = []
        for f in pl_want:
            if f in pl_valid:
                pl_fields.append(f)
        if "name" not in pl_fields:
            pl_fields.append("name")
        out["lines"] = frappe.db.get_all("Work Payment Line", filters={"parent": pmname}, fields=pl_fields, order_by="idx", limit=2000)

    elif action == "cost_breakdown":
        # Estimated vs paid-out cost, grouped by activity (task), worker, or farm.
        # Filters (optional): farm, task, from_date, to_date, q. group = task|worker|farm
        cbfarm = frappe.form_dict.get("farm")
        cbtask = frappe.form_dict.get("task")
        cbfrom = frappe.form_dict.get("from_date")
        cbto = frappe.form_dict.get("to_date")
        cbq = (frappe.form_dict.get("q") or "").strip().lower()
        cbgroup = frappe.form_dict.get("group") or "task"

        # Pull confirmed-actuals worker rows joined to their actuals+farm/task, with per-row amount and paid flag.
        # We filter by farm/task/date at SQL where possible; python does the grouping and text search.
        conds = ["ac.workflow_state = 'CONFIRMED'"]
        params = []
        if cbfarm:
            conds.append("ac.farm = %s"); params.append(cbfarm)
        if cbtask:
            conds.append("ac.task LIKE %s"); params.append("%" + cbtask + "%")
        if cbfrom:
            conds.append("we.work_date >= %s"); params.append(cbfrom)
        if cbto:
            conds.append("we.work_date <= %s"); params.append(cbto)
        where = " AND ".join(conds)
        rows = frappe.db.sql("SELECT ac.farm farm, ac.task task, we.employee employee, we.employee_name employee_name, COALESCE(we.amount,0) amount, IFNULL(we.paid,0) paid, COALESCE(we.actual_quantity,0) qty FROM `tabWork Actuals Employee` we INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name WHERE " + where + " LIMIT 20000", tuple(params), as_dict=True)

        # group in python
        groups = {}
        tot_est = 0
        tot_paid = 0
        for r in rows:
            if cbgroup == "worker":
                key = r.employee_name or r.employee or "?"
            elif cbgroup == "farm":
                key = r.farm or "?"
            else:
                key = r.task or "?"
            if cbq and cbq not in str(key).lower():
                continue
            g = groups.get(key)
            if not g:
                g = {"key": key, "estimated": 0, "paid": 0, "qty": 0, "workers": {}, "rows": 0}
                groups[key] = g
            amt = frappe.utils.flt(r.amount)
            g["estimated"] = g["estimated"] + amt
            if frappe.utils.cint(r.paid) == 1:
                g["paid"] = g["paid"] + amt
            g["qty"] = g["qty"] + frappe.utils.flt(r.qty)
            g["rows"] = g["rows"] + 1
            if r.employee:
                g["workers"][r.employee] = 1
            tot_est = tot_est + amt
            if frappe.utils.cint(r.paid) == 1:
                tot_paid = tot_paid + amt

        out_rows = []
        for k in groups:
            g = groups[k]
            g["worker_count"] = len(g["workers"])
            g["outstanding"] = g["estimated"] - g["paid"]
            del g["workers"]
            out_rows.append(g)
        # sort by estimated desc
        out_rows = sorted(out_rows, key=lambda x: x["estimated"], reverse=True)
        out["breakdown"] = out_rows
        out["group"] = cbgroup
        out["totals"] = {"estimated": tot_est, "paid": tot_paid, "outstanding": tot_est - tot_paid}
        out["farms"] = FARMS

    elif action == "emp_tracker":
        # Employee & assignment tracker: search a worker, see all their assignments (task/farm/block/period/state)
        # and optionally their actuals (days worked, qty, pay). Filters: q (name/id), farm, state, task, from_date, to_date.
        etq = (frappe.form_dict.get("q") or "").strip()
        etfarm = frappe.form_dict.get("farm")
        etstate = frappe.form_dict.get("state")
        ettask = frappe.form_dict.get("task")
        etfrom = frappe.form_dict.get("from_date")
        etto = frappe.form_dict.get("to_date")

        # 1) resolve matching employees (by name or id). If no search term, list workers who have assignments.
        emp_rows = []
        if etq:
            emp_rows = frappe.db.get_all("Employee",
                or_filters=[["employee_name", "like", "%" + etq + "%"], ["name", "like", "%" + etq + "%"]],
                fields=["name", "employee_name", "custom_farm", "custom_business_unit", "designation", "employment_type", "status"],
                order_by="employee_name", limit=50)
        out["employees"] = emp_rows

        # 2) build assignment rows. If a specific employee search matched, scope to those; else show recent assignment-workers.
        emp_names = []
        for e in emp_rows:
            emp_names.append(e.name)

        weconds = []
        params = []
        if emp_names:
            placeholders = ", ".join(["%s"] * len(emp_names))
            weconds.append("we.employee IN (" + placeholders + ")")
            params = params + emp_names
        if etfarm:
            weconds.append("a.farm = %s"); params.append(etfarm)
        if etstate:
            weconds.append("a.workflow_state = %s"); params.append(etstate)
        if ettask:
            weconds.append("a.task LIKE %s"); params.append("%" + ettask + "%")
        if etfrom:
            weconds.append("a.to_date >= %s"); params.append(etfrom)
        if etto:
            weconds.append("a.from_date <= %s"); params.append(etto)
        wewhere = " AND ".join(weconds) if weconds else "1=1"

        rows = frappe.db.sql("SELECT we.employee employee, we.employee_name employee_name, we.status wstatus, we.start_date start_date, we.left_date left_date, a.name assignment, a.farm farm, a.task task, a.block_section block_section, a.from_date from_date, a.to_date to_date, a.workflow_state state, a.planner_request plan FROM `tabWork Assignment Employee` we INNER JOIN `tabWork Management Assigner` a ON we.parent = a.name WHERE " + wewhere + " ORDER BY a.from_date DESC LIMIT 2000", tuple(params), as_dict=True)
        out["assignments"] = rows

        # 3) summary per employee (count of assignments, active vs left, distinct farms/tasks)
        summ = {}
        for r in rows:
            k = r.employee
            g = summ.get(k)
            if not g:
                g = {"employee": r.employee, "employee_name": r.employee_name, "count": 0, "active": 0, "left": 0, "farms": {}, "tasks": {}}
                summ[k] = g
            g["count"] = g["count"] + 1
            if (r.wstatus or "") == "Left":
                g["left"] = g["left"] + 1
            else:
                g["active"] = g["active"] + 1
            if r.farm:
                g["farms"][r.farm] = 1
            if r.task:
                g["tasks"][r.task] = 1
        summ_out = []
        for k in summ:
            g = summ[k]
            g["farm_count"] = len(g["farms"])
            g["task_count"] = len(g["tasks"])
            del g["farms"]
            del g["tasks"]
            summ_out.append(g)
        summ_out = sorted(summ_out, key=lambda x: x["count"], reverse=True)

        # overlap detection: per worker, flag assignments whose live date-ranges intersect.
        # "live" = state not Rejected and worker not Left on that assignment.
        byemp = {}
        for r in rows:
            live = (r.state != "Rejected") and ((r.wstatus or "") != "Left")
            if not live:
                continue
            k = r.employee
            lst = byemp.get(k)
            if not lst:
                lst = []
                byemp[k] = lst
            lst.append(r)
        conflict_workers = {}
        conflict_pairs = 0
        for k in byemp:
            lst = byemp[k]
            n = len(lst)
            i = 0
            while i < n:
                j = i + 1
                while j < n:
                    a1 = lst[i]
                    a2 = lst[j]
                    af = a1.from_date
                    at = a1.to_date
                    bf = a2.from_date
                    bt = a2.to_date
                    if af and at and bf and bt and (af <= bt) and (bf <= at):
                        conflict_pairs = conflict_pairs + 1
                        conflict_workers[k] = 1
                        a1["overlap"] = 1
                        a2["overlap"] = 1
                    j = j + 1
                i = i + 1
        # stamp overlap flag onto summary
        for g in summ_out:
            g["has_conflict"] = 1 if conflict_workers.get(g["employee"]) else 0

        out["summary"] = summ_out
        out["assignments"] = rows

        # KPI rollups over the filtered set
        all_farms = {}
        all_tasks = {}
        active_c = 0
        left_c = 0
        pend_c = 0
        rej_c = 0
        asgd_c = 0
        for r in rows:
            if r.farm:
                all_farms[r.farm] = 1
            if r.task:
                all_tasks[r.task] = 1
            if (r.wstatus or "") == "Left":
                left_c = left_c + 1
            else:
                active_c = active_c + 1
            st = r.state or ""
            if st == "Assigned":
                asgd_c = asgd_c + 1
            elif st == "Rejected":
                rej_c = rej_c + 1
            elif st.find("Pending") >= 0:
                pend_c = pend_c + 1
        out["kpis"] = {
            "workers": len(summ_out),
            "assignments": len(rows),
            "farms": len(all_farms),
            "tasks": len(all_tasks),
            "active_slots": active_c,
            "left_slots": left_c,
            "pending": pend_c,
            "rejected": rej_c,
            "assigned": asgd_c,
            "conflict_workers": len(conflict_workers),
            "conflict_pairs": conflict_pairs
        }
        out["farms"] = FARMS

    elif action == "emp_detail":
        # Full detail for ONE worker: profile + all assignments + all actuals (days/qty/pay).
        emp = frappe.form_dict.get("employee")
        prof = frappe.db.get_value("Employee", emp,
            ["name", "employee_name", "custom_farm", "custom_business_unit", "custom_group_name",
             "designation", "employment_type", "status", "date_of_joining", "cell_number"], as_dict=True)
        out["profile"] = prof or {}

        # all assignments this worker is on (joined to the parent assignment)
        asg = frappe.db.sql("SELECT we.status wstatus, we.start_date start_date, we.left_date left_date, a.name assignment, a.farm farm, a.task task, a.block_section block_section, a.from_date from_date, a.to_date to_date, a.workflow_state state, a.planner_request plan FROM `tabWork Assignment Employee` we INNER JOIN `tabWork Management Assigner` a ON we.parent = a.name WHERE we.employee = %s ORDER BY a.from_date DESC LIMIT 500", (emp,), as_dict=True)
        out["assignments"] = asg

        # all actuals rows for this worker (daily work + pay), joined to the parent actual for context
        acts = frappe.db.sql("SELECT we.work_date work_date, we.actual_quantity qty, we.amount amount, we.count_in_payroll in_payroll, we.paid paid, we.payment_ref payment_ref, ac.name actual, ac.farm farm, ac.task task, ac.block_section block_section, ac.workflow_state state FROM `tabWork Actuals Employee` we INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name WHERE we.employee = %s ORDER BY we.work_date DESC LIMIT 2000", (emp,), as_dict=True)
        out["actuals"] = acts

        # tallies
        tot_qty = 0
        tot_earned = 0
        tot_paid = 0
        days_worked = 0
        for r in acts:
            tot_qty = tot_qty + frappe.utils.flt(r.qty)
            tot_earned = tot_earned + frappe.utils.flt(r.amount)
            if frappe.utils.cint(r.paid) == 1:
                tot_paid = tot_paid + frappe.utils.flt(r.amount)
            days_worked = days_worked + 1
        out["totals"] = {
            "assignments": len(asg),
            "days_worked": days_worked,
            "qty": tot_qty,
            "earned": tot_earned,
            "paid": tot_paid,
            "outstanding": tot_earned - tot_paid
        }

    elif action == "dash":
        def state_counts(table):
            d = {}
            for r in frappe.db.sql("SELECT workflow_state s, COUNT(*) c FROM `tab" + table + "` GROUP BY workflow_state", as_dict=True):
                d[r.s or "Draft"] = r.c
            return d
        plan_states = state_counts("Work Management Planner")
        asg_states = state_counts("Work Management Assigner")
        act_states = state_counts("Work Management Actuals")
        pay_states = state_counts("Work Management Payment")

        farm_map = {}
        for f in FARMS:
            farm_map[f] = {"farm": f, "approved_plans": 0, "pending_plans": 0,
                "approved_cost": 0, "planned_people": 0, "assignments": 0,
                "workers_deployed": 0, "unassigned": 0, "actual_payment": 0, "confirmed_actuals": 0,
                "planned_qty": 0, "actual_qty": 0, "paid_amount": 0, "workers_paid": 0, "planned_value": 0,
                "assigned_workers": 0, "confirmed_workers": 0, "awaiting_workers": 0, "crew_days": 0, "closed_plans": 0}

        for r in frappe.db.sql("""SELECT farm, COUNT(*) c, SUM(total_cost) cost, SUM(people_per_day) ppl, SUM(quantity) qty, SUM(person_days) pd
            FROM `tabWork Management Planner` WHERE workflow_state='Approved' GROUP BY farm""", as_dict=True):
            if r.farm in farm_map:
                farm_map[r.farm]["approved_plans"] = r.c
                farm_map[r.farm]["approved_cost"] = r.cost or 0
                farm_map[r.farm]["planned_people"] = r.ppl or 0
                farm_map[r.farm]["planned_qty"] = r.qty or 0
                farm_map[r.farm]["planned_value"] = r.cost or 0
                farm_map[r.farm]["crew_days"] = r.pd or 0
        for r in frappe.db.sql("""SELECT farm, COUNT(*) c FROM `tabWork Management Planner`
            WHERE workflow_state='Pending Approval' GROUP BY farm""", as_dict=True):
            if r.farm in farm_map:
                farm_map[r.farm]["pending_plans"] = r.c
        # closed-early plans per farm (workflow_state stays Approved; flagged via custom_close_state)
        for r in frappe.db.sql("""SELECT farm, COUNT(*) c FROM `tabWork Management Planner`
            WHERE custom_close_state='Closed' GROUP BY farm""", as_dict=True):
            if r.farm in farm_map:
                farm_map[r.farm]["closed_plans"] = r.c
        for r in frappe.db.sql("""SELECT farm, COUNT(*) c, SUM(assigned_count) dep
            FROM `tabWork Management Assigner` WHERE workflow_state='Assigned' GROUP BY farm""", as_dict=True):
            if r.farm in farm_map:
                farm_map[r.farm]["assignments"] = r.c
                farm_map[r.farm]["workers_deployed"] = r.dep or 0
        for r in frappe.db.sql("""SELECT farm, COUNT(*) c, SUM(total_payment) pay, SUM(total_actual_qty) qty
            FROM `tabWork Management Actuals` WHERE workflow_state='CONFIRMED' GROUP BY farm""", as_dict=True):
            if r.farm in farm_map:
                farm_map[r.farm]["actual_payment"] = r.pay or 0
                farm_map[r.farm]["confirmed_actuals"] = r.c
                farm_map[r.farm]["actual_qty"] = r.qty or 0
        # paid amount + distinct workers paid per farm (from confirmed actuals rows marked paid)
        for r in frappe.db.sql("""
            SELECT ac.farm farm, COALESCE(SUM(we.amount),0) paid_amt, COUNT(DISTINCT we.employee) wkrs
            FROM `tabWork Actuals Employee` we
            INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
            WHERE ac.workflow_state='CONFIRMED' AND IFNULL(we.paid,0)=1
            GROUP BY ac.farm""", as_dict=True):
            if r.farm in farm_map:
                farm_map[r.farm]["paid_amount"] = r.paid_amt or 0
                farm_map[r.farm]["workers_paid"] = r.wkrs or 0
        # DISTINCT assigned workers per farm (each person once, across live assignments)
        for r in frappe.db.sql("""
            SELECT a.farm farm, COUNT(DISTINCT we.employee) w
            FROM `tabWork Assignment Employee` we
            INNER JOIN `tabWork Management Assigner` a ON we.parent = a.name
            WHERE a.workflow_state IN ('Pending Farm Manager','Pending HR Head','Pending GM','Assigned')
              AND IFNULL(we.status,'Active') = 'Active'
            GROUP BY a.farm""", as_dict=True):
            if r.farm in farm_map:
                farm_map[r.farm]["assigned_workers"] = r.w or 0
        # DISTINCT workers on CONFIRMED actuals per farm (those with confirmation of doing jobs)
        conf_by_farm = {}
        for r in frappe.db.sql("""
            SELECT ac.farm farm, COUNT(DISTINCT we.employee) w
            FROM `tabWork Actuals Employee` we
            INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
            WHERE ac.workflow_state = 'CONFIRMED'
            GROUP BY ac.farm""", as_dict=True):
            conf_by_farm[r.farm] = r.w or 0
            if r.farm in farm_map:
                farm_map[r.farm]["confirmed_workers"] = r.w or 0

        farm_rows = []
        tot_cost = 0; tot_ppl = 0; tot_deployed = 0; tot_actpay = 0
        tot_planqty = 0; tot_actqty = 0; tot_paid = 0; tot_wkrs_paid = 0
        for f in FARMS:
            fr = farm_map[f]
            fr["unassigned"] = fr["approved_plans"] - fr["assignments"]
            tot_cost = tot_cost + fr["approved_cost"]
            tot_ppl = tot_ppl + fr["planned_people"]
            tot_deployed = tot_deployed + fr["workers_deployed"]
            tot_actpay = tot_actpay + fr["actual_payment"]
            tot_planqty = tot_planqty + fr["planned_qty"]
            tot_actqty = tot_actqty + fr["actual_qty"]
            tot_paid = tot_paid + fr["paid_amount"]
            tot_wkrs_paid = tot_wkrs_paid + fr["workers_paid"]
            aw = fr["assigned_workers"] - fr["confirmed_workers"]
            fr["awaiting_workers"] = aw if aw > 0 else 0
            farm_rows.append(fr)
        tot_assigned_w = 0; tot_conf_w = 0; tot_await_w = 0; tot_crewdays = 0
        for f in FARMS:
            tot_assigned_w = tot_assigned_w + farm_map[f]["assigned_workers"]
            tot_conf_w = tot_conf_w + farm_map[f]["confirmed_workers"]
            tot_await_w = tot_await_w + farm_map[f]["awaiting_workers"]
            tot_crewdays = tot_crewdays + farm_map[f]["crew_days"]

        unpaid_row = frappe.db.sql("""SELECT SUM(total_payment) s FROM `tabWork Management Actuals`
            WHERE workflow_state='CONFIRMED' AND IFNULL(paid,0)=0""", as_dict=True)
        unpaid = (unpaid_row[0].s or 0) if unpaid_row else 0
        paid_row = frappe.db.sql("""SELECT SUM(grand_total) s FROM `tabWork Management Payment`
            WHERE workflow_state='Paid'""", as_dict=True)
        paid_total = (paid_row[0].s or 0) if paid_row else 0

        out["plan_states"] = plan_states
        out["asg_states"] = asg_states
        out["act_states"] = act_states
        out["pay_states"] = pay_states
        out["farms"] = farm_rows
        out["totals"] = {
            "approved_cost": tot_cost, "planned_people": tot_ppl, "workers_deployed": tot_deployed,
            "approved_plans": plan_states.get("Approved", 0), "assignments": asg_states.get("Assigned", 0),
            "plan_pending": plan_states.get("Pending Approval", 0), "asg_pending": asg_states.get("Pending Farm Manager", 0) + asg_states.get("Pending HR Head", 0) + asg_states.get("Pending GM", 0),
            "act_confirmed": act_states.get("CONFIRMED", 0), "actual_payment": tot_actpay,
            "planned_qty": tot_planqty, "actual_qty": tot_actqty, "planned_value": tot_cost,
            "paid_amount": tot_paid, "workers_paid": tot_wkrs_paid,
            "assigned_workers": tot_assigned_w, "confirmed_workers": tot_conf_w, "awaiting_workers": tot_await_w,
            "crew_days": tot_crewdays,
            "unpaid": unpaid, "paid_total": paid_total,
            "act_pending": act_states.get("Pending Farm Manager", 0) + act_states.get("Pending HR Head", 0) + act_states.get("Pending GM", 0),
            "pay_pending": pay_states.get("Pending Accounts", 0)}
        out["funnel"] = {"planned": plan_states.get("Approved", 0), "assigned": asg_states.get("Assigned", 0),
            "confirmed": act_states.get("CONFIRMED", 0), "paid": pay_states.get("Paid", 0)}
        out["plan_pending"] = frappe.db.get_all("Work Management Planner",
            filters={"workflow_state": "Pending Approval"},
            fields=["name","farm","block_section","task","people_per_day","total_cost","requested_by"],
            order_by="request_date desc", limit=50)
        out["asg_pending"] = frappe.db.get_all("Work Management Assigner",
            filters={"workflow_state": "Pending HR Head"},
            fields=["name","farm","task","planned_people","assigned_count","variance","assigned_by"],
            order_by="assign_date desc", limit=50)
        out["act_pending"] = frappe.db.get_all("Work Management Actuals",
            filters={"workflow_state": ["in", ["Pending Farm Manager","Pending HR Head","Pending GM"]]},
            fields=["name","farm","task","workflow_state","actual_people","payroll_people","total_payment"],
            order_by="entry_date desc", limit=50)
        out["pay_pending_list"] = frappe.db.get_all("Work Management Payment",
            filters={"workflow_state": "Pending Accounts"},
            fields=["name","run_title","total_workers","grand_total"], order_by="run_date desc", limit=50)
        # ---- approval speed (step by step): per sign-off step, timing + who + what's waiting now ----
        appr_names = {}
        appr_eff = []
        def eff_step(group, step, dtype, user_field, date_field, done_state, pending_states):
            # completed sign-offs: timing from creation -> approval date
            em = frappe.get_meta(dtype)
            if not em.get_field(user_field):
                return
            dwant = ["name", user_field, "creation"]
            if em.get_field(date_field):
                dwant.append(date_field)
            done = frappe.db.get_all(dtype, filters={"workflow_state": done_state},
                fields=dwant, limit=8000)
            n = 0
            d1 = 0
            d0 = 0
            people = {}
            for r in done:
                who = r.get(user_field)
                appd = r.get(date_field)
                if not who or not appd:
                    continue
                n = n + 1
                people[who] = people.get(who, 0) + 1
                days = frappe.utils.date_diff(appd, frappe.utils.getdate(r.creation))
                if days < 0:
                    days = 0
                d1 = d1 + days
                if days < 1:
                    d0 = d0 + 1
                if who not in appr_names:
                    fn = frappe.db.get_value("User", who, "full_name")
                    appr_names[who] = fn or who
            # pending at this step now
            pend = frappe.db.get_all(dtype, filters={"workflow_state": ["in", pending_states]},
                fields=["name", "creation"], limit=8000)
            pend_n = len(pend)
            wait_sum = 0
            today = frappe.utils.getdate(frappe.utils.today())
            for r in pend:
                w = frappe.utils.date_diff(today, frappe.utils.getdate(r.creation))
                if w < 0:
                    w = 0
                wait_sum = wait_sum + w
            ppl = []
            for u in people:
                ppl.append({"user": u, "n": people[u]})
            appr_eff.append({
                "group": group, "step": step,
                "n": n, "avg_days": (d1 / n) if n else None,
                "eff_pct": (d0 / n * 100) if n else None,
                "people": ppl,
                "pending_n": pend_n,
                "pending_avg_wait": (wait_sum / pend_n) if pend_n else None
            })
        eff_step("Work plans", "Approve", "Work Management Planner", "approved_by", "approval_date", "Approved", ["Pending Approval"])
        eff_step("Assignments", "GM", "Work Management Assigner", "approved_by", "approval_date", "Assigned", ["Pending Farm Manager","Pending HR Head","Pending GM"])
        eff_step("Work records", "GM", "Work Management Actuals", "gm_approved_by", "gm_approval_date", "CONFIRMED", ["Pending Farm Manager","Pending HR Head","Pending GM"])
        eff_step("Payments", "Accounts", "Work Management Payment", "accounts_approved_by", "accounts_approval_date", "Paid", ["Pending Accounts"])
        out["approval_eff"] = appr_eff
        out["approver_names"] = appr_names

    elif action == "burndown":
        rows = frappe.db.sql("""
            SELECT p.name, p.farm, p.block_section, p.task, p.quantity target,
                   COALESCE(p.fulfilled_qty,0) fulfilled,
                   COALESCE(p.remaining_qty, p.quantity) remaining,
                   COALESCE(p.fulfilment_pct,0) pct,
                   COALESCE(p.over_target,0) over_target,
                   COALESCE(p.person_days,0) mandays,
                   COALESCE(p.total_hours,0) total_hours,
                   p.uom, p.workflow_state,
                   COALESCE(p.custom_close_state,'') close_state
            FROM `tabWork Management Planner` p
            WHERE p.workflow_state = 'Approved'
            ORDER BY p.farm, p.fulfilment_pct DESC
        """, as_dict=True)
        ecount = {}
        for e in frappe.db.sql("""
            SELECT a2.planner_request plan, COUNT(ac.name) n
            FROM `tabWork Management Actuals` ac
            INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
            WHERE ac.workflow_state = 'CONFIRMED'
            GROUP BY a2.planner_request
        """, as_dict=True):
            ecount[e.plan] = e.n
        # substitution count per plan (Left workers on the plan's assignments)
        subcount = {}
        for srow in frappe.db.sql("""
            SELECT a2.planner_request plan, COUNT(*) n
            FROM `tabWork Assignment Employee` we
            INNER JOIN `tabWork Management Assigner` a2 ON we.parent = a2.name
            WHERE we.status = 'Left'
            GROUP BY a2.planner_request
        """, as_dict=True):
            subcount[srow.plan] = srow.n
        for r in rows:
            r["entries"] = ecount.get(r.name, 0)
            r["subs"] = subcount.get(r.name, 0)
        out["plans"] = rows

    elif action == "substitutions":
        # full substitution history — set-based (the old per-row loop timed out)
        subs = frappe.db.sql("""
            SELECT we.parent assignment, a.planner_request plan, a.farm, a.task,
                   we.employee left_emp, we.employee_name left_name, we.left_date
            FROM `tabWork Assignment Employee` we
            INNER JOIN `tabWork Management Assigner` a ON we.parent = a.name
            WHERE we.status = 'Left'
            ORDER BY we.left_date DESC
            LIMIT 400
        """, as_dict=True)
        asg_names = []
        emp_ids = []
        for srow in subs:
            if srow.assignment and srow.assignment not in asg_names:
                asg_names.append(srow.assignment)
            if srow.left_emp and srow.left_emp not in emp_ids:
                emp_ids.append(srow.left_emp)
        # every mid-period joiner (Active with a start date) — matched ones become the
        # replacement side of a swap; unmatched ones are standalone "Joined" events
        joiners = frappe.db.sql("""
            SELECT we.parent, we.employee, we.employee_name, we.start_date,
                   a.planner_request plan, a.farm, a.task
            FROM `tabWork Assignment Employee` we
            INNER JOIN `tabWork Management Assigner` a ON we.parent = a.name
            WHERE we.status = 'Active' AND we.start_date IS NOT NULL
            ORDER BY we.start_date DESC
            LIMIT 400
        """, as_dict=True)
        reps_map = {}
        for rr in joiners:
            reps_map.setdefault(rr.parent, []).append(rr)
            if rr.parent not in asg_names:
                asg_names.append(rr.parent)
            if rr.employee and rr.employee not in emp_ids:
                emp_ids.append(rr.employee)
        contrib = {}
        if emp_ids and asg_names:
            ph1 = ",".join(["%s"] * len(emp_ids))
            ph2 = ",".join(["%s"] * len(asg_names))
            crows = frappe.db.sql("""
                SELECT we.employee emp, ac.assignment asg,
                       COALESCE(SUM(we.actual_quantity),0) qty,
                       COUNT(DISTINCT we.work_date) days,
                       COALESCE(SUM(we.amount),0) pay
                FROM `tabWork Actuals Employee` we
                INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
                WHERE ac.workflow_state='CONFIRMED'
                  AND we.employee IN (""" + ph1 + """)
                  AND ac.assignment IN (""" + ph2 + """)
                GROUP BY we.employee, ac.assignment
            """, tuple(emp_ids) + tuple(asg_names), as_dict=True)
            for cr in crows:
                contrib[(cr.emp, cr.asg)] = cr
        matched = {}
        for srow in subs:
            rep = None
            for rr in reps_map.get(srow.assignment, []):
                if matched.get((srow.assignment, rr.employee)):
                    continue
                if not srow.left_date or (rr.start_date and str(rr.start_date) >= str(srow.left_date)):
                    rep = rr
                    break
            if rep:
                matched[(srow.assignment, rep.employee)] = 1
            srow["kind"] = "Swap" if rep else "Left"
            srow["rep_emp"] = rep.employee if rep else None
            srow["rep_name"] = rep.employee_name if rep else None
            srow["rep_start"] = str(rep.start_date) if rep and rep.start_date else None
            cr = contrib.get((srow.left_emp, srow.assignment))
            srow["left_qty"] = frappe.utils.flt(cr.qty) if cr else 0
            srow["left_days"] = frappe.utils.cint(cr.days) if cr else 0
            srow["left_pay"] = frappe.utils.flt(cr.pay) if cr else 0
            srow["left_date"] = str(srow.left_date) if srow.left_date else None
            srow["event_date"] = srow["left_date"]
        # standalone joins: mid-period additions with no leaver matched to them
        for rr in joiners:
            if matched.get((rr.parent, rr.employee)):
                continue
            cr = contrib.get((rr.employee, rr.parent))
            subs.append({
                "assignment": rr.parent, "plan": rr.plan, "farm": rr.farm, "task": rr.task,
                "kind": "Joined",
                "left_emp": None, "left_name": None, "left_date": None,
                "rep_emp": rr.employee, "rep_name": rr.employee_name,
                "rep_start": str(rr.start_date) if rr.start_date else None,
                "left_qty": frappe.utils.flt(cr.qty) if cr else 0,
                "left_days": frappe.utils.cint(cr.days) if cr else 0,
                "left_pay": frappe.utils.flt(cr.pay) if cr else 0,
                "event_date": str(rr.start_date) if rr.start_date else None,
            })
        subs = sorted(subs, key=lambda x: x.get("event_date") or "", reverse=True)
        out["subs"] = subs

    elif action == "timeline":
        # Daily comparison series: planned output/value vs staffed (assigned) share vs
        # confirmed actuals — for the delivery timeline chart. Optional farm + range.
        tfarm = frappe.form_dict.get("farm")
        tfrom = frappe.form_dict.get("from_date") or frappe.utils.add_days(frappe.utils.today(), -41)
        tto = frappe.form_dict.get("to_date") or frappe.utils.today()
        days_idx = {}
        cursor = frappe.utils.getdate(tfrom)
        endd = frappe.utils.getdate(tto)
        guard = 0
        while cursor <= endd and guard < 400:
            days_idx[str(cursor)] = {"d": str(cursor), "planned_qty": 0, "assigned_qty": 0, "actual_qty": 0,
                                     "planned_val": 0, "assigned_val": 0, "actual_val": 0}
            cursor = frappe.utils.add_days(cursor, 1)
            guard = guard + 1
        # actuals per day
        aconds = "ac.workflow_state='CONFIRMED' AND we.work_date >= %s AND we.work_date <= %s"
        aparams = [tfrom, tto]
        if tfarm:
            aconds = aconds + " AND ac.farm = %s"
            aparams.append(tfarm)
        arows = frappe.db.sql("""
            SELECT we.work_date d, COALESCE(SUM(we.actual_quantity),0) qty, COALESCE(SUM(we.amount),0) val
            FROM `tabWork Actuals Employee` we
            INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
            WHERE """ + aconds + """
            GROUP BY we.work_date
        """, tuple(aparams), as_dict=True)
        for r in arows:
            rec = days_idx.get(str(r.d))
            if rec:
                rec["actual_qty"] = frappe.utils.flt(r.qty)
                rec["actual_val"] = frappe.utils.flt(r.val)
        # approved plans overlapping the window -> spread daily share
        pflt = {"workflow_state": ["in", ["Approved", "Assigned"]],
                "from_date": ["<=", tto], "to_date": [">=", tfrom]}
        if tfarm:
            pflt["farm"] = tfarm
        plans = frappe.db.get_all("Work Management Planner", filters=pflt,
            fields=["name", "farm", "quantity", "total_cost", "working_days", "from_date", "to_date"],
            limit=2000)
        staffed = {}
        if plans:
            pnames = [p.name for p in plans]
            ph = ",".join(["%s"] * len(pnames))
            srws = frappe.db.sql("""
                SELECT DISTINCT planner_request FROM `tabWork Management Assigner`
                WHERE planner_request IN (""" + ph + """)
                  AND workflow_state IN ('Pending Farm Manager','Pending HR Head','Pending GM','Assigned')
            """, tuple(pnames), as_dict=True)
            for r in srws:
                staffed[r.planner_request] = 1
        for pl in plans:
            wd = frappe.utils.cint(pl.working_days) or (frappe.utils.date_diff(pl.to_date, pl.from_date) + 1)
            if wd <= 0:
                continue
            dq = frappe.utils.flt(pl.quantity) / wd
            dv = frappe.utils.flt(pl.total_cost) / wd
            is_staffed = staffed.get(pl.name)
            cursor = frappe.utils.getdate(pl.from_date)
            pend = frappe.utils.getdate(pl.to_date)
            guard = 0
            while cursor <= pend and guard < 400:
                rec = days_idx.get(str(cursor))
                if rec:
                    rec["planned_qty"] = rec["planned_qty"] + dq
                    rec["planned_val"] = rec["planned_val"] + dv
                    if is_staffed:
                        rec["assigned_qty"] = rec["assigned_qty"] + dq
                        rec["assigned_val"] = rec["assigned_val"] + dv
                cursor = frappe.utils.add_days(cursor, 1)
                guard = guard + 1
        series = []
        for kd in sorted(days_idx.keys()):
            series.append(days_idx[kd])
        out["days"] = series
        out["window"] = {"from": str(tfrom), "to": str(tto), "farm": tfarm or None}
        tl_farms = frappe.db.sql("""SELECT DISTINCT farm FROM `tabWork Management Planner`
            WHERE farm IS NOT NULL AND farm != '' ORDER BY farm""", as_dict=True)
        out["farms"] = [f.farm for f in tl_farms]

    elif action == "plan_entries":
        nm = frappe.form_dict.get("planner")
        out["entries"] = frappe.db.sql("""
            SELECT ac.name, ac.entry_date, ac.total_actual_qty, ac.payroll_people, ac.total_payment
            FROM `tabWork Management Actuals` ac
            INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
            WHERE a2.planner_request = %s AND ac.workflow_state = 'CONFIRMED'
            ORDER BY ac.entry_date
        """, (nm,), as_dict=True)

    elif action == "plan_calendar":
        nm = frappe.form_dict.get("planner")
        p = frappe.db.get_value("Work Management Planner", nm,
            ["quantity","from_date","to_date","uom","farm","task","fulfilled_qty","remaining_qty",
             "fulfilment_pct","over_target","person_days","total_hours","people_per_day","working_days"],
            as_dict=True)
        days = frappe.db.sql("""
            SELECT ac.entry_date d,
                   COALESCE(SUM(ac.total_actual_qty),0) qty,
                   COALESCE(SUM(ac.payroll_people),0) workers,
                   COALESCE(SUM(ac.total_payment),0) pay,
                   COUNT(ac.name) entries
            FROM `tabWork Management Actuals` ac
            INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
            WHERE a2.planner_request = %s AND ac.workflow_state = 'CONFIRMED'
            GROUP BY ac.entry_date
            ORDER BY ac.entry_date
        """, (nm,), as_dict=True)
        daymap = {}
        for r in days:
            daymap[str(r.d)] = {"qty": r.qty, "workers": r.workers, "pay": r.pay, "entries": r.entries}
        out["plan"] = p
        out["days"] = daymap

    elif action == "assignment_detail":
        # one assignment header + roster + actuals (for the dashboard queue expander)
        aname = frappe.form_dict.get("assignment")
        a = frappe.db.get_value("Work Management Assigner", aname,
            ["name","farm","block_section","task","planned_people","assigned_count","variance",
             "planned_cost","from_date","to_date","workflow_state","planner_request"], as_dict=True)
        out["assignment"] = a or {}
        out["workers"] = frappe.db.sql("""
            SELECT employee, employee_name, employment_type, status, start_date, left_date
            FROM `tabWork Assignment Employee` WHERE parent = %s ORDER BY idx
        """, (aname,), as_dict=True)
        out["actuals"] = frappe.db.sql("""
            SELECT name, total_actual_qty, actual_people, payroll_people, total_payment, workflow_state
            FROM `tabWork Management Actuals` WHERE assignment = %s ORDER BY creation DESC
        """, (aname,), as_dict=True)

    elif action == "cost_group_detail":
        # the confirmed worker-rows behind ONE cost-breakdown group (task/worker/farm), filtered.
        cgroup = frappe.form_dict.get("group") or "task"
        ckey = frappe.form_dict.get("key")
        cbfarm = frappe.form_dict.get("farm")
        cbtask = frappe.form_dict.get("task")
        cbfrom = frappe.form_dict.get("from_date")
        cbto = frappe.form_dict.get("to_date")
        conds = ["ac.workflow_state = 'CONFIRMED'"]
        params = []
        if cbfarm:
            conds.append("ac.farm = %s"); params.append(cbfarm)
        if cbtask:
            conds.append("ac.task LIKE %s"); params.append("%" + cbtask + "%")
        if cbfrom:
            conds.append("we.work_date >= %s"); params.append(cbfrom)
        if cbto:
            conds.append("we.work_date <= %s"); params.append(cbto)
        # scope to the clicked group
        if cgroup == "worker":
            conds.append("we.employee_name = %s"); params.append(ckey)
        elif cgroup == "farm":
            conds.append("ac.farm = %s"); params.append(ckey)
        else:
            conds.append("ac.task = %s"); params.append(ckey)
        where = " AND ".join(conds)
        rows = frappe.db.sql("""
            SELECT we.work_date work_date, we.employee employee, we.employee_name employee_name,
                   ac.farm farm, ac.task task, ac.name actual_ref,
                   COALESCE(we.actual_quantity,0) qty, COALESCE(we.amount,0) amount, IFNULL(we.paid,0) paid
            FROM `tabWork Actuals Employee` we
            INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
            WHERE """ + where + """
            ORDER BY we.work_date DESC LIMIT 3000
        """, tuple(params), as_dict=True)
        est = 0
        paid = 0
        for r in rows:
            est = est + frappe.utils.flt(r.amount)
            if frappe.utils.cint(r.paid) == 1:
                paid = paid + frappe.utils.flt(r.amount)
        out["rows"] = rows
        out["group"] = cgroup
        out["key"] = ckey
        out["totals"] = {"count": len(rows), "estimated": est, "paid": paid, "outstanding": est - paid}

    elif action == "charts":
        # confirmed-work analytics: weekly output/pay/workers, top tasks, farm share, approver ranking.
        # Follows the dashboard date filter; no filter = last ~12 weeks.
        cfrom = frappe.form_dict.get("from_date")
        cto = frappe.form_dict.get("to_date")
        if not cfrom and not cto:
            cto = frappe.utils.today()
            cfrom = frappe.utils.add_days(cto, -84)
        dconds = "ac.workflow_state='CONFIRMED'"
        dparams = []
        if cfrom:
            dconds = dconds + " AND we.work_date >= %s"
            dparams.append(cfrom)
        if cto:
            dconds = dconds + " AND we.work_date <= %s"
            dparams.append(cto)
        # weekly buckets (Monday start) via YEARWEEK, converted to the Monday date in python
        wk = frappe.db.sql("""
            SELECT MIN(we.work_date) wk_any,
                   YEARWEEK(we.work_date, 3) yw,
                   COALESCE(SUM(we.actual_quantity),0) qty,
                   COALESCE(SUM(we.amount),0) pay,
                   COUNT(DISTINCT we.employee) workers
            FROM `tabWork Actuals Employee` we
            INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
            WHERE """ + dconds + """
            GROUP BY YEARWEEK(we.work_date, 3)
            ORDER BY yw
        """, tuple(dparams), as_dict=True)
        weekly = []
        for r in wk:
            # Monday of that week: shift wk_any back to Monday
            d0 = frappe.utils.getdate(r.wk_any)
            wd = d0.weekday()  # Mon=0
            monday = frappe.utils.add_days(d0, -wd)
            weekly.append({"wstart": str(monday), "qty": frappe.utils.flt(r.qty),
                "pay": frappe.utils.flt(r.pay), "workers": frappe.utils.cint(r.workers)})
        out["weekly"] = weekly
        # top tasks by confirmed pay
        tt = frappe.db.sql("""
            SELECT ac.task label, COALESCE(SUM(we.amount),0) pay,
                   COALESCE(SUM(we.actual_quantity),0) qty, COUNT(DISTINCT we.employee) workers
            FROM `tabWork Actuals Employee` we
            INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
            WHERE """ + dconds + """
            GROUP BY ac.task ORDER BY pay DESC LIMIT 10
        """, tuple(dparams), as_dict=True)
        out["top_tasks"] = [{"label": r.label, "pay": frappe.utils.flt(r.pay),
            "qty": frappe.utils.flt(r.qty), "workers": frappe.utils.cint(r.workers)} for r in tt]
        # farm share
        fsh = frappe.db.sql("""
            SELECT ac.farm farm, COALESCE(SUM(we.amount),0) pay,
                   COALESCE(SUM(we.actual_quantity),0) qty, COUNT(DISTINCT we.employee) workers
            FROM `tabWork Actuals Employee` we
            INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
            WHERE """ + dconds + """
            GROUP BY ac.farm ORDER BY pay DESC
        """, tuple(dparams), as_dict=True)
        out["farm_share"] = [{"farm": r.farm, "pay": frappe.utils.flt(r.pay),
            "qty": frappe.utils.flt(r.qty), "workers": frappe.utils.cint(r.workers)} for r in fsh]
        # ---- approver ranking: count sign-offs per person per pipeline step ----
        # Uses the *_approved_by fields present on each doctype. Day-level timing where a
        # matching date field exists; otherwise counts only. Groups: Work plans / Assignments /
        # Work records / Payments; steps: FM / HR / GM / Approve / Accounts.
        approvers = []
        names = {}
        def add_appr(group, step, user_field, date_field, created_field, dtype, statefilter):
            am = frappe.get_meta(dtype)
            if not am.get_field(user_field):
                return
            wantf = ["name", user_field, created_field]
            has_date = True if am.get_field(date_field) else False
            if has_date:
                wantf.append(date_field)
            rows = frappe.db.get_all(dtype, filters=statefilter,
                fields=wantf, limit=5000)
            agg = {}
            for r in rows:
                who = r.get(user_field)
                if not who:
                    continue
                g = agg.get(who)
                if not g:
                    g = {"n": 0, "d0": 0, "d1": 0, "slow": 0, "mx": 0, "ym": None}
                    agg[who] = g
                g["n"] = g["n"] + 1
                appd = r.get(date_field)
                crd = r.get(created_field)
                if appd and crd:
                    days = frappe.utils.date_diff(appd, frappe.utils.getdate(crd))
                    if days < 0:
                        days = 0
                    g["d1"] = g["d1"] + days
                    if days < 1:
                        g["d0"] = g["d0"] + 1
                    if days >= 2:
                        g["slow"] = g["slow"] + 1
                    if days > g["mx"]:
                        g["mx"] = days
                    if not g["ym"]:
                        g["ym"] = str(appd)[:7]
            for who in agg:
                g = agg[who]
                avg_d = (g["d1"] / g["n"]) if g["n"] else None
                approvers.append({"who": who, "group": group, "step": step,
                    "n": g["n"], "avg_d": avg_d, "d0": g["d0"], "d1": g["d0"], "slow": g["slow"],
                    "mx": g["mx"], "ym": g["ym"] or frappe.utils.today()[:7],
                    "pn": 0, "avg_min": None, "best_min": None})
                if who not in names:
                    fn = frappe.db.get_value("User", who, "full_name")
                    names[who] = fn or who
        # Work records (Actuals): FM / HR / GM
        add_appr("Work records", "FM", "fm_approved_by", "fm_approval_date", "creation", "Work Management Actuals", {"workflow_state": "CONFIRMED"})
        add_appr("Work records", "HR", "hr_approved_by", "hr_approval_date", "creation", "Work Management Actuals", {"workflow_state": "CONFIRMED"})
        add_appr("Work records", "GM", "gm_approved_by", "gm_approval_date", "creation", "Work Management Actuals", {"workflow_state": "CONFIRMED"})
        # Assignments: GM approve
        add_appr("Assignments", "GM", "approved_by", "approval_date", "creation", "Work Management Assigner", {"workflow_state": "Assigned"})
        # Work plans: approve
        add_appr("Work plans", "Approve", "approved_by", "approval_date", "creation", "Work Management Planner", {"workflow_state": "Approved"})
        # Payments: accounts
        add_appr("Payments", "Accounts", "accounts_approved_by", "accounts_approval_date", "creation", "Work Management Payment", {"workflow_state": "Paid"})
        out["approvers"] = approvers
        out["apr_names"] = names
        out["apr_window"] = {"from": cfrom, "to": cto}

    elif action == "ops_kpis":
        # Operations control board: where money & work stand at every stage (with
        # age), how long until workers get paid, and each approver's desk measured
        # by throughput and value — no minutes-to-approve noise.
        now_dt = frappe.utils.now_datetime()
        today_s = frappe.utils.today()
        kfrom = frappe.form_dict.get("from_date") or frappe.utils.add_days(today_s, -83)
        kto = frappe.form_dict.get("to_date") or today_s

        def age_days(ts):
            try:
                if not ts:
                    return None
                d = (now_dt - frappe.utils.get_datetime(ts)).total_seconds() / 86400.0
                return d if d >= 0 else 0.0
            except Exception:
                return None

        # ---- 1 · STAGE LEDGER: value sitting at every step right now ----
        ledger = []

        def ledge(key, label, route, rows, val_field, ts_fields):
            total = 0.0
            oldest = 0.0
            v_fresh = 0.0
            v_mid = 0.0
            v_old = 0.0
            for r in rows:
                v = frappe.utils.flt(r.get(val_field))
                total = total + v
                ts = None
                for f in ts_fields:
                    if r.get(f):
                        ts = r.get(f)
                        break
                a = age_days(ts)
                if a is None:
                    a = 0
                if a > oldest:
                    oldest = a
                if a < 3:
                    v_fresh = v_fresh + v
                elif a <= 7:
                    v_mid = v_mid + v
                else:
                    v_old = v_old + v
            ledger.append({"key": key, "label": label, "route": route,
                           "count": len(rows), "value": total, "oldest_d": oldest,
                           "v_fresh": v_fresh, "v_mid": v_mid, "v_old": v_old})

        ledge("plans_pending", "Plans awaiting approval", "/work-planner",
            frappe.db.get_all("Work Management Planner", filters={"workflow_state": "Pending Approval"},
                fields=["total_cost", "custom_submitted_at", "creation"], limit=2000),
            "total_cost", ["custom_submitted_at", "creation"])
        appr_plans = frappe.db.get_all("Work Management Planner",
            filters={"workflow_state": ["in", ["Approved", "Assigned"]]},
            fields=["name", "total_cost", "custom_approved_at", "approval_date"], limit=5000)
        staffed_p = {}
        if appr_plans:
            pnames = [r.name for r in appr_plans]
            ph = ",".join(["%s"] * len(pnames))
            for r in frappe.db.sql("""SELECT DISTINCT planner_request p FROM `tabWork Management Assigner`
                WHERE planner_request IN (""" + ph + """) AND workflow_state != 'Rejected'""",
                tuple(pnames), as_dict=True):
                staffed_p[r.p] = 1
        unstaffed = [r for r in appr_plans if not staffed_p.get(r.name)]
        ledge("plans_unstaffed", "Approved plans not yet staffed", "/work-assigner",
            unstaffed, "total_cost", ["custom_approved_at", "approval_date"])
        asg_rows = frappe.db.get_all("Work Management Assigner",
            filters={"workflow_state": ["in", ["Pending Farm Manager", "Pending HR Head", "Pending GM"]]},
            fields=["planned_cost", "custom_submitted_at", "creation"], limit=2000)
        ledge("asg_pending", "Assignments in approval", "/work-assigner",
            asg_rows, "planned_cost", ["custom_submitted_at", "creation"])
        asg_ok = frappe.db.get_all("Work Management Assigner", filters={"workflow_state": "Assigned"},
            fields=["name", "planned_cost", "custom_gm_approved_at", "approval_date"], limit=5000)
        has_act = {}
        if asg_ok:
            anames = [r.name for r in asg_ok]
            ph = ",".join(["%s"] * len(anames))
            for r in frappe.db.sql("""SELECT DISTINCT assignment a FROM `tabWork Management Actuals`
                WHERE assignment IN (""" + ph + """)""", tuple(anames), as_dict=True):
                has_act[r.a] = 1
        no_act = [r for r in asg_ok if not has_act.get(r.name)]
        ledge("asg_noactuals", "Staffed, no actuals recorded yet", "/work-actuals",
            no_act, "planned_cost", ["custom_gm_approved_at", "approval_date"])
        act_rows = frappe.db.get_all("Work Management Actuals",
            filters={"workflow_state": ["in", ["Pending Farm Manager", "Pending HR Head", "Pending GM"]]},
            fields=["total_payment", "workflow_state", "custom_submitted_at", "creation"], limit=2000)
        ledge("act_pending", "Actuals in approval (FM/HR/GM)", "/work-actuals",
            act_rows, "total_payment", ["custom_submitted_at", "creation"])
        cu = frappe.db.sql("""
            SELECT COALESCE(SUM(we.amount),0) v, COUNT(DISTINCT we.employee) c, MIN(we.work_date) oldest,
                   COALESCE(SUM(CASE WHEN DATEDIFF(%s, we.work_date) < 3 THEN we.amount ELSE 0 END),0) vf,
                   COALESCE(SUM(CASE WHEN DATEDIFF(%s, we.work_date) BETWEEN 3 AND 7 THEN we.amount ELSE 0 END),0) vm,
                   COALESCE(SUM(CASE WHEN DATEDIFF(%s, we.work_date) > 7 THEN we.amount ELSE 0 END),0) vo
            FROM `tabWork Actuals Employee` we
            INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
            WHERE ac.workflow_state='CONFIRMED' AND IFNULL(we.paid,0)=0
              AND IFNULL(we.count_in_payroll,0)=1 AND we.amount>0 AND we.payment_ref IS NULL
        """, (today_s, today_s, today_s), as_dict=True)
        ledger.append({"key": "confirmed_unpaid", "label": "Confirmed earnings not yet sent to accounts",
            "route": "/work-payment", "count": frappe.utils.cint(cu[0].c) if cu else 0,
            "value": frappe.utils.flt(cu[0].v) if cu else 0,
            "oldest_d": frappe.utils.date_diff(today_s, cu[0].oldest) if cu and cu[0].oldest else 0,
            "v_fresh": frappe.utils.flt(cu[0].vf) if cu else 0,
            "v_mid": frappe.utils.flt(cu[0].vm) if cu else 0,
            "v_old": frappe.utils.flt(cu[0].vo) if cu else 0})
        ledge("sent_accounts", "Sent, awaiting release by accounts", "/work-payment",
            frappe.db.get_all("Work Management Payment", filters={"workflow_state": "Pending Accounts"},
                fields=["grand_total", "custom_submitted_at", "creation"], limit=2000),
            "grand_total", ["custom_submitted_at", "creation"])
        out["ledger"] = ledger

        # ---- 2 · SPEED TO PAY: how long a day of work takes to reach the worker ----
        pd_rows = frappe.db.sql("""
            SELECT we.work_date wd, we.amount amt, p.accounts_approval_date paid_d,
                   ac.gm_approval_date conf_d, ac.farm farm
            FROM `tabWork Actuals Employee` we
            INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
            LEFT JOIN `tabWork Management Payment` p ON we.payment_ref = p.name
            WHERE IFNULL(we.paid,0)=1 AND we.amount>0 AND we.work_date >= %s AND we.work_date <= %s
        """, (kfrom, kto), as_dict=True)
        v_all = 0.0
        vd_pay = 0.0
        vd_conf = 0.0
        v_conf = 0.0
        farm_pay = {}
        weeks_pay = {}
        for r in pd_rows:
            amt = frappe.utils.flt(r.amt)
            if r.paid_d and r.wd:
                dd = frappe.utils.date_diff(r.paid_d, r.wd)
                if dd >= 0:
                    v_all = v_all + amt
                    vd_pay = vd_pay + amt * dd
                    fp = farm_pay.get(r.farm) or {"v": 0.0, "vd": 0.0}
                    fp["v"] = fp["v"] + amt
                    fp["vd"] = fp["vd"] + amt * dd
                    farm_pay[r.farm] = fp
                    wd0 = frappe.utils.getdate(r.wd)
                    monday = str(frappe.utils.add_days(wd0, -wd0.weekday()))
                    wp = weeks_pay.get(monday) or {"v": 0.0, "vd": 0.0}
                    wp["v"] = wp["v"] + amt
                    wp["vd"] = wp["vd"] + amt * dd
                    weeks_pay[monday] = wp
            if r.conf_d and r.wd:
                dc = frappe.utils.date_diff(r.conf_d, r.wd)
                if dc >= 0:
                    v_conf = v_conf + amt
                    vd_conf = vd_conf + amt * dc
        # confirmed-but-unpaid backlog also has an implicit wait (still counting)
        out["speed"] = {
            "days_to_pay": (vd_pay / v_all) if v_all else None,
            "days_to_confirm": (vd_conf / v_conf) if v_conf else None,
            "paid_value": v_all,
            "farms": sorted([{"farm": f, "days": farm_pay[f]["vd"] / farm_pay[f]["v"]}
                             for f in farm_pay if farm_pay[f]["v"]], key=lambda x: x["days"]),
            "weekly": [{"wstart": k, "days": weeks_pay[k]["vd"] / weeks_pay[k]["v"]}
                       for k in sorted(weeks_pay) if weeks_pay[k]["v"]],
        }

        # ---- 3 · APPROVER DESKS: throughput & value, no stopwatch ----
        desks = {}
        names2 = {}

        def desk_add(dtype, statefilter, who_field, val_field, when_fields, unpaid_flag):
            am = frappe.get_meta(dtype)
            if not am.get_field(who_field):
                return
            fields = ["name", "creation", who_field, val_field]
            for f in when_fields:
                if am.get_field(f):
                    fields.append(f)
            if am.get_field("paid"):
                fields.append("paid")
            rows = frappe.db.get_all(dtype, filters=statefilter, fields=list(set(fields)), limit=5000)
            for r in rows:
                who = r.get(who_field)
                if not who:
                    continue
                when = None
                for f in when_fields:
                    if r.get(f):
                        when = r.get(f)
                        break
                if not when:
                    when = r.get("creation")
                wd = str(frappe.utils.get_datetime(when).date())
                if wd < str(kfrom) or wd > str(kto):
                    continue
                dk = desks.get(who)
                if not dk:
                    dk = {"who": who, "n": 0, "value": 0.0, "weeks": {}, "unpaid_signed": 0.0, "groups": {}}
                    desks[who] = dk
                v = frappe.utils.flt(r.get(val_field))
                dk["n"] = dk["n"] + 1
                dk["value"] = dk["value"] + v
                dk["groups"][dtype] = 1
                d0 = frappe.utils.getdate(wd)
                monday = str(frappe.utils.add_days(d0, -d0.weekday()))
                wkk = dk["weeks"].get(monday) or {"n": 0, "v": 0.0}
                wkk["n"] = wkk["n"] + 1
                wkk["v"] = wkk["v"] + v
                dk["weeks"][monday] = wkk
                if unpaid_flag and not frappe.utils.cint(r.get("paid")):
                    dk["unpaid_signed"] = dk["unpaid_signed"] + v
                if who not in names2:
                    names2[who] = frappe.db.get_value("User", who, "full_name") or who

        desk_add("Work Management Planner", {"approved_by": ["is", "set"]}, "approved_by",
                 "total_cost", ["custom_approved_at", "approval_date"], False)
        desk_add("Work Management Assigner", {"approved_by": ["is", "set"]}, "approved_by",
                 "planned_cost", ["custom_gm_approved_at", "approval_date"], False)
        desk_add("Work Management Actuals", {"gm_approved_by": ["is", "set"]}, "gm_approved_by",
                 "total_payment", ["custom_gm_approved_at", "gm_approval_date"], True)
        desk_add("Work Management Actuals", {"hr_approved_by": ["is", "set"]}, "hr_approved_by",
                 "total_payment", ["custom_hr_approved_at", "hr_approval_date"], False)
        desk_add("Work Management Payment", {"accounts_approved_by": ["is", "set"]}, "accounts_approved_by",
                 "grand_total", ["custom_accounts_approved_at", "accounts_approval_date"], False)
        GLBL = {"Work Management Planner": "Plans", "Work Management Assigner": "Assignments",
                "Work Management Actuals": "Actuals", "Work Management Payment": "Payments"}
        dlist = []
        this_monday = str(frappe.utils.add_days(frappe.utils.getdate(today_s),
                                                -frappe.utils.getdate(today_s).weekday()))
        for who in desks:
            dk = desks[who]
            weekly = [{"wstart": k, "n": dk["weeks"][k]["n"], "v": dk["weeks"][k]["v"]}
                      for k in sorted(dk["weeks"])]
            tw = dk["weeks"].get(this_monday) or {"n": 0, "v": 0.0}
            dlist.append({"who": who, "name": names2.get(who) or who,
                          "n": dk["n"], "value": dk["value"],
                          "week_n": tw["n"], "week_v": tw["v"],
                          "unpaid_signed": dk["unpaid_signed"],
                          "weekly": weekly,
                          "groups": sorted([GLBL.get(g, g) for g in dk["groups"]])})
        dlist = sorted(dlist, key=lambda x: x["value"], reverse=True)
        out["desks"] = dlist
        # rejections per stage (attribution to a person is not stored — stage level)
        # ---- 4 · PER-STAGE APPROVER BARS: who signs what, at every stage ----
        stages_out = []

        def stage_bars(stage_label, dtype, who_field, val_field, when_fields, start_fields):
            am = frappe.get_meta(dtype)
            if not am.get_field(who_field):
                return
            fields = ["name", "creation", who_field, val_field]
            for f in when_fields + start_fields:
                if am.get_field(f):
                    fields.append(f)
            rows = frappe.db.get_all(dtype, filters={who_field: ["is", "set"]},
                                     fields=list(set(fields)), limit=5000)
            agg = {}
            for r in rows:
                who = r.get(who_field)
                if not who:
                    continue
                when = None
                for f in when_fields:
                    if r.get(f):
                        when = r.get(f)
                        break
                if not when:
                    when = r.get("creation")
                wd = str(frappe.utils.get_datetime(when).date())
                if wd < str(kfrom) or wd > str(kto):
                    continue
                g = agg.get(who) or {"n": 0, "v": 0.0, "hsum": 0.0, "hn": 0}
                g["n"] = g["n"] + 1
                g["v"] = g["v"] + frappe.utils.flt(r.get(val_field))
                start = None
                for f in start_fields:
                    if r.get(f):
                        start = r.get(f)
                        break
                if not start:
                    start = r.get("creation")
                hh = None
                try:
                    hh = (frappe.utils.get_datetime(when) - frappe.utils.get_datetime(start)).total_seconds() / 3600.0
                except Exception:
                    hh = None
                if hh is not None and hh >= 0:
                    g["hsum"] = g["hsum"] + hh
                    g["hn"] = g["hn"] + 1
                agg[who] = g
            aps = []
            for who in agg:
                nm = frappe.db.get_value("User", who, "full_name") or who
                aps.append({"who": who, "name": nm, "n": agg[who]["n"], "value": agg[who]["v"],
                            "avg_h": (agg[who]["hsum"] / agg[who]["hn"]) if agg[who]["hn"] else None})
            aps = sorted(aps, key=lambda x: x["n"], reverse=True)
            stages_out.append({"stage": stage_label, "approvers": aps,
                               "total_n": sum(x["n"] for x in aps),
                               "total_v": sum(x["value"] for x in aps)})

        stage_bars("Plan approval — Farm Manager", "Work Management Planner",
                   "approved_by", "total_cost", ["custom_approved_at", "approval_date"],
                   ["custom_submitted_at"])
        stage_bars("Assignment approval — GM", "Work Management Assigner",
                   "approved_by", "planned_cost", ["custom_gm_approved_at", "approval_date"],
                   ["custom_submitted_at"])
        stage_bars("Actuals — FM sign-off", "Work Management Actuals",
                   "fm_approved_by", "total_payment", ["custom_fm_approved_at", "fm_approval_date"],
                   ["custom_submitted_at"])
        stage_bars("Actuals — HR sign-off", "Work Management Actuals",
                   "hr_approved_by", "total_payment", ["custom_hr_approved_at", "hr_approval_date"],
                   ["custom_fm_approved_at", "custom_submitted_at"])
        stage_bars("Actuals — GM confirmation", "Work Management Actuals",
                   "gm_approved_by", "total_payment", ["custom_gm_approved_at", "gm_approval_date"],
                   ["custom_hr_approved_at", "custom_fm_approved_at", "custom_submitted_at"])
        stage_bars("Payment — accounts release", "Work Management Payment",
                   "accounts_approved_by", "grand_total", ["custom_accounts_approved_at", "accounts_approval_date"],
                   ["custom_submitted_at"])
        out["stages"] = stages_out

        out["rejected"] = {
            "plans": frappe.db.count("Work Management Planner", {"workflow_state": "Rejected"}),
            "assignments": frappe.db.count("Work Management Assigner", {"workflow_state": "Rejected"}),
            "actuals": frappe.db.count("Work Management Actuals", {"workflow_state": "Rejected"}),
        }
        out["window"] = {"from": str(kfrom), "to": str(kto)}

    elif action == "approver_kpis":
        # Per-approver sign-off KPIs from the hour-level stage timestamps
        # (custom_submitted_at → FM → HR → GM / accounts), plus the live backlog
        # sitting at every sign-off queue. Powers the Approver KPIs board.
        now_dt = frappe.utils.now_datetime()
        kfrom = frappe.form_dict.get("from_date") or frappe.utils.add_days(frappe.utils.today(), -83)
        kto = frappe.form_dict.get("to_date") or frappe.utils.today()
        events = []

        def hours_between(a, b):
            try:
                if not a or not b:
                    return None
                h = (frappe.utils.get_datetime(b) - frappe.utils.get_datetime(a)).total_seconds() / 3600.0
                return h if h >= 0 else 0.0
            except Exception:
                return None

        def collect(dtype, statefilter, who_field, start_fields, end_fields, step, group):
            am = frappe.get_meta(dtype)
            if not am.get_field(who_field):
                return
            fields = ["name", "creation", who_field]
            for f in start_fields + end_fields:
                if am.get_field(f):
                    fields.append(f)
            if am.get_field("farm"):
                fields.append("farm")
            rows = frappe.db.get_all(dtype, filters=statefilter, fields=list(set(fields)), limit=5000)
            for r in rows:
                who = r.get(who_field)
                if not who:
                    continue
                start = None
                for f in start_fields:
                    if r.get(f):
                        start = r.get(f)
                        break
                if not start:
                    start = r.get("creation")
                end = None
                for f in end_fields:
                    if r.get(f):
                        end = r.get(f)
                        break
                h = hours_between(start, end)
                if h is None:
                    continue
                endd = str(frappe.utils.get_datetime(end).date())
                if endd < str(kfrom) or endd > str(kto):
                    continue
                events.append({"who": who, "step": step, "group": group, "h": h,
                               "doc": r.get("name"), "farm": r.get("farm"), "end": endd})

        collect("Work Management Planner", {"approved_by": ["is", "set"]}, "approved_by",
                ["custom_submitted_at"], ["custom_approved_at", "approval_date"],
                "Plan approval", "Work plans")
        collect("Work Management Assigner", {"approved_by": ["is", "set"]}, "approved_by",
                ["custom_submitted_at"], ["custom_gm_approved_at", "approval_date"],
                "Assignment approval", "Assignments")
        collect("Work Management Actuals", {"fm_approved_by": ["is", "set"]}, "fm_approved_by",
                ["custom_submitted_at"], ["custom_fm_approved_at"],
                "Actuals FM", "Work records")
        collect("Work Management Actuals", {"hr_approved_by": ["is", "set"]}, "hr_approved_by",
                ["custom_fm_approved_at", "custom_submitted_at"], ["custom_hr_approved_at", "hr_approval_date"],
                "Actuals HR", "Work records")
        collect("Work Management Actuals", {"gm_approved_by": ["is", "set"]}, "gm_approved_by",
                ["custom_hr_approved_at", "custom_fm_approved_at", "custom_submitted_at"],
                ["custom_gm_approved_at", "gm_approval_date"],
                "Actuals GM", "Work records")
        collect("Work Management Payment", {"accounts_approved_by": ["is", "set"]}, "accounts_approved_by",
                ["custom_submitted_at", "creation"], ["custom_accounts_approved_at", "accounts_approval_date"],
                "Accounts release", "Payments")

        per = {}
        allh = []
        for e in events:
            allh.append(e["h"])
            pp = per.get(e["who"])
            if not pp:
                pp = {"who": e["who"], "n": 0, "hsum": 0.0, "hs": [], "b0": 0, "b1": 0, "b2": 0,
                      "mx": 0.0, "mx_doc": None, "steps": {}, "weeks": {}, "farms": {}}
                per[e["who"]] = pp
            pp["n"] = pp["n"] + 1
            pp["hsum"] = pp["hsum"] + e["h"]
            pp["hs"].append(e["h"])
            if e["h"] < 24:
                pp["b0"] = pp["b0"] + 1
            elif e["h"] <= 72:
                pp["b1"] = pp["b1"] + 1
            else:
                pp["b2"] = pp["b2"] + 1
            if e["h"] > pp["mx"]:
                pp["mx"] = e["h"]
                pp["mx_doc"] = e["doc"]
            st = pp["steps"].get(e["step"]) or {"n": 0, "hsum": 0.0}
            st["n"] = st["n"] + 1
            st["hsum"] = st["hsum"] + e["h"]
            pp["steps"][e["step"]] = st
            wd = frappe.utils.getdate(e["end"])
            monday = str(frappe.utils.add_days(wd, -wd.weekday()))
            wk = pp["weeks"].get(monday) or {"n": 0, "hsum": 0.0}
            wk["n"] = wk["n"] + 1
            wk["hsum"] = wk["hsum"] + e["h"]
            pp["weeks"][monday] = wk
            if e.get("farm"):
                pp["farms"][e["farm"]] = 1

        aprs = []
        for who in per:
            pp = per[who]
            hs = sorted(pp["hs"])
            n = len(hs)
            med = hs[n // 2] if n % 2 else (hs[n // 2 - 1] + hs[n // 2]) / 2.0
            weekly = [{"wstart": k, "n": pp["weeks"][k]["n"],
                       "avg_h": pp["weeks"][k]["hsum"] / pp["weeks"][k]["n"]} for k in sorted(pp["weeks"])]
            steps = [{"step": k, "n": pp["steps"][k]["n"],
                      "avg_h": pp["steps"][k]["hsum"] / pp["steps"][k]["n"]} for k in sorted(pp["steps"])]
            aprs.append({"who": who,
                         "name": frappe.db.get_value("User", who, "full_name") or who,
                         "n": pp["n"], "avg_h": pp["hsum"] / pp["n"], "med_h": med,
                         "b0": pp["b0"], "b1": pp["b1"], "b2": pp["b2"],
                         "mx_h": pp["mx"], "mx_doc": pp["mx_doc"],
                         "steps": steps, "weekly": weekly, "farms": sorted(pp["farms"].keys())})
        aprs = sorted(aprs, key=lambda x: x["med_h"])
        out["approvers"] = aprs
        allh = sorted(allh)
        out["team_med_h"] = (allh[len(allh) // 2] if len(allh) % 2 else
                             (allh[len(allh) // 2 - 1] + allh[len(allh) // 2]) / 2.0) if allh else 0
        out["events_n"] = len(events)

        queues = []

        def qcount(dtype, state, label, start_fields):
            am = frappe.get_meta(dtype)
            fields = ["name", "creation"]
            for f in start_fields:
                if am.get_field(f):
                    fields.append(f)
            rows = frappe.db.get_all(dtype, filters={"workflow_state": state},
                                     fields=list(set(fields)), limit=2000)
            ages = []
            for r in rows:
                st = None
                for f in start_fields:
                    if r.get(f):
                        st = r.get(f)
                        break
                if not st:
                    st = r.get("creation")
                h = hours_between(st, now_dt)
                if h is not None:
                    ages.append(h)
            fresh = len([a for a in ages if a < 24])
            mid = len([a for a in ages if 24 <= a <= 72])
            old = len([a for a in ages if a > 72])
            queues.append({"label": label, "count": len(rows),
                           "avg_h": (sum(ages) / len(ages)) if ages else 0,
                           "fresh": fresh, "mid": mid, "old": old})

        qcount("Work Management Planner", "Pending Approval", "Plans → Farm Manager", ["custom_submitted_at"])
        qcount("Work Management Assigner", "Pending Farm Manager", "Assignments → FM", ["custom_submitted_at"])
        qcount("Work Management Assigner", "Pending HR Head", "Assignments → HR", ["custom_fm_approved_at", "custom_submitted_at"])
        qcount("Work Management Assigner", "Pending GM", "Assignments → GM", ["custom_hr_approved_at", "custom_submitted_at"])
        qcount("Work Management Actuals", "Pending Farm Manager", "Actuals → FM", ["custom_submitted_at"])
        qcount("Work Management Actuals", "Pending HR Head", "Actuals → HR", ["custom_fm_approved_at", "custom_submitted_at"])
        qcount("Work Management Actuals", "Pending GM", "Actuals → GM", ["custom_hr_approved_at", "custom_submitted_at"])
        qcount("Work Management Payment", "Pending Accounts", "Payments → Accounts", ["custom_submitted_at", "creation"])
        out["queues"] = queues
        out["window"] = {"from": str(kfrom), "to": str(kto)}

    elif action == "cost_center":
        # Block-as-cost-centre ranking: which block consumes the most money.
        # Two money columns side by side: labour spend (from confirmed actuals) and GL
        # cost-centre actuals (posted accounting, if the block maps to a Cost Center).
        ccfarm = frappe.form_dict.get("farm")
        ccfrom = frappe.form_dict.get("from_date")
        ccto = frappe.form_dict.get("to_date")
        ccq = (frappe.form_dict.get("q") or "").strip().lower()
        conds = "ac.workflow_state='CONFIRMED' AND ac.block_section IS NOT NULL"
        params = []
        if ccfarm:
            conds = conds + " AND ac.farm = %s"
            params.append(ccfarm)
        if ccfrom:
            conds = conds + " AND we.work_date >= %s"
            params.append(ccfrom)
        if ccto:
            conds = conds + " AND we.work_date <= %s"
            params.append(ccto)
        labour = frappe.db.sql("""
            SELECT ac.block_section block, ac.farm farm,
                   COALESCE(SUM(we.amount),0) labour_spend,
                   COALESCE(SUM(we.actual_quantity),0) qty,
                   COUNT(DISTINCT we.employee) workers,
                   COUNT(DISTINCT ac.task) tasks,
                   COUNT(*) worker_days,
                   COUNT(DISTINCT we.work_date) days_active,
                   MIN(we.work_date) first_day,
                   MAX(we.work_date) last_day
            FROM `tabWork Actuals Employee` we
            INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
            WHERE """ + conds + """
            GROUP BY ac.block_section, ac.farm
            ORDER BY labour_spend DESC
        """, tuple(params), as_dict=True)
        # weekly spend per block (for sparklines) - one query, bucketed by ISO week Monday
        wk = frappe.db.sql("""
            SELECT ac.block_section block,
                   YEARWEEK(we.work_date, 3) yw,
                   MIN(we.work_date) wk_any,
                   COALESCE(SUM(we.amount),0) pay
            FROM `tabWork Actuals Employee` we
            INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
            WHERE """ + conds + """
            GROUP BY ac.block_section, YEARWEEK(we.work_date, 3)
            ORDER BY yw
        """, tuple(params), as_dict=True)
        trend = {}
        for w in wk:
            key = w.block
            lst = trend.get(key)
            if not lst:
                lst = []
                trend[key] = lst
            d0 = frappe.utils.getdate(w.wk_any)
            monday = frappe.utils.add_days(d0, -d0.weekday())
            lst.append({"w": str(monday), "pay": frappe.utils.flt(w.pay)})
        # resolve GL cost-centre actuals per block (direct Cost Center name match, or via Warehouse.cost_center)
        has_gl = frappe.get_meta("GL Entry").get_field("cost_center") is not None
        wh_has_cc = frappe.get_meta("Warehouse").get_field("cost_center") is not None
        rows = []
        tot_labour = 0
        tot_gl = 0
        tot_qty = 0
        tot_wd = 0
        for r in labour:
            if ccq and ccq not in str(r.block).lower():
                continue
            gl_spend = 0
            cc = None
            if has_gl and r.block:
                # block_section values are the CC 'name' (e.g. 'A4 - KL'); match that first,
                # then fall back to cost_center_name, then Warehouse.cost_center.
                if frappe.db.exists("Cost Center", r.block):
                    cc = r.block
                if not cc:
                    cc = frappe.db.get_value("Cost Center", {"cost_center_name": r.block}, "name")
                if not cc and wh_has_cc and frappe.db.exists("Warehouse", r.block):
                    cc = frappe.db.get_value("Warehouse", r.block, "cost_center")
                if cc:
                    glconds = "cost_center = %s AND is_cancelled = 0"
                    glparams = [cc]
                    if ccfrom:
                        glconds = glconds + " AND posting_date >= %s"
                        glparams.append(ccfrom)
                    if ccto:
                        glconds = glconds + " AND posting_date <= %s"
                        glparams.append(ccto)
                    glrow = frappe.db.sql("""
                        SELECT COALESCE(SUM(debit),0) dr FROM `tabGL Entry` WHERE """ + glconds,
                        tuple(glparams), as_dict=True)
                    gl_spend = frappe.utils.flt(glrow[0].dr) if glrow else 0
            lspend = frappe.utils.flt(r.labour_spend)
            qty = frappe.utils.flt(r.qty)
            wd = frappe.utils.cint(r.worker_days)
            days_active = frappe.utils.cint(r.days_active)
            # derived efficiency metrics
            cost_per_unit = (lspend / qty) if qty > 0 else None
            cost_per_wd = (lspend / wd) if wd > 0 else None
            avg_crew = (float(wd) / days_active) if days_active > 0 else None
            # labour as a share of GL posted cost (variance signal)
            labour_share = (lspend / gl_spend * 100) if gl_spend > 0 else None
            rows.append({
                "block": r.block, "farm": r.farm,
                "labour_spend": lspend,
                "gl_spend": gl_spend, "cost_center": cc,
                "qty": qty, "workers": frappe.utils.cint(r.workers),
                "tasks": frappe.utils.cint(r.tasks), "worker_days": wd,
                "days_active": days_active,
                "first_day": str(r.first_day) if r.first_day else None,
                "last_day": str(r.last_day) if r.last_day else None,
                "cost_per_unit": cost_per_unit,
                "cost_per_wd": cost_per_wd,
                "avg_crew": avg_crew,
                "labour_share": labour_share,
                "trend": trend.get(r.block, [])
            })
            tot_labour = tot_labour + lspend
            tot_gl = tot_gl + gl_spend
            tot_qty = tot_qty + qty
            tot_wd = tot_wd + wd
        # farm-level subtotals for the grouped view
        farm_tot = {}
        for r in rows:
            g = farm_tot.get(r["farm"])
            if not g:
                g = {"farm": r["farm"], "labour": 0, "gl": 0, "qty": 0, "worker_days": 0, "blocks": 0}
                farm_tot[r["farm"]] = g
            g["labour"] = g["labour"] + r["labour_spend"]
            g["gl"] = g["gl"] + r["gl_spend"]
            g["qty"] = g["qty"] + r["qty"]
            g["worker_days"] = g["worker_days"] + r["worker_days"]
            g["blocks"] = g["blocks"] + 1
        farm_rows = []
        for k in farm_tot:
            g = farm_tot[k]
            g["cost_per_unit"] = (g["labour"] / g["qty"]) if g["qty"] > 0 else None
            farm_rows.append(g)
        farm_rows = sorted(farm_rows, key=lambda x: x["labour"], reverse=True)
        # portfolio medians for colour-coding efficiency
        cpu_list = sorted([r["cost_per_unit"] for r in rows if r["cost_per_unit"] is not None])
        med_cpu = None
        if cpu_list:
            mid = len(cpu_list) // 2
            med_cpu = cpu_list[mid] if len(cpu_list) % 2 == 1 else (cpu_list[mid - 1] + cpu_list[mid]) / 2.0
        out["blocks"] = rows
        out["farm_totals"] = farm_rows
        out["totals"] = {"labour": tot_labour, "gl": tot_gl, "blocks": len(rows),
            "qty": tot_qty, "worker_days": tot_wd,
            "cost_per_unit": (tot_labour / tot_qty) if tot_qty > 0 else None,
            "median_cost_per_unit": med_cpu, "has_gl": 1 if has_gl else 0}
        out["farms"] = FARMS

    elif action == "cost_center_detail":
        # For one block: tasks in it AND workers on it (both tables), same filters.
        ccblock = frappe.form_dict.get("block")
        ccfarm = frappe.form_dict.get("farm")
        ccfrom = frappe.form_dict.get("from_date")
        ccto = frappe.form_dict.get("to_date")
        conds = "ac.workflow_state='CONFIRMED' AND ac.block_section = %s"
        params = [ccblock]
        if ccfarm:
            conds = conds + " AND ac.farm = %s"
            params.append(ccfarm)
        if ccfrom:
            conds = conds + " AND we.work_date >= %s"
            params.append(ccfrom)
        if ccto:
            conds = conds + " AND we.work_date <= %s"
            params.append(ccto)
        tasks = frappe.db.sql("""
            SELECT ac.task label,
                   COALESCE(SUM(we.amount),0) spend,
                   COALESCE(SUM(we.actual_quantity),0) qty,
                   COUNT(DISTINCT we.employee) workers,
                   COUNT(*) worker_days
            FROM `tabWork Actuals Employee` we
            INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
            WHERE """ + conds + """
            GROUP BY ac.task ORDER BY spend DESC
        """, tuple(params), as_dict=True)
        workers = frappe.db.sql("""
            SELECT we.employee emp, we.employee_name nm,
                   COALESCE(SUM(we.amount),0) spend,
                   COALESCE(SUM(we.actual_quantity),0) qty,
                   COUNT(DISTINCT we.work_date) days,
                   COUNT(DISTINCT ac.task) tasks
            FROM `tabWork Actuals Employee` we
            INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
            WHERE """ + conds + """
            GROUP BY we.employee, we.employee_name ORDER BY spend DESC
        """, tuple(params), as_dict=True)
        # weekly labour trend for this block
        wkd = frappe.db.sql("""
            SELECT YEARWEEK(we.work_date, 3) yw, MIN(we.work_date) wk_any,
                   COALESCE(SUM(we.amount),0) pay,
                   COALESCE(SUM(we.actual_quantity),0) qty,
                   COUNT(DISTINCT we.employee) workers
            FROM `tabWork Actuals Employee` we
            INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
            WHERE """ + conds + """
            GROUP BY YEARWEEK(we.work_date, 3) ORDER BY yw
        """, tuple(params), as_dict=True)
        weekly = []
        for w in wkd:
            d0 = frappe.utils.getdate(w.wk_any)
            monday = frappe.utils.add_days(d0, -d0.weekday())
            weekly.append({"w": str(monday), "pay": frappe.utils.flt(w.pay),
                "qty": frappe.utils.flt(w.qty), "workers": frappe.utils.cint(w.workers)})
        # GL account breakdown for this block's cost centre (labour vs materials vs other)
        gl_accounts = []
        gl_total = 0
        has_gl = frappe.get_meta("GL Entry").get_field("cost_center") is not None
        if has_gl and ccblock:
            cc = None
            if frappe.db.exists("Cost Center", ccblock):
                cc = ccblock
            if not cc:
                cc = frappe.db.get_value("Cost Center", {"cost_center_name": ccblock}, "name")
            if cc:
                glconds2 = "gl.cost_center = %s AND gl.is_cancelled = 0"
                glparams2 = [cc]
                if ccfrom:
                    glconds2 = glconds2 + " AND gl.posting_date >= %s"
                    glparams2.append(ccfrom)
                if ccto:
                    glconds2 = glconds2 + " AND gl.posting_date <= %s"
                    glparams2.append(ccto)
                gla = frappe.db.sql("""
                    SELECT gl.account account, COALESCE(SUM(gl.debit),0) dr,
                           COALESCE(a.root_type,'') root_type
                    FROM `tabGL Entry` gl
                    LEFT JOIN `tabAccount` a ON a.name = gl.account
                    WHERE """ + glconds2 + """
                    GROUP BY gl.account HAVING dr <> 0 ORDER BY dr DESC LIMIT 40
                """, tuple(glparams2), as_dict=True)
                for x in gla:
                    amt = frappe.utils.flt(x.dr)
                    gl_accounts.append({"account": x.account, "amount": amt, "root_type": x.root_type})
                    gl_total = gl_total + amt
        out["block"] = ccblock
        out["tasks"] = [{"label": t.label, "spend": frappe.utils.flt(t.spend),
            "qty": frappe.utils.flt(t.qty), "workers": frappe.utils.cint(t.workers),
            "worker_days": frappe.utils.cint(t.worker_days),
            "cost_per_unit": (frappe.utils.flt(t.spend) / frappe.utils.flt(t.qty)) if frappe.utils.flt(t.qty) > 0 else None} for t in tasks]
        out["workers"] = [{"emp": w.emp, "nm": w.nm, "spend": frappe.utils.flt(w.spend),
            "qty": frappe.utils.flt(w.qty), "days": frappe.utils.cint(w.days),
            "tasks": frappe.utils.cint(w.tasks),
            "cost_per_unit": (frappe.utils.flt(w.spend) / frappe.utils.flt(w.qty)) if frappe.utils.flt(w.qty) > 0 else None} for w in workers]
        out["weekly"] = weekly
        out["gl_accounts"] = gl_accounts
        out["gl_total"] = gl_total

    else:
        out["error"] = "unknown action: " + str(action)


    return out
