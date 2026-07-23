# Ported from Kaitet live Server Script "wm_planner" (API) — logic unchanged.
# Farms / projects / company / approver roles now come from Work Management Settings
# (falls back to the original Kaitet defaults) — see upande_work_management/api/config.py.

import frappe

from upande_work_management.api.config import get_config


@frappe.whitelist()
def wm_planner(**kwargs):
    _cfg = get_config()
    FARM_PROJECT = _cfg["farm_project"]
    DEFAULT_COMPANY = _cfg["default_company"]
    FARMS = _cfg["farms"]
    BLOCK_EXCLUDE = _cfg["block_exclude"]
    FARM_APPROVER_ROLE = _cfg["farm_approver_role"]

    # ==================================================================
    # SERVER SCRIPT — "WM Planner" (API, api_method=wm_planner)
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
    if action == "meta":
        out["farms"] = FARMS
        out["company"] = DEFAULT_COMPANY

    elif action == "blocks":
        farm = frappe.form_dict.get("farm")
        rows = frappe.db.get_all("Warehouse", filters={"custom_farm":farm,"is_group":0,"disabled":0},
            fields=["name","warehouse_name","custom_area_ha"], order_by="name", limit=500)
        blocks = []
        for r in rows:
            nm = r.warehouse_name or r.name
            skip = False
            for kw in BLOCK_EXCLUDE:
                if kw.lower() in nm.lower():
                    skip = True
            if not skip:
                blocks.append({"name":r.name,"label":nm.replace(" - KL",""),"area":frappe.utils.flt(r.custom_area_ha)})
        out["blocks"] = blocks

    elif action == "tasks":
        farm = frappe.form_dict.get("farm")
        proj = FARM_PROJECT.get(farm)
        rows = frappe.db.get_all("Task", filters={"project":proj,"is_group":0},
            fields=["name","subject","custom_uom","custom_daily_target","custom_rate"],
            order_by="subject", limit=500)
        tasks = []
        for r in rows:
            tasks.append({"name":r.name,"subject":r.subject,"uom":r.custom_uom,
                "daily_target":r.custom_daily_target or 0,"rate":r.custom_rate or 0})
        out["tasks"] = tasks

    elif action == "compare":
        rows = frappe.db.get_all("Work Management Planner",
            filters={"farm":frappe.form_dict.get("farm"),"block_section":frappe.form_dict.get("block"),
                     "task":frappe.form_dict.get("task"),"workflow_state":"Approved"},
            fields=["name","quantity","people_per_day","person_days","total_cost","from_date","to_date","approval_date"],
            order_by="approval_date desc", limit=1)
        out["last"] = rows[0] if rows else None

    elif action == "pending":
        # FARM SCOPING: a farm manager only sees plans awaiting approval for their own farm(s).
        # GM / System Manager / HR see all. Uses farm-specific roles (same signal as Assigner/Actuals).
        pflt = {"workflow_state": "Pending Approval"}
        prl = frappe.db.get_all("Has Role", filters={"parent": frappe.session.user}, pluck="role")
        pbypass = ("System Manager" in prl) or ("General Manager" in prl) or ("HOD HR" in prl) or ("HR Manager Kaitet" in prl) or (frappe.session.user == "Administrator")
        if not pbypass:
            pallowed = []
            for _farm_, _role_ in FARM_APPROVER_ROLE.items():
                if _role_ in prl: pallowed.append(_farm_)
            pflt["farm"] = ["in", pallowed] if pallowed else ["in", ["__none__"]]
        out["pending"] = frappe.db.get_all("Work Management Planner",
            filters=pflt,
            fields=["name","farm","block_section","task","quantity","people_per_day","person_days",
                    "total_hours","total_cost","from_date","to_date","requested_by","request_date",
                    "workflow_state","uom","daily_target","rate","working_days"],
            order_by="request_date desc", limit=200)

    elif action == "my_requests":
        out["requests"] = frappe.db.get_all("Work Management Planner",
            filters={"requested_by":frappe.session.user},
            fields=["name","farm","block_section","task","quantity","people_per_day","person_days",
                    "total_hours","total_cost","from_date","to_date","workflow_state","request_date",
                    "approved_by","approval_date","uom","daily_target","rate","working_days"],
            order_by="creation desc", limit=200)

    elif action == "planner_blocks":
        # full block list for one planner (primary + extras)
        nm = frappe.form_dict.get("planner")
        primary = frappe.db.get_value("Work Management Planner", nm, "block_section")
        blist = []
        if primary:
            blist.append(primary)
        for r in frappe.db.get_all("Work Planner Block", filters={"parent":nm},
                fields=["block"], order_by="idx"):
            if r.block:
                blist.append(r.block)
        out["blocks"] = blist

    elif action == "roles":
        roles = frappe.db.get_all("Has Role", filters={"parent":frappe.session.user}, fields=["role"])
        rl = []
        for r in roles:
            rl.append(r.role)
        is_fm = False
        for r in rl:
            if r.startswith("Farm Manager"):
                is_fm = True
        out["user"] = frappe.session.user
        out["is_section_head"] = ("Production Section Head" in rl) or is_fm
        out["is_approver"] = is_fm

    elif action == "submit":
        farm = frappe.form_dict.get("farm")
        block = frappe.form_dict.get("block")
        blocks_raw = frappe.form_dict.get("blocks")
        task = frappe.form_dict.get("task"); qty = frappe.utils.flt(frappe.form_dict.get("quantity"))
        from_date = frappe.form_dict.get("from_date"); to_date = frappe.form_dict.get("to_date")
        submit_now = frappe.form_dict.get("submit_now")
        plan_name = frappe.form_dict.get("plan")  # if editing an existing draft
        block_list = []
        if blocks_raw:
            for b in blocks_raw.split(","):
                bv = b.strip()
                if bv and bv not in block_list:
                    block_list.append(bv)
        elif block:
            block_list.append(block)
        primary = block_list[0] if block_list else None
        err = None
        if farm not in FARMS: err = "Invalid farm"
        if not primary: err = "At least one block is required"
        if not task: err = "Task is required"
        if qty <= 0: err = "Quantity must be greater than zero"
        if not from_date or not to_date: err = "Date range is required"
        if err:
            out["error"] = err
        else:
            wd = frappe.utils.date_diff(to_date, from_date) + 1
            if wd < 1: wd = 0
            tinfo = frappe.db.get_value("Task", task, ["custom_daily_target","custom_rate","custom_uom"], as_dict=True)
            tgt = frappe.utils.flt(tinfo.custom_daily_target) if tinfo else 0
            rate = frappe.utils.flt(tinfo.custom_rate) if tinfo else 0
            uom = tinfo.custom_uom if tinfo else None
            ppd = 0
            if tgt > 0 and wd > 0:
                raw = qty / tgt / wd
                ppd = int(raw)
                if ppd < raw: ppd = ppd + 1
            editing = 0
            if plan_name and frappe.db.exists("Work Management Planner", plan_name):
                state = frappe.db.get_value("Work Management Planner", plan_name, "workflow_state")
                if state in ("Draft", "Rejected", "Pending Approval"):
                    d = frappe.get_doc("Work Management Planner", plan_name)
                    d.set("extra_blocks", [])   # rebuild blocks from the new selection
                    editing = 1
                else:
                    d = frappe.new_doc("Work Management Planner")
            else:
                d = frappe.new_doc("Work Management Planner")
            d.farm = farm; d.company = DEFAULT_COMPANY; d.block_section = primary
            i = 0
            for b in block_list:
                if i > 0:
                    row = d.append("extra_blocks", {}); row.block = b
                i = i + 1
            d.task = task; d.uom = uom; d.daily_target = tgt; d.rate = rate
            d.task_kpi = str(tgt) + " " + (uom or "") + "/day @ KES " + str(rate)
            d.from_date = from_date; d.to_date = to_date; d.working_days = wd
            # total hours across the period: Mon-Fri=8, Sat=6, Sun=8
            th = 0
            cursor = frappe.utils.getdate(from_date)
            endd = frappe.utils.getdate(to_date)
            guard = 0
            while cursor <= endd and guard < 400:
                wdi = cursor.weekday()  # Mon=0 .. Sun=6
                if wdi == 5:
                    th = th + SATURDAY_HOURS
                else:
                    th = th + WEEKDAY_HOURS
                cursor = frappe.utils.add_days(cursor, 1)
                guard = guard + 1
            d.quantity = qty; d.people_per_day = ppd; d.person_days = ppd * wd
            d.total_hours = th
            d.total_cost = qty * rate
            if not editing:
                d.requested_by = frappe.session.user; d.request_date = frappe.utils.today()
            if editing:
                # keep it a draft unless they explicitly submit; reset a Rejected back to Draft on save
                if not submit_now:
                    d.workflow_state = "Draft"
                d.save(ignore_permissions=True)
            else:
                d.insert(ignore_permissions=True)
            if submit_now:
                d.workflow_state = "Pending Approval"; d.save(ignore_permissions=True)
            out["name"] = d.name; out["workflow_state"] = d.workflow_state
            out["total_cost"] = d.total_cost; out["people_per_day"] = d.people_per_day
            out["blocks"] = block_list
            out["editing"] = editing

    elif action == "approve":
        nm = frappe.form_dict.get("name")
        cur_ws = frappe.db.get_value("Work Management Planner", nm, "workflow_state")
        if cur_ws != "Pending Approval":
            out["error"] = "Not awaiting approval (state: " + str(cur_ws) + ")"
        else:
            frappe.db.set_value("Work Management Planner", nm, "workflow_state", "Approved", update_modified=False)
            frappe.db.set_value("Work Management Planner", nm, "docstatus", 1, update_modified=False)
            frappe.db.set_value("Work Management Planner", nm, "approved_by", frappe.session.user, update_modified=False)
            frappe.db.set_value("Work Management Planner", nm, "approval_date", frappe.utils.today(), update_modified=False)
            out["name"] = nm; out["workflow_state"] = "Approved"

    elif action == "reject":
        nm = frappe.form_dict.get("name")
        cur_ws = frappe.db.get_value("Work Management Planner", nm, "workflow_state")
        if cur_ws != "Pending Approval":
            out["error"] = "Not awaiting approval (state: " + str(cur_ws) + ")"
        else:
            frappe.db.set_value("Work Management Planner", nm, "workflow_state", "Rejected", update_modified=False)
            frappe.db.set_value("Work Management Planner", nm, "approved_by", None, update_modified=False)
            frappe.db.set_value("Work Management Planner", nm, "approval_date", None, update_modified=False)
            out["name"] = nm; out["workflow_state"] = "Rejected"

    # ===== ASSIGNER (a_) =====
    elif action == "plan_detail":
        nm = frappe.form_dict.get("plan")
        p = frappe.db.get_value("Work Management Planner", nm,
            ["name","farm","block_section","task","quantity","from_date","to_date",
             "workflow_state","uom","daily_target","rate"], as_dict=True)
        blist = []
        if p and p.block_section:
            blist.append(p.block_section)
        for r in frappe.db.get_all("Work Planner Block", filters={"parent": nm}, fields=["block"], order_by="idx"):
            if r.block:
                blist.append(r.block)
        if p:
            p["blocks"] = blist
            p["editable"] = 1 if p.workflow_state in ("Draft","Rejected","Pending Approval") else 0
        out["plan"] = p

    else:
        out["error"] = "unknown action: " + str(action)


    return out
