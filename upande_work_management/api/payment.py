# Ported from Kaitet live Server Script "wm_payment" (API) — logic unchanged.
# Farms / projects / company / approver roles now come from Work Management Settings
# (falls back to the original Kaitet defaults) — see upande_work_management/api/config.py.

import frappe

from upande_work_management.api.config import get_config


@frappe.whitelist()
def wm_payment(**kwargs):
    _cfg = get_config()
    FARM_PROJECT = _cfg["farm_project"]
    DEFAULT_COMPANY = _cfg["default_company"]
    FARMS = _cfg["farms"]
    BLOCK_EXCLUDE = _cfg["block_exclude"]
    FARM_APPROVER_ROLE = _cfg["farm_approver_role"]

    # ==================================================================
    # SERVER SCRIPT — "WM Payment" (API, api_method=wm_payment)
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
    if action == "pay_confirmed":
        rows = frappe.db.get_all("Work Management Actuals",
            filters={"workflow_state":"CONFIRMED","paid":0},
            fields=["name","farm","task","block_section","payroll_people","total_payment","entry_date"],
            order_by="farm", limit=500)
        out["actuals"] = rows

    elif action == "pay_submit":
        # Worker-centric: pay a list of employees. Each becomes ONE payment line summarising
        # their unpaid confirmed earnings; on mark-paid we stamp their individual rows.
        title = frappe.form_dict.get("title")
        workers_raw = frappe.form_dict.get("workers")
        submit_now = frappe.form_dict.get("submit_now")
        dfrom = frappe.form_dict.get("from_date")
        dto = frappe.form_dict.get("to_date")
        err = None
        emp_list = []
        if workers_raw:
            for e in workers_raw.split(","):
                ev = e.strip()
                if ev and ev not in emp_list:
                    emp_list.append(ev)
        if not emp_list: err = "Select at least one worker to pay"
        if err:
            out["error"] = err
        else:
            d = frappe.new_doc("Work Management Payment")
            d.run_title = title or ("Payment run " + frappe.utils.today())
            d.company = DEFAULT_COMPANY
            d.run_date = frappe.utils.today()
            d.prepared_by = frappe.session.user
            # store the window if the fields exist (safe: set_value later per-row anyway)
            try:
                if dfrom:
                    d.period_from = dfrom
                if dto:
                    d.period_to = dto
            except Exception:
                pass
            gt = 0
            cnt = 0
            for emp in emp_list:
                aconds = "we.employee=%s AND ac.workflow_state='CONFIRMED' AND IFNULL(we.paid,0)=0 AND IFNULL(we.count_in_payroll,0)=1 AND we.amount>0"
                aparams = [emp]
                if dfrom:
                    aconds = aconds + " AND we.work_date >= %s"
                    aparams.append(dfrom)
                if dto:
                    aconds = aconds + " AND we.work_date <= %s"
                    aparams.append(dto)
                agg = frappe.db.sql("""
                    SELECT we.employee_name nm, ac.farm farm,
                           COUNT(DISTINCT we.work_date) days,
                           COALESCE(SUM(we.actual_quantity),0) qty,
                           COALESCE(SUM(we.amount),0) owed
                    FROM `tabWork Actuals Employee` we
                    INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
                    WHERE """ + aconds + """
                """, tuple(aparams), as_dict=True)
                if not agg or frappe.utils.flt(agg[0].owed) <= 0:
                    continue
                g = agg[0]
                row = d.append("lines", {})
                row.employee = emp
                row.employee_name = g.nm
                row.farm = g.farm
                row.days = g.days
                row.qty = g.qty
                row.paid_workers = 1
                row.amount = frappe.utils.flt(g.owed)
                gt = gt + frappe.utils.flt(g.owed)
                cnt = cnt + 1
            d.grand_total = gt
            d.total_workers = cnt
            d.total_actuals = cnt
            d.flags.ignore_permissions = True
            d.insert(ignore_permissions=True)
            if submit_now:
                frappe.db.set_value("Work Management Payment", d.name, "workflow_state", "Pending Accounts", update_modified=False)
                d.workflow_state = "Pending Accounts"
            out["name"] = d.name
            out["workflow_state"] = d.workflow_state
            out["grand_total"] = d.grand_total
            out["total_workers"] = cnt

    elif action == "pay_workers":
        # Worker-centric. Optional: farms (CSV) + date range (filters payable work_days).
        # include_all=1 -> return EVERY confirmed worker in range with a status (Unpaid/Submitted/Paid)
        #                  and the run ref; paid/submitted rows are shown but not payable.
        farms_raw = frappe.form_dict.get("farms")
        dfrom = frappe.form_dict.get("from_date")
        dto = frappe.form_dict.get("to_date")
        include_all = frappe.form_dict.get("include_all")
        conds = "ac.workflow_state='CONFIRMED' AND IFNULL(we.count_in_payroll,0)=1 AND we.amount>0"
        if not include_all:
            conds = conds + " AND IFNULL(we.paid,0)=0"
        params = []
        farm_list = []
        if farms_raw:
            for f in farms_raw.split(","):
                fv = f.strip()
                if fv:
                    farm_list.append(fv)
        if farm_list:
            ph = ",".join(["%s"] * len(farm_list))
            conds = conds + " AND ac.farm IN (" + ph + ")"
            for fv in farm_list:
                params.append(fv)
        if dfrom:
            conds = conds + " AND we.work_date >= %s"
            params.append(dfrom)
        if dto:
            conds = conds + " AND we.work_date <= %s"
            params.append(dto)
        rows = frappe.db.sql("""
            SELECT we.employee emp, we.employee_name emp_name, ac.farm farm,
                   COUNT(DISTINCT we.work_date) days,
                   MIN(we.work_date) wfrom, MAX(we.work_date) wto,
                   COALESCE(SUM(we.actual_quantity),0) qty,
                   COALESCE(SUM(we.amount),0) owed,
                   COALESCE(SUM(CASE WHEN IFNULL(we.paid,0)=0 THEN we.amount ELSE 0 END),0) unpaid_amt,
                   COALESCE(SUM(CASE WHEN IFNULL(we.paid,0)=0 AND IFNULL(we.custom_reviewed,0)=0 THEN we.amount ELSE 0 END),0) unreviewed_amt,
                   COUNT(DISTINCT ac.name) docs,
                   MIN(IFNULL(we.paid,0)) min_paid,
                   MAX(IFNULL(we.paid,0)) max_paid,
                   MAX(we.payment_ref) run_ref
            FROM `tabWork Actuals Employee` we
            INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
            WHERE """ + conds + """
            GROUP BY we.employee, we.employee_name, ac.farm
            ORDER BY ac.farm, owed DESC
        """, tuple(params), as_dict=True)
        # derive status per worker
        for r in rows:
            rref = r.get("run_ref")
            runstate = None
            if rref:
                runstate = frappe.db.get_value("Work Management Payment", rref, "workflow_state")
            if r.get("max_paid") == 1 and r.get("min_paid") == 1:
                r["pay_status"] = "Paid"
            elif rref and runstate in ("Pending Accounts",):
                r["pay_status"] = "Sent to accounts"
            elif rref and runstate == "Paid" and frappe.utils.flt(r.get("unpaid_amt")) <= 0.001:
                r["pay_status"] = "Paid"
            elif r.get("max_paid") == 1 and frappe.utils.flt(r.get("unpaid_amt")) <= 0.001:
                r["pay_status"] = "Paid"
            elif frappe.utils.flt(r.get("unreviewed_amt")) <= 0.001:
                r["pay_status"] = "Reviewed"
            else:
                r["pay_status"] = "Unpaid"
            r["run_ref"] = rref or None
            r["wfrom"] = str(r.get("wfrom")) if r.get("wfrom") else None
            r["wto"] = str(r.get("wto")) if r.get("wto") else None
            r["payable"] = 1 if r["pay_status"] in ("Unpaid", "Reviewed") else 0
        out["workers"] = rows
        tot = 0
        for r in rows:
            if r.get("payable"):
                tot = tot + frappe.utils.flt(r.owed)
        out["grand_total"] = tot
        # ALL farms that have earnings in the same window (unpaid-only for the multi-select summary)
        fconds = "ac.workflow_state='CONFIRMED' AND IFNULL(we.paid,0)=0 AND IFNULL(we.count_in_payroll,0)=1 AND we.amount>0"
        fparams = []
        if dfrom:
            fconds = fconds + " AND we.work_date >= %s"
            fparams.append(dfrom)
        if dto:
            fconds = fconds + " AND we.work_date <= %s"
            fparams.append(dto)
        allfarms = frappe.db.sql("""
            SELECT ac.farm farm, COUNT(DISTINCT we.employee) workers, COALESCE(SUM(we.amount),0) owed
            FROM `tabWork Actuals Employee` we
            INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
            WHERE """ + fconds + """
            GROUP BY ac.farm ORDER BY ac.farm
        """, tuple(fparams), as_dict=True)
        out["farms"] = allfarms

    elif action == "pay_worker_detail":
        # One worker's completed jobs (per task/plan/day) that are confirmed + unpaid
        emp = frappe.form_dict.get("employee")
        dfrom = frappe.form_dict.get("from_date")
        dto = frappe.form_dict.get("to_date")
        jconds = "we.employee=%s AND ac.workflow_state='CONFIRMED' AND IFNULL(we.paid,0)=0 AND IFNULL(we.count_in_payroll,0)=1"
        jparams = [emp]
        if dfrom:
            jconds = jconds + " AND we.work_date >= %s"
            jparams.append(dfrom)
        if dto:
            jconds = jconds + " AND we.work_date <= %s"
            jparams.append(dto)
        jobs = frappe.db.sql("""
            SELECT ac.name actuals, ac.farm farm, ac.task task, ac.block_section block,
                   we.work_date wdate, we.actual_quantity qty, we.amount amount,
                   CASE WHEN IFNULL(we.actual_quantity,0) > 0
                        THEN we.amount / we.actual_quantity ELSE ac.rate END rate
            FROM `tabWork Actuals Employee` we
            INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
            WHERE """ + jconds + """
            ORDER BY we.work_date
        """, tuple(jparams), as_dict=True)
        empinfo = frappe.db.get_value("Employee", emp, ["employee_name","custom_farm"], as_dict=True)
        out["employee"] = emp
        out["employee_name"] = empinfo.employee_name if empinfo else emp
        out["jobs"] = jobs
        tot = 0
        days = {}
        for j in jobs:
            tot = tot + frappe.utils.flt(j.amount)
            days[str(j.wdate)] = 1
        out["total_owed"] = tot
        out["total_days"] = len(days)

    elif action == "pay_pending":
        out["pending"] = frappe.db.get_all("Work Management Payment",
            filters={"workflow_state":"Pending Accounts"},
            fields=["name","run_title","total_actuals","total_workers","grand_total","prepared_by","run_date"],
            order_by="run_date desc", limit=200)

    elif action == "pay_mark_paid":
        nm = frappe.form_dict.get("name")
        cur = frappe.db.get_value("Work Management Payment", nm,
            ["workflow_state","period_from","period_to"], as_dict=True)
        if not cur or cur.workflow_state != "Pending Accounts":
            out["error"] = "Not awaiting accounts (state: " + str(cur.workflow_state if cur else "not found") + ")"
        else:
            # finalise via direct writes (bypass workflow engine + doctype gate)
            frappe.db.set_value("Work Management Payment", nm, "workflow_state", "Paid", update_modified=False)
            frappe.db.set_value("Work Management Payment", nm, "docstatus", 1, update_modified=False)
            frappe.db.set_value("Work Management Payment", nm, "accounts_approved_by", frappe.session.user, update_modified=False)
            frappe.db.set_value("Work Management Payment", nm, "accounts_approval_date", frappe.utils.today(), update_modified=False)
            # stamp each paid worker's confirmed-unpaid rows as paid (row-level)
            touched_parents = {}
            pfrom = cur.period_from
            pto = cur.period_to
            # resolve the child doctype of the 'lines' table field (name varies)
            line_dt = None
            pmeta = frappe.get_meta("Work Management Payment")
            for f in pmeta.fields:
                if f.fieldtype == "Table" and f.fieldname == "lines":
                    line_dt = f.options
            lines = []
            if line_dt:
                lines = frappe.db.get_all(line_dt, filters={"parent": nm}, fields=["employee"])
            for ln in lines:
                emp = ln.employee
                if not emp:
                    continue
                rconds = "we.employee=%s AND ac.workflow_state='CONFIRMED' AND IFNULL(we.paid,0)=0 AND IFNULL(we.count_in_payroll,0)=1"
                rparams = [emp]
                if pfrom:
                    rconds = rconds + " AND we.work_date >= %s"
                    rparams.append(pfrom)
                if pto:
                    rconds = rconds + " AND we.work_date <= %s"
                    rparams.append(pto)
                payrows = frappe.db.sql("""
                    SELECT we.name rowname, we.parent parent
                    FROM `tabWork Actuals Employee` we
                    INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
                    WHERE """ + rconds + """
                """, tuple(rparams), as_dict=True)
                for pr in payrows:
                    frappe.db.set_value("Work Actuals Employee", pr.rowname, "paid", 1, update_modified=False)
                    frappe.db.set_value("Work Actuals Employee", pr.rowname, "payment_ref", nm, update_modified=False)
                    touched_parents[pr.parent] = 1
            # flip parent Actuals paid=1 only when ALL its payable rows are now paid
            for parent in touched_parents:
                unpaid = frappe.db.sql("""
                    SELECT COUNT(*) c FROM `tabWork Actuals Employee`
                    WHERE parent=%s AND IFNULL(count_in_payroll,0)=1 AND amount>0 AND IFNULL(paid,0)=0
                """, (parent,), as_dict=True)
                if unpaid and unpaid[0].c == 0:
                    frappe.db.set_value("Work Management Actuals", parent, "paid", 1, update_modified=False)
                    frappe.db.set_value("Work Management Actuals", parent, "payment_ref", nm, update_modified=False)
            frappe.db.commit()
            out["name"] = nm; out["workflow_state"] = "Paid"

    elif action == "pay_my":
        out["runs"] = frappe.db.get_all("Work Management Payment",
            filters={"prepared_by":frappe.session.user},
            fields=["name","run_title","total_actuals","total_workers","grand_total","workflow_state","run_date"],
            order_by="creation desc", limit=200)

    elif action == "pay_roles":
        rl = frappe.db.get_all("Has Role", filters={"parent": frappe.session.user}, pluck="role")
        is_acc = ("Accounts User" in rl) or ("Accounts Manager" in rl) or ("System Manager" in rl)
        out["user"] = frappe.session.user
        out["is_accounts"] = 1 if is_acc else 0

    elif action == "pay_audit":
        # Reconcile CONFIRMED actuals against assigner + payment, per task/block, for the range.
        dfrom = frappe.form_dict.get("from_date")
        dto = frappe.form_dict.get("to_date")
        farms_raw = frappe.form_dict.get("farms")
        farm_list = []
        if farms_raw:
            for f in farms_raw.split(","):
                fv = f.strip()
                if fv:
                    farm_list.append(fv)
        conds = "ac.workflow_state='CONFIRMED'"
        params = []
        if dfrom:
            conds = conds + " AND we.work_date >= %s"
            params.append(dfrom)
        if dto:
            conds = conds + " AND we.work_date <= %s"
            params.append(dto)
        if farm_list:
            ph = ",".join(["%s"] * len(farm_list))
            conds = conds + " AND ac.farm IN (" + ph + ")"
            for fv in farm_list:
                params.append(fv)
        # ---- SUMMARY: one row per actuals doc (task/block/assignment) ----
        summ = frappe.db.sql("""
            SELECT ac.name actuals, ac.farm farm, ac.task task, ac.block_section block,
                   ac.assignment assignment, ac.entry_date entry_date, ac.entered_by entered_by,
                   COUNT(DISTINCT we.employee) workers,
                   COUNT(*) worker_days,
                   COALESCE(SUM(we.actual_quantity),0) actual_qty,
                   COALESCE(SUM(we.amount),0) total_pay,
                   COALESCE(SUM(CASE WHEN IFNULL(we.paid,0)=1 THEN we.amount ELSE 0 END),0) paid_pay,
                   COALESCE(SUM(CASE WHEN IFNULL(we.paid,0)=0 THEN we.amount ELSE 0 END),0) unpaid_pay,
                   MAX(we.payment_ref) run_refs
            FROM `tabWork Actuals Employee` we
            INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
            WHERE """ + conds + """
            GROUP BY ac.name, ac.farm, ac.task, ac.block_section, ac.assignment, ac.entry_date, ac.entered_by
            ORDER BY ac.farm, total_pay DESC
        """, tuple(params), as_dict=True)
        sumrows = []
        t_tasks = 0
        t_qty = 0
        t_total = 0
        t_paid = 0
        t_unpaid = 0
        t_wdays = 0
        for s in summ:
            # enrich with assigner planned/assigned + plan link
            planned = 0
            assigned = 0
            variance = 0
            planner = None
            pfrom = None
            pto = None
            if s.assignment:
                ai = frappe.db.get_value("Work Management Assigner", s.assignment,
                    ["planned_people","assigned_count","variance","planner_request"], as_dict=True)
                if ai:
                    planned = frappe.utils.cint(ai.planned_people)
                    assigned = frappe.utils.cint(ai.assigned_count)
                    variance = frappe.utils.cint(ai.variance)
                    planner = ai.planner_request
            if planner:
                pd = frappe.db.get_value("Work Management Planner", planner, ["from_date","to_date"], as_dict=True)
                if pd:
                    pfrom = str(pd.from_date) if pd.from_date else None
                    pto = str(pd.to_date) if pd.to_date else None
            # pay status for the doc
            tot = frappe.utils.flt(s.total_pay)
            paid = frappe.utils.flt(s.paid_pay)
            unpaid = frappe.utils.flt(s.unpaid_pay)
            run_state = None
            if s.run_refs:
                run_state = frappe.db.get_value("Work Management Payment", s.run_refs, "workflow_state")
            if tot > 0 and paid >= tot - 0.001:
                pstat = "Paid"
            elif paid > 0:
                pstat = "Part paid"
            elif s.run_refs and run_state == "Pending Accounts":
                pstat = "In run (awaiting accounts)"
            else:
                pstat = "Unpaid"
            sumrows.append({
                "actuals": s.actuals, "farm": s.farm, "task": s.task, "block": s.block,
                "assignment": s.assignment, "planner_request": planner, "from_date": pfrom, "to_date": pto,
                "planned_people": planned, "assigned_count": assigned, "variance": variance,
                "actual_qty": frappe.utils.flt(s.actual_qty), "workers": frappe.utils.cint(s.workers),
                "worker_days": frappe.utils.cint(s.worker_days),
                "total_pay": tot, "paid_pay": paid, "unpaid_pay": unpaid,
                "pay_status": pstat, "run_refs": s.run_refs, "entered_by": s.entered_by,
                "entry_date": str(s.entry_date) if s.entry_date else None
            })
            t_tasks = t_tasks + 1
            t_qty = t_qty + frappe.utils.flt(s.actual_qty)
            t_total = t_total + tot
            t_paid = t_paid + paid
            t_unpaid = t_unpaid + unpaid
            t_wdays = t_wdays + frappe.utils.cint(s.worker_days)
        out["summary"] = sumrows
        # ---- DETAIL: one row per worker per day ----
        det = frappe.db.sql("""
            SELECT ac.farm farm, ac.task task, ac.block_section block, ac.assignment assignment,
                   we.employee emp, we.employee_name emp_name, we.employment_type emp_type,
                   we.work_date wdate, we.actual_quantity qty, we.amount amount,
                   IFNULL(we.count_in_payroll,0) in_payroll,
                   IFNULL(we.paid,0) paid, IFNULL(we.custom_reviewed,0) reviewed, we.payment_ref run_ref
            FROM `tabWork Actuals Employee` we
            INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
            WHERE """ + conds + """
            ORDER BY ac.farm, ac.task, we.employee_name, we.work_date
        """, tuple(params), as_dict=True)
        detrows = []
        for d in det:
            pstat = "Paid" if frappe.utils.cint(d.paid) == 1 else "Unpaid"
            detrows.append({
                "farm": d.farm, "task": d.task, "block": d.block, "assignment": d.assignment,
                "emp": d.emp, "emp_name": d.emp_name, "emp_type": d.emp_type,
                "wdate": str(d.wdate) if d.wdate else None,
                "qty": frappe.utils.flt(d.qty), "amount": frappe.utils.flt(d.amount),
                "in_payroll": frappe.utils.cint(d.in_payroll), "pay_status": pstat, "run_ref": d.run_ref,
                "reviewed": frappe.utils.cint(d.reviewed)
            })
        out["detail"] = detrows
        out["totals"] = {"tasks": t_tasks, "qty": t_qty, "total_pay": t_total,
                         "paid": t_paid, "unpaid": t_unpaid, "worker_days": t_wdays}

    elif action == "pay_insights":
        dfrom = frappe.form_dict.get("from_date")
        dto = frappe.form_dict.get("to_date")
        farm = frappe.form_dict.get("farm")
        conds = "ac.workflow_state='CONFIRMED'"
        params = []
        if dfrom:
            conds = conds + " AND we.work_date >= %s"
            params.append(dfrom)
        if dto:
            conds = conds + " AND we.work_date <= %s"
            params.append(dto)
        if farm:
            conds = conds + " AND ac.farm = %s"
            params.append(farm)
        # KPIs
        kp = frappe.db.sql("""
            SELECT COUNT(DISTINCT we.employee) active_workers,
                   COUNT(*) mandays,
                   COALESCE(SUM(we.amount),0) earned,
                   COALESCE(SUM(CASE WHEN IFNULL(we.paid,0)=1 THEN we.amount ELSE 0 END),0) paid_amt,
                   COUNT(DISTINCT CASE WHEN IFNULL(we.paid,0)=1 THEN we.employee END) paid_workers,
                   COALESCE(SUM(CASE WHEN IFNULL(we.paid,0)=0 THEN we.amount ELSE 0 END),0) unpaid_amt,
                   COUNT(DISTINCT CASE WHEN IFNULL(we.paid,0)=0 THEN we.employee END) unpaid_workers
            FROM `tabWork Actuals Employee` we
            INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
            WHERE """ + conds + """
        """, tuple(params), as_dict=True)
        k = kp[0] if kp else {}
        out["kpi"] = {
            "active_workers": frappe.utils.cint(k.active_workers) if kp else 0,
            "mandays": frappe.utils.cint(k.mandays) if kp else 0,
            "earned": frappe.utils.flt(k.earned) if kp else 0,
            "paid_amt": frappe.utils.flt(k.paid_amt) if kp else 0,
            "paid_workers": frappe.utils.cint(k.paid_workers) if kp else 0,
            "unpaid_amt": frappe.utils.flt(k.unpaid_amt) if kp else 0,
            "unpaid_workers": frappe.utils.cint(k.unpaid_workers) if kp else 0
        }
        # assigned workers (live assignments in window/farm)
        aconds = "a.workflow_state IN ('Pending Farm Manager','Pending HR Head','Pending GM','Assigned')"
        aparams = []
        if farm:
            aconds = aconds + " AND a.farm = %s"
            aparams.append(farm)
        asg = frappe.db.sql("""
            SELECT COUNT(DISTINCT we.employee) c
            FROM `tabWork Assignment Employee` we
            INNER JOIN `tabWork Management Assigner` a ON we.parent = a.name
            WHERE """ + aconds + """ AND IFNULL(we.status,'Active')='Active'
        """, tuple(aparams), as_dict=True)
        out["assigned_workers"] = frappe.utils.cint(asg[0].c) if asg else 0
        # workforce pool: active Task Workers -> available = pool - assigned
        pconds = "status='Active' AND employment_type='Task Worker'"
        pparams = []
        if farm:
            pconds = pconds + " AND custom_farm = %s"
            pparams.append(farm)
        pool = frappe.db.sql("""
            SELECT name emp, employee_name nm, custom_farm farm, designation
            FROM `tabEmployee` WHERE """ + pconds + """
            ORDER BY employee_name LIMIT 3000
        """, tuple(pparams), as_dict=True)
        out["pool_count"] = len(pool)
        arows = frappe.db.sql("""
            SELECT we.employee emp, we.employee_name nm, a.farm farm, a.task task,
                   a.name assignment, a.from_date fdate, a.to_date tdate, a.workflow_state state
            FROM `tabWork Assignment Employee` we
            INNER JOIN `tabWork Management Assigner` a ON we.parent = a.name
            WHERE """ + aconds + """ AND IFNULL(we.status,'Active')='Active'
            ORDER BY a.from_date DESC LIMIT 5000
        """, tuple(aparams), as_dict=True)
        aset = {}
        amap = {}
        for r in arows:
            aset[r.emp] = 1
            g = amap.get(r.emp)
            if not g:
                g = {"emp": r.emp, "nm": r.nm, "farm": r.farm, "assignments": 0, "tasks": {}, "latest_from": None, "latest_to": None}
                amap[r.emp] = g
            g["assignments"] = g["assignments"] + 1
            if r.task:
                g["tasks"][r.task] = 1
            if not g["latest_from"]:
                g["latest_from"] = str(r.fdate) if r.fdate else None
                g["latest_to"] = str(r.tdate) if r.tdate else None
        alist = []
        for k2 in amap:
            g = amap[k2]
            tl = []
            for tk in g["tasks"]:
                tl.append(tk)
            tl = sorted(tl)
            g["task_list"] = ", ".join(tl)
            g["task_count"] = len(tl)
            del g["tasks"]
            alist.append(g)
        alist = sorted(alist, key=lambda x: x["assignments"], reverse=True)
        out["assigned_list"] = alist
        avail = []
        for p in pool:
            if not aset.get(p.emp):
                avail.append({"emp": p.emp, "nm": p.nm, "farm": p.farm, "designation": p.designation})
        out["available_list"] = avail
        # unpaid list (worker-level, biggest first)
        unp = frappe.db.sql("""
            SELECT we.employee emp, we.employee_name nm, ac.farm farm,
                   COUNT(DISTINCT we.work_date) days, COALESCE(SUM(we.amount),0) owed,
                   MIN(we.work_date) oldest, MAX(we.work_date) newest
            FROM `tabWork Actuals Employee` we
            INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
            WHERE """ + conds + """ AND IFNULL(we.paid,0)=0 AND IFNULL(we.count_in_payroll,0)=1 AND we.amount>0
            GROUP BY we.employee, we.employee_name, ac.farm
            ORDER BY owed DESC LIMIT 500
        """, tuple(params), as_dict=True)
        ulist = []
        for u in unp:
            ulist.append({"emp": u.emp, "nm": u.nm, "farm": u.farm,
                "days": frappe.utils.cint(u.days), "owed": frappe.utils.flt(u.owed),
                "oldest": str(u.oldest) if u.oldest else None, "newest": str(u.newest) if u.newest else None})
        out["unpaid_list"] = ulist
        # task costs (per task per farm)
        tc = frappe.db.sql("""
            SELECT ac.task label, ac.farm farm,
                   COALESCE(SUM(we.amount),0) pay, COALESCE(SUM(we.actual_quantity),0) qty,
                   COUNT(DISTINCT we.employee) workers, COUNT(*) mandays
            FROM `tabWork Actuals Employee` we
            INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
            WHERE """ + conds + """
            GROUP BY ac.task, ac.farm ORDER BY pay DESC LIMIT 500
        """, tuple(params), as_dict=True)
        tclist = []
        for r in tc:
            tclist.append({"label": r.label, "farm": r.farm, "pay": frappe.utils.flt(r.pay),
                "qty": frappe.utils.flt(r.qty), "workers": frappe.utils.cint(r.workers),
                "mandays": frappe.utils.cint(r.mandays)})
        out["task_costs"] = tclist
        # top earners
        top = frappe.db.sql("""
            SELECT we.employee emp, we.employee_name nm, ac.farm farm,
                   COUNT(DISTINCT we.work_date) days, COALESCE(SUM(we.actual_quantity),0) qty,
                   COALESCE(SUM(we.amount),0) pay
            FROM `tabWork Actuals Employee` we
            INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
            WHERE """ + conds + """
            GROUP BY we.employee, we.employee_name, ac.farm
            ORDER BY pay DESC LIMIT 50
        """, tuple(params), as_dict=True)
        toplist = []
        for r in top:
            toplist.append({"emp": r.emp, "nm": r.nm, "farm": r.farm,
                "days": frappe.utils.cint(r.days), "qty": frappe.utils.flt(r.qty), "pay": frappe.utils.flt(r.pay)})
        out["top_workers"] = toplist
        # idle: assigned but no confirmed work in window
        idle = frappe.db.sql("""
            SELECT we.employee emp, we.employee_name nm, a.farm farm, COUNT(DISTINCT a.name) assignments
            FROM `tabWork Assignment Employee` we
            INNER JOIN `tabWork Management Assigner` a ON we.parent = a.name
            WHERE """ + aconds + """ AND IFNULL(we.status,'Active')='Active'
              AND we.employee NOT IN (
                SELECT DISTINCT we2.employee
                FROM `tabWork Actuals Employee` we2
                INNER JOIN `tabWork Management Actuals` ac2 ON we2.parent = ac2.name
                WHERE ac2.workflow_state='CONFIRMED'""" + (" AND we2.work_date >= %s" if dfrom else "") + (" AND we2.work_date <= %s" if dto else "") + """
              )
            GROUP BY we.employee, we.employee_name, a.farm
            ORDER BY assignments DESC LIMIT 500
        """, tuple(aparams + ([dfrom] if dfrom else []) + ([dto] if dto else [])), as_dict=True)
        ilist = []
        for r in idle:
            ilist.append({"emp": r.emp, "nm": r.nm, "farm": r.farm, "assignments": frappe.utils.cint(r.assignments)})
        out["idle_list"] = ilist
        # farms list for the dropdown
        allf = frappe.db.sql("""SELECT DISTINCT farm FROM `tabWork Management Actuals`
            WHERE farm IS NOT NULL ORDER BY farm""", as_dict=True)
        out["farms"] = [f.farm for f in allf]
        out["window"] = {"farm": farm or None, "from": dfrom or None, "to": dto or None}

    elif action == "pay_worker_history":
        # In-depth overview of ONE worker: every confirmed job (paid or not),
        # grouped per task/actuals doc with plan period, plus the raw daily log,
        # payment runs and headline KPIs. Used by the Audit worker deep-dive.
        emp = frappe.form_dict.get("employee")
        dfrom = frappe.form_dict.get("from_date")
        dto = frappe.form_dict.get("to_date")
        if not emp:
            out["error"] = "employee is required"
        else:
            hconds = "we.employee=%s AND ac.workflow_state='CONFIRMED'"
            hparams = [emp]
            if dfrom:
                hconds = hconds + " AND we.work_date >= %s"
                hparams.append(dfrom)
            if dto:
                hconds = hconds + " AND we.work_date <= %s"
                hparams.append(dto)
            einfo = frappe.db.get_value("Employee", emp,
                ["employee_name", "custom_farm", "designation", "employment_type", "status", "date_of_joining"],
                as_dict=True)
            out["info"] = {
                "employee": emp,
                "employee_name": (einfo.employee_name if einfo else None) or emp,
                "farm": einfo.custom_farm if einfo else None,
                "designation": einfo.designation if einfo else None,
                "employment_type": einfo.employment_type if einfo else None,
                "status": einfo.status if einfo else None,
                "date_of_joining": str(einfo.date_of_joining) if einfo and einfo.date_of_joining else None,
            }
            # KPIs across the window
            kp = frappe.db.sql("""
                SELECT COUNT(*) mandays,
                       COUNT(DISTINCT we.work_date) days,
                       COUNT(DISTINCT ac.task) tasks,
                       COUNT(DISTINCT ac.name) docs,
                       COALESCE(SUM(we.actual_quantity),0) qty,
                       COALESCE(SUM(we.amount),0) earned,
                       COALESCE(SUM(CASE WHEN IFNULL(we.paid,0)=1 THEN we.amount ELSE 0 END),0) paid_amt,
                       COALESCE(SUM(CASE WHEN IFNULL(we.paid,0)=0 AND IFNULL(we.count_in_payroll,0)=1 THEN we.amount ELSE 0 END),0) unpaid_amt,
                       COALESCE(SUM(CASE WHEN IFNULL(we.paid,0)=0 AND IFNULL(we.count_in_payroll,0)=1 AND IFNULL(we.custom_reviewed,0)=0 THEN we.amount ELSE 0 END),0) unreviewed_amt,
                       MIN(we.work_date) first_day, MAX(we.work_date) last_day
                FROM `tabWork Actuals Employee` we
                INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
                WHERE """ + hconds + """
            """, tuple(hparams), as_dict=True)
            k = kp[0] if kp else None
            days = frappe.utils.cint(k.days) if k else 0
            earned = frappe.utils.flt(k.earned) if k else 0
            out["kpi"] = {
                "mandays": frappe.utils.cint(k.mandays) if k else 0,
                "days": days,
                "tasks": frappe.utils.cint(k.tasks) if k else 0,
                "docs": frappe.utils.cint(k.docs) if k else 0,
                "qty": frappe.utils.flt(k.qty) if k else 0,
                "earned": earned,
                "paid_amt": frappe.utils.flt(k.paid_amt) if k else 0,
                "unpaid_amt": frappe.utils.flt(k.unpaid_amt) if k else 0,
                "unreviewed_amt": frappe.utils.flt(k.unreviewed_amt) if k else 0,
                "avg_per_day": (earned / days) if days else 0,
                "first_day": str(k.first_day) if k and k.first_day else None,
                "last_day": str(k.last_day) if k and k.last_day else None,
            }
            # per actuals doc first, then merged per TASK (many docs are single-day,
            # so grouping by task is what reads naturally: one card per task with
            # its full worked period and every approver involved)
            grp = frappe.db.sql("""
                SELECT ac.name actuals, ac.farm farm, ac.task task, ac.block_section block,
                       ac.assignment assignment, ac.rate doc_rate,
                       ac.entered_by entered_by, ac.hr_approved_by hr_approved_by, ac.gm_approved_by gm_approved_by,
                       MIN(we.work_date) wfrom, MAX(we.work_date) wto,
                       COUNT(DISTINCT we.work_date) days,
                       COALESCE(SUM(we.actual_quantity),0) qty,
                       COALESCE(SUM(we.amount),0) amount,
                       COALESCE(SUM(CASE WHEN IFNULL(we.paid,0)=1 THEN we.amount ELSE 0 END),0) paid_amt,
                       COALESCE(SUM(CASE WHEN IFNULL(we.paid,0)=0 AND IFNULL(we.count_in_payroll,0)=1 THEN we.amount ELSE 0 END),0) unpaid_amt,
                       MAX(we.payment_ref) run_ref
                FROM `tabWork Actuals Employee` we
                INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
                WHERE """ + hconds + """
                GROUP BY ac.name, ac.farm, ac.task, ac.block_section, ac.assignment, ac.rate,
                         ac.entered_by, ac.hr_approved_by, ac.gm_approved_by
                ORDER BY MIN(we.work_date) DESC
            """, tuple(hparams), as_dict=True)
            asg_cache = {}
            tmap = {}
            torder = []
            for g in grp:
                ai = None
                if g.assignment:
                    ai = asg_cache.get(g.assignment)
                    if ai is None:
                        ai = frappe.db.get_value("Work Management Assigner", g.assignment,
                            ["planner_request", "from_date", "to_date", "assigned_by", "approved_by"], as_dict=True)
                        asg_cache[g.assignment] = ai
                key = (g.task or "") + "|" + (g.block or "") + "|" + (g.farm or "")
                t = tmap.get(key)
                if not t:
                    t = {"task": g.task, "block": g.block, "farm": g.farm,
                         "plan_from": None, "plan_to": None, "work_from": None, "work_to": None,
                         "days": 0, "qty": 0, "amount": 0, "paid_amt": 0, "unpaid_amt": 0,
                         "docs": [], "assignments": {}, "runs": {}, "planners": {},
                         "assigned_by": {}, "fm_approved_by": {}, "entered_by": {},
                         "hr_approved_by": {}, "gm_approved_by": {}, "rate_num": 0}
                    tmap[key] = t
                    torder.append(key)
                t["docs"].append(g.actuals)
                if g.assignment:
                    t["assignments"][g.assignment] = 1
                if g.run_ref:
                    t["runs"][g.run_ref] = 1
                if ai:
                    if ai.planner_request:
                        t["planners"][ai.planner_request] = 1
                    pf = str(ai.from_date) if ai.from_date else None
                    pt = str(ai.to_date) if ai.to_date else None
                    if pf and (not t["plan_from"] or pf < t["plan_from"]):
                        t["plan_from"] = pf
                    if pt and (not t["plan_to"] or pt > t["plan_to"]):
                        t["plan_to"] = pt
                    if ai.assigned_by:
                        t["assigned_by"][ai.assigned_by] = 1
                    if ai.approved_by:
                        t["fm_approved_by"][ai.approved_by] = 1
                for fld in ("entered_by", "hr_approved_by", "gm_approved_by"):
                    v = g.get(fld)
                    if v:
                        t[fld][v] = 1
                wf = str(g.wfrom) if g.wfrom else None
                wt = str(g.wto) if g.wto else None
                if wf and (not t["work_from"] or wf < t["work_from"]):
                    t["work_from"] = wf
                if wt and (not t["work_to"] or wt > t["work_to"]):
                    t["work_to"] = wt
                t["days"] = t["days"] + frappe.utils.cint(g.days)
                t["qty"] = t["qty"] + frappe.utils.flt(g.qty)
                t["amount"] = t["amount"] + frappe.utils.flt(g.amount)
                t["paid_amt"] = t["paid_amt"] + frappe.utils.flt(g.paid_amt)
                t["unpaid_amt"] = t["unpaid_amt"] + frappe.utils.flt(g.unpaid_amt)
            tasks = []
            for key in torder:
                t = tmap[key]
                amt = t["amount"]
                if amt > 0 and t["paid_amt"] >= amt - 0.001:
                    pstat = "Paid"
                elif t["paid_amt"] > 0:
                    pstat = "Part paid"
                else:
                    pstat = "Unpaid"
                tasks.append({
                    "task": t["task"], "block": t["block"], "farm": t["farm"],
                    "plan_from": t["plan_from"], "plan_to": t["plan_to"],
                    "work_from": t["work_from"], "work_to": t["work_to"],
                    "days": t["days"], "qty": t["qty"],
                    "rate": (amt / t["qty"]) if t["qty"] else 0,
                    "amount": amt, "paid_amt": t["paid_amt"], "unpaid_amt": t["unpaid_amt"],
                    "pay_status": pstat,
                    "doc_count": len(t["docs"]),
                    "assignments": sorted(t["assignments"].keys()),
                    "planners": sorted(t["planners"].keys()),
                    "runs": sorted(t["runs"].keys()),
                    "assigned_by": sorted(t["assigned_by"].keys()),
                    "fm_approved_by": sorted(t["fm_approved_by"].keys()),
                    "entered_by": sorted(t["entered_by"].keys()),
                    "hr_approved_by": sorted(t["hr_approved_by"].keys()),
                    "gm_approved_by": sorted(t["gm_approved_by"].keys()),
                })
            tasks = sorted(tasks, key=lambda x: x["work_to"] or "", reverse=True)
            out["tasks"] = tasks
            # raw daily log
            dl = frappe.db.sql("""
                SELECT ac.name actuals, we.name rowname, we.work_date wdate, ac.task task, ac.block_section block, ac.farm farm,
                       we.actual_quantity qty, we.amount amount, ac.rate doc_rate,
                       IFNULL(we.paid,0) paid, IFNULL(we.count_in_payroll,0) in_payroll,
                       IFNULL(we.custom_reviewed,0) reviewed, we.payment_ref run_ref
                FROM `tabWork Actuals Employee` we
                INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
                WHERE """ + hconds + """
                ORDER BY we.work_date ASC
            """, tuple(hparams), as_dict=True)
            daily = []
            for r in dl:
                qty = frappe.utils.flt(r.qty)
                amt = frappe.utils.flt(r.amount)
                daily.append({
                    "actuals": r.actuals,
                    "rowname": r.rowname,
                    "doc_rate": frappe.utils.flt(r.doc_rate),
                    "editable": 1 if (not frappe.utils.cint(r.paid)) and frappe.utils.cint(r.in_payroll) else 0,
                    "wdate": str(r.wdate) if r.wdate else None,
                    "task": r.task, "block": r.block, "farm": r.farm,
                    "qty": qty, "amount": amt, "rate": (amt / qty) if qty else 0,
                    "paid": frappe.utils.cint(r.paid), "in_payroll": frappe.utils.cint(r.in_payroll),
                    "reviewed": frappe.utils.cint(r.reviewed), "run_ref": r.run_ref,
                })
            out["daily"] = daily
            # payment runs that include this worker
            runs = frappe.db.sql("""
                SELECT p.name run, p.run_title title, p.run_date rdate, p.workflow_state state,
                       l.amount amount, l.days days, l.qty qty
                FROM `tabWork Payment Line` l
                INNER JOIN `tabWork Management Payment` p ON l.parent = p.name
                WHERE l.employee = %s
                ORDER BY p.run_date DESC LIMIT 100
            """, (emp,), as_dict=True)
            runlist = []
            for r in runs:
                runlist.append({
                    "run": r.run, "title": r.title, "date": str(r.rdate) if r.rdate else None,
                    "state": r.state, "amount": frappe.utils.flt(r.amount),
                    "days": frappe.utils.cint(r.days), "qty": frappe.utils.flt(r.qty),
                })
            out["runs"] = runlist

    elif action == "pay_worker_edit_day":
        # Audit-stage correction: change the quantity recorded for one worker-day.
        # Pay recomputes at that row's rate, parent totals are re-summed, and the
        # row's review stamp resets so it must be re-reviewed before payment.
        emp = frappe.form_dict.get("employee")
        rowname = frappe.form_dict.get("rowname")
        new_qty = frappe.utils.flt(frappe.form_dict.get("qty"))
        if not emp or not rowname:
            out["error"] = "employee and rowname are required"
        elif new_qty < 0:
            out["error"] = "Quantity cannot be negative"
        else:
            row = frappe.db.get_value("Work Actuals Employee", rowname,
                ["name", "parent", "employee", "employee_name", "work_date",
                 "actual_quantity", "amount", "paid", "count_in_payroll"], as_dict=True)
            if not row:
                out["error"] = "Record not found"
            elif row.employee != emp:
                out["error"] = "Record does not belong to this worker"
            elif frappe.utils.cint(row.paid):
                out["error"] = "This day is already paid and cannot be edited"
            elif not frappe.utils.cint(row.count_in_payroll):
                out["error"] = "This row is not payroll-counted (salaried) — nothing to edit"
            else:
                pstate = frappe.db.get_value("Work Management Actuals", row.parent, "workflow_state")
                if pstate != "CONFIRMED":
                    out["error"] = "Actuals doc is not CONFIRMED (state: " + str(pstate) + ")"
                else:
                    old_qty = frappe.utils.flt(row.actual_quantity)
                    old_amt = frappe.utils.flt(row.amount)
                    rate = (old_amt / old_qty) if old_qty else frappe.utils.flt(
                        frappe.db.get_value("Work Management Actuals", row.parent, "rate"))
                    new_amt = new_qty * rate
                    frappe.db.set_value("Work Actuals Employee", rowname, "actual_quantity", new_qty, update_modified=False)
                    frappe.db.set_value("Work Actuals Employee", rowname, "amount", new_amt, update_modified=False)
                    frappe.db.set_value("Work Actuals Employee", rowname, "custom_reviewed", 0, update_modified=False)
                    frappe.db.set_value("Work Actuals Employee", rowname, "custom_reviewed_by", None, update_modified=False)
                    frappe.db.set_value("Work Actuals Employee", rowname, "custom_reviewed_at", None, update_modified=False)
                    tots = frappe.db.sql("""
                        SELECT COALESCE(SUM(actual_quantity),0) q, COALESCE(SUM(amount),0) p
                        FROM `tabWork Actuals Employee` WHERE parent=%s
                    """, (row.parent,), as_dict=True)
                    if tots:
                        frappe.db.set_value("Work Management Actuals", row.parent, "total_actual_qty", frappe.utils.flt(tots[0].q), update_modified=False)
                        frappe.db.set_value("Work Management Actuals", row.parent, "total_payment", frappe.utils.flt(tots[0].p), update_modified=False)
                    frappe.db.commit()
                    try:
                        frappe.get_doc("Work Management Actuals", row.parent).add_comment("Edited",
                            "Audit correction: " + (row.employee_name or emp) + " on " + str(row.work_date) +
                            " — qty " + str(old_qty) + " → " + str(new_qty) +
                            ", pay " + str(round(old_amt, 2)) + " → " + str(round(new_amt, 2)) +
                            " (by " + frappe.session.user + ")")
                    except Exception:
                        pass
                    out["rowname"] = rowname
                    out["qty"] = new_qty
                    out["amount"] = new_amt
                    out["rate"] = rate
                    out["parent"] = row.parent

    elif action == "pay_worker_review":
        # Stamp ONE worker's unpaid confirmed rows in the window as reviewed —
        # the audit trail between "Unpaid" and "sent to accounts".
        emp = frappe.form_dict.get("employee")
        dfrom = frappe.form_dict.get("from_date")
        dto = frappe.form_dict.get("to_date")
        if not emp:
            out["error"] = "employee is required"
        else:
            rconds = "we.employee=%s AND ac.workflow_state='CONFIRMED' AND IFNULL(we.paid,0)=0 AND IFNULL(we.count_in_payroll,0)=1 AND we.amount>0"
            rparams = [emp]
            if dfrom:
                rconds = rconds + " AND we.work_date >= %s"
                rparams.append(dfrom)
            if dto:
                rconds = rconds + " AND we.work_date <= %s"
                rparams.append(dto)
            rows = frappe.db.sql("""
                SELECT we.name rowname FROM `tabWork Actuals Employee` we
                INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
                WHERE """ + rconds + """
            """, tuple(rparams), as_dict=True)
            if not rows:
                out["error"] = "No unpaid confirmed rows to review in this window"
            else:
                now = frappe.utils.now()
                for r in rows:
                    frappe.db.set_value("Work Actuals Employee", r.rowname, "custom_reviewed", 1, update_modified=False)
                    frappe.db.set_value("Work Actuals Employee", r.rowname, "custom_reviewed_by", frappe.session.user, update_modified=False)
                    frappe.db.set_value("Work Actuals Employee", r.rowname, "custom_reviewed_at", now, update_modified=False)
                frappe.db.commit()
                out["employee"] = emp
                out["rows_reviewed"] = len(rows)
                out["reviewed_by"] = frappe.session.user

    elif action == "pay_worker_submit":
        # Approve ONE worker's unpaid confirmed earnings and send them to accounts
        # as a single-worker payment run (workers are paid one at a time).
        emp = frappe.form_dict.get("employee")
        dfrom = frappe.form_dict.get("from_date")
        dto = frappe.form_dict.get("to_date")
        if not emp:
            out["error"] = "employee is required"
        else:
            sconds = "we.employee=%s AND ac.workflow_state='CONFIRMED' AND IFNULL(we.paid,0)=0 AND IFNULL(we.count_in_payroll,0)=1 AND we.amount>0"
            sparams = [emp]
            if dfrom:
                sconds = sconds + " AND we.work_date >= %s"
                sparams.append(dfrom)
            if dto:
                sconds = sconds + " AND we.work_date <= %s"
                sparams.append(dto)
            agg = frappe.db.sql("""
                SELECT we.employee_name nm, MAX(ac.farm) farm,
                       COUNT(DISTINCT we.work_date) days,
                       COALESCE(SUM(we.actual_quantity),0) qty,
                       COALESCE(SUM(we.amount),0) owed
                FROM `tabWork Actuals Employee` we
                INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
                WHERE """ + sconds + """
            """, tuple(sparams), as_dict=True)
            if not agg or frappe.utils.flt(agg[0].owed) <= 0:
                out["error"] = "No unpaid confirmed earnings for this worker in the window"
            else:
                g = agg[0]
                ename = g.nm or frappe.db.get_value("Employee", emp, "employee_name") or emp
                d = frappe.new_doc("Work Management Payment")
                d.run_title = "Worker payment — " + ename + " — " + frappe.utils.today()
                d.company = DEFAULT_COMPANY
                d.run_date = frappe.utils.today()
                d.prepared_by = frappe.session.user
                try:
                    if dfrom:
                        d.period_from = dfrom
                    if dto:
                        d.period_to = dto
                except Exception:
                    pass
                row = d.append("lines", {})
                row.employee = emp
                row.employee_name = ename
                row.farm = g.farm
                row.days = g.days
                row.qty = g.qty
                row.paid_workers = 1
                row.amount = frappe.utils.flt(g.owed)
                d.grand_total = frappe.utils.flt(g.owed)
                d.total_workers = 1
                d.total_actuals = 1
                d.flags.ignore_permissions = True
                d.insert(ignore_permissions=True)
                frappe.db.set_value("Work Management Payment", d.name, "workflow_state", "Pending Accounts", update_modified=False)
                out["name"] = d.name
                out["workflow_state"] = "Pending Accounts"
                out["employee"] = emp
                out["employee_name"] = ename
                out["amount"] = frappe.utils.flt(g.owed)
                out["days"] = frappe.utils.cint(g.days)

    # ===== DASHBOARD (fast: grouped queries) =====
    else:
        out["error"] = "unknown action: " + str(action)


    return out
