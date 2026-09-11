# Ported from the upstream mirror's Server Script "wm_planner" (API) — logic unchanged.
# Farms / projects / company / approver roles now come from Work Management Settings
# and the Work Management Farm doctype — see work_management/api/config.py.
# ON THE `altura` BRANCH THIS FILE IS SOURCE, not a port. Altura deploys the
# packaged app rather than Kaitet's Server Scripts, so no port_app.py run
# follows this file and nothing reverts an edit made here. Edit it directly,
# and do not run the mirror's porter against this checkout — see
# docs/ALTURA_FORK.md. On master the opposite still holds.

import json

import frappe

from work_management.api.config import get_config
from work_management import audit, bulk
from work_management.master_plan import attributed_to_plan, unattributed_to_plan


@frappe.whitelist()
def wm_planner(**kwargs):
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
    # SERVER SCRIPT — "WM Planner" (API, api_method=wm_planner)
    # Powers: Planner + Assigner (a_) + Actuals (act_) + Payment (pay_) + dash
    # Multi-block planner (Option A) + fast grouped-query dashboard.
    # ==================================================================

    # How long a full day is, and the denominator every man-day figure divides by.
    # Sunday is worked on these farms, so it is a full day and not zero -- a zero
    # would divide by nothing on every Sunday row.
    #
    # This was three loose constants, declared in five scripts and read in one. It is
    # one value now because port_app.py strips it and rebuilds it from get_config(),
    # so a site that works a six-hour Friday can say so in Work Management Settings
    # instead of it being compiled in. Mirrors work_management/split_day.py, which is
    # unit-tested; keep the two in step.

    # WHO MAY DECIDE A PLAN. Approving and rejecting were gated only by the desk
    # workflow and by what the pending list chose to show -- the endpoint itself
    # checked nothing, so anyone who could reach it could approve any farm's plan.
    # This is the same signal `pending` scopes on, so what a person can DO now
    # matches what they can SEE: a farm-specific role decides that farm, while the
    # GM, the HR head and System Manager decide anywhere.
    ap_roles = frappe.db.get_all("Has Role", filters={"parent": frappe.session.user}, pluck="role")
    AP_BYPASS = 1 if (("System Manager" in ap_roles) or ("General Manager" in ap_roles)
                      or any(_r_ in ap_roles for _r_ in HR_HEAD_ROLES)
                      or frappe.session.user == "Administrator") else 0
    AP_FARMS = []
    for _farm_, _role_ in FARM_APPROVER_ROLE.items():
        if _role_ in ap_roles:
            AP_FARMS.append(_farm_)

    # The approval chain this screen advances. Where the chain comes from differs by
    # world; the derivation below does not.
    #
    # In the app, port_app.py strips this assignment and rebuilds STAGE_ROWS from
    # get_config() -- so it is whatever Settings holds, with every On switch honoured.
    #
    # On live it is this literal, which is the chain that has always run here. Live
    # carries no Work Management Approval Stage table, so there is nothing to read and
    # nothing to switch, and this keeps today's behaviour exactly. Reading the table
    # here instead would mean resolving "what comes after this step" a second time, in
    # a sandbox with no imports and no def -- and two implementations of that rule is
    # the bug this change exists to remove. Giving live the switches is a separate
    # job: hand it the table and the app's config, not a copy of the arithmetic.

    # Read the same way in both worlds, so no action below ever touches a raw row.
    # STAGE_STATE is where a step waits, STAGE_NEXT is where approving it goes, and
    # STAGE_ON says whether the step is in the chain at all.
    STAGE_STATE = {}
    STAGE_NEXT = {}
    STAGE_ON = {}
    STAGE_ROLE = {}
    for sr_row in STAGE_ROWS:
        STAGE_STATE[sr_row["key"]] = sr_row["state"]
        STAGE_NEXT[sr_row["key"]] = sr_row["next_state"]
        STAGE_ON[sr_row["key"]] = sr_row["on"]
        STAGE_ROLE[sr_row["key"]] = sr_row.get("role")

    # The caller's roles, read once. Each step's configured Role gates that step --
    # see may_take_step() in approvals.py, whose rule this mirrors: the step's own
    # role, or System Manager as the unstick-the-pipeline bypass. General Manager is
    # deliberately not a bypass here; it is one for the farm dimension, where the GM
    # oversees every farm, and the wrong one for a step, where it would let the GM
    # take the HR Head step and erase the separation the chain exists to express.
    MY_ROLES = frappe.db.get_all("Has Role", filters={"parent": frappe.session.user},
                                 pluck="role")

    # THE PLANNER'S OWN APPROVAL STEPS, in chain order and enabled only.
    # `approve` used to name planner_farm_approval and nothing else, which was the
    # whole chain while the Planner had one approval. A site that switches a second
    # one on -- Altura, where HR signs after the farm manager -- got a request that
    # reached Pending HR Approval and stopped there: the generated desk workflow
    # moves it correctly, and this screen, which is where the work happens, had no
    # button for it. Keyed off the configured chain now, so a step added in Settings
    # arrives on the screen without a release.
    AP_STEPS = []
    AP_STEP_AT = {}
    for sr_row in STAGE_ROWS:
        if (sr_row.get("document_type") == "Work Management Planner"
                and sr_row.get("kind") == "Approval" and sr_row.get("on")
                and sr_row.get("state")):
            AP_STEPS.append(sr_row)
            AP_STEP_AT[sr_row["state"]] = sr_row
    # Where the chain ends. A step that leads here is the last one, and only the
    # last one submits the document -- approving an intermediate step used to set
    # docstatus = 1 as well, which with two approvals would submit a request that
    # HR had not seen yet.
    AP_TERMINAL = "Approved"


    action = frappe.form_dict.get("action") or "meta"
    out = {}

    # ===== PLANNER =====
    # A farm this caller is not offered is not a farm they may ask about. FARMS is
    # the project's farm list, narrowed to the farms this person is permitted where
    # the site has asked for that -- so the picker has already stopped offering the
    # rest. What the picker cannot close is the request itself, and every action
    # below reads its farm from the request: `?farm=Endebess` from somebody
    # restricted to Saboti was answered in full, picker or no picker.
    #
    # So the guard sits ahead of the dispatch rather than inside the actions. There
    # are thirty-odd places that read a farm and one that could be forgotten is one
    # that leaks, and an action added next year gets this for free.
    #
    # Two things it deliberately does not refuse. A request naming no farm is a
    # request across everything the caller may see, and FARMS already bounds that --
    # refusing it would break the default view of every screen for everybody. And an
    # empty FARMS means the site is unconfigured, not that this person is permitted
    # nothing: the pickers are empty there anyway, so there is nothing to defend and
    # a guard that fired would only break a fresh install.
    FARM_ASKED = (frappe.form_dict.get("farm") or "").strip()
    FARM_DENIED = ""
    if FARM_ASKED and FARMS and FARM_ASKED not in FARMS:
        # The farm they asked for, and no others: listing the ones they may not see
        # would hand back exactly what the guard withholds.
        FARM_DENIED = (FARM_ASKED + " is not a farm you are working. If it should be,"
            " it needs adding to the farms this project works, or to the farms you"
            " are permitted.")

    if FARM_DENIED:
        out["error"] = FARM_DENIED
    elif action == "meta":
        out["farms"] = FARMS
        out["company"] = DEFAULT_COMPANY

    elif action == "blocks":
        farm = frappe.form_dict.get("farm")
        # Every location on the farm. A keyword list used to hide anything whose name
        # contained Store, Mill, Tank, BIN, Warehouse, Cold Room, Parchment or Diesel,
        # on the assumption that only field blocks get planned. That hid 41 real places
        # across the four farms -- General Store Avocado Packhouse among them -- and the
        # tasks people actually plan there (Cleaners, Store Clerk, Security, Gardener)
        # exist in the task list. Nothing had ever been recorded at them because the
        # planner would not offer them, not because no work happens there.
        rows = frappe.db.get_all("Warehouse", filters={"custom_farm":farm,"is_group":0,"disabled":0},
            fields=["name","warehouse_name","custom_area_ha"], order_by="name", limit=500)
        blocks = []
        for r in rows:
            nm = r.warehouse_name or r.name
            blocks.append({"name":r.name,"label":nm.replace(" - KL",""),
                           "area":frappe.utils.flt(r.custom_area_ha)})
        out["blocks"] = blocks

    elif action == "tasks":
        # Only what the approved master plan allows. Before this, every non-group
        # Task on the farm's project was offered -- with no ceiling on quantity or cost.
        farm = frappe.form_dict.get("farm")
        tk_from = frappe.form_dict.get("from_date") or frappe.utils.today()
        tk_to = frappe.form_dict.get("to_date") or tk_from
        tk_named = frappe.form_dict.get("master_plan") or ""
        tk_all = frappe.db.sql("""
            SELECT name, period_from, period_to FROM `tabWork Management Master Plan`
            WHERE farm = %(f)s AND workflow_state = 'Approved'
              AND period_from <= %(from)s AND period_to >= %(to)s
            ORDER BY period_from DESC
        """, {"f": farm, "from": tk_from, "to": tk_to}, as_dict=True)
        # The named plan decides which activities are on offer. Two plans can cover
        # these dates and budget the same activity from different money, so taking the
        # first by period would offer the wrong list -- and let a request draw down a
        # budget nobody chose. resolve_master_plan(), inlined; keep in step with
        # work_management/master_plan.py.
        tk_names = []
        for tk_c in tk_all:
            if tk_c.name:
                tk_names.append(tk_c.name)
        tk_pick = None
        tk_ambiguous = None
        if tk_named:
            if tk_named in tk_names:
                tk_pick = tk_named
        elif len(tk_names) > 1:
            # Nothing named and more than one budget: which activities are on offer
            # genuinely depends on which one, so the screen has to ask. Offering the
            # first plan's list would be a guess dressed up as an answer.
            tk_ambiguous = sorted(tk_names)
        elif tk_names:
            tk_pick = tk_names[0]
        tk_mp = []
        for tk_c in tk_all:
            if tk_c.name == tk_pick:
                tk_mp.append(tk_c)
        tasks = []
        if not tk_mp:
            out["master_plan"] = None
            # "the planner has gone" is what this looks like from the outside, so say what
            # is actually holding it up: the farm's own plan and where it has got to,
            # rather than only that nothing is approved
            tk_any = frappe.db.sql("""
                SELECT name, workflow_state, period_from, period_to
                FROM `tabWork Management Master Plan`
                WHERE farm = %(f)s AND period_from <= %(to)s AND period_to >= %(from)s
                ORDER BY FIELD(workflow_state,'Approved','Pending GM','Pending Consultant','Draft','Rejected'),
                         period_from DESC
                LIMIT 1
            """, {"f": farm, "from": tk_from, "to": tk_to}, as_dict=True)
            # a plan the request only PARTLY sits inside is the commonest way to land
            # here -- a budget running Mon-Sat against a Mon-Sun week -- and saying
            # "no approved master plan" about a plan that is plainly approved reads as
            # the system losing it. Name the period and what to do instead.
            tk_a = tk_any[0] if tk_any else None
            if tk_ambiguous:
                tk_why = (str(farm) + " has more than one approved master plan over " +
                          str(tk_from) + " to " + str(tk_to) + ": " +
                          ", ".join(tk_ambiguous) +
                          ". Pick the one this work is planned against.")
            elif tk_a and tk_a.workflow_state == "Approved":
                tk_why = ("This request runs " + str(tk_from) + " to " + str(tk_to) + ", but " +
                          tk_a.name + " budgets " + str(farm) + " only from " +
                          str(tk_a.period_from) + " to " + str(tk_a.period_to) + ". Plan within "
                          "those dates, or widen the master plan's period to cover them.")
                out["partial_plan"] = tk_a.name
                out["partial_from"] = str(tk_a.period_from)
                out["partial_to"] = str(tk_a.period_to)
            elif tk_a and tk_a.workflow_state == "Rejected":
                tk_why = ("No approved master plan covers " + str(tk_from) + " to " + str(tk_to) +
                          " for " + str(farm) + ". " + tk_a.name + " was rejected. Edit it and "
                          "submit it again, or raise a new one, then have it approved.")
            elif tk_a:
                tk_why = ("No approved master plan covers " + str(tk_from) + " to " + str(tk_to) +
                          " for " + str(farm) + ". " + tk_a.name + " covers these dates but is "
                          "still at " + str(tk_a.workflow_state) + ". Planning opens once it is approved.")
            else:
                tk_why = ("No approved master plan covers " + str(tk_from) + " to " + str(tk_to) +
                          " for " + str(farm) + ". Raise a master plan for this period and have "
                          "it approved.")
            if tk_a:
                out["pending_plan"] = tk_a.name
                out["pending_plan_state"] = tk_a.workflow_state
            out["blocked_reason"] = tk_why
        else:
            tkm = tk_mp[0]
            out["master_plan"] = tkm.name
            # the period the budget actually covers, so the screen can offer to snap the
            # request's dates to it rather than letting someone plan past the ceiling
            out["period_from"] = str(tkm.period_from)
            out["period_to"] = str(tkm.period_to)
            out["blocked_reason"] = None
            # WHAT IS LEFT ON THE BUDGET THE USER IS ABOUT TO DRAW FROM. One grouped
            # read for the plan rather than one per line: the attribution rule carries
            # a correlated subquery and the answer per task is the same either way.
            # Charged by the stored link, not by dates -- two plans over one period
            # were each shown the other's consumption, so both looked spent and every
            # line read exhausted.
            tk_args = {"f": farm, "plan": tkm.name,
                       "pfrom": tkm.period_from, "pto": tkm.period_to}
            tk_use = {}
            for tk_u in frappe.db.sql("""
                SELECT p.task task, COALESCE(SUM(p.quantity),0) q,
                       COALESCE(SUM(p.total_cost),0) c
                FROM `tabWork Management Planner` p
                WHERE p.farm = %(f)s AND IFNULL(p.workflow_state,'') != 'Rejected'
                  AND """ + attributed_to_plan("p") + """
                GROUP BY p.task
            """, tk_args, as_dict=True):
                tk_use[tk_u.task] = tk_u
            # committed work in these dates that no plan may be charged for; reported
            # beside the line so the remaining figure is not read as the whole story
            tk_un = {}
            for tk_x in frappe.db.sql("""
                SELECT p.task task, COALESCE(SUM(p.quantity),0) q,
                       COALESCE(SUM(p.total_cost),0) c
                FROM `tabWork Management Planner` p
                WHERE p.farm = %(f)s AND IFNULL(p.workflow_state,'') != 'Rejected'
                  AND """ + unattributed_to_plan("p") + """
                GROUP BY p.task
            """, tk_args, as_dict=True):
                tk_un[tk_x.task] = tk_x
            for ta in frappe.db.get_all("Work Management Master Plan Activity",
                    filters={"parent": tkm.name, "consultant_state": "OK"},
                    fields=["name", "task", "uom", "rate", "work_qty", "cost"], order_by="idx"):
                tk_used = tk_use.get(ta.task)
                tk_unat = tk_un.get(ta.task)
                tk_rq = frappe.utils.flt(ta.work_qty) - (frappe.utils.flt(tk_used.q) if tk_used else 0)
                tk_rc = frappe.utils.flt(ta.cost) - (frappe.utils.flt(tk_used.c) if tk_used else 0)
                ti = frappe.db.get_value("Task", ta.task,
                    ["subject", "custom_uom", "custom_daily_target", "custom_rate"], as_dict=True)
                tasks.append({"name": ta.task, "subject": (ti.subject if ti else ta.task),
                              "uom": ta.uom or (ti.custom_uom if ti else None),
                              "daily_target": frappe.utils.flt(ti.custom_daily_target) if ti else 0,
                              "rate": frappe.utils.flt(ti.custom_rate) if ti else 0,
                              "budget_rate": frappe.utils.flt(ta.rate, 6),
                              "work_qty": frappe.utils.flt(ta.work_qty),
                              "budget_cost": frappe.utils.flt(ta.cost),
                              "remaining_qty": tk_rq, "remaining_cost": tk_rc,
                              "unattributed_qty": frappe.utils.flt(tk_unat.q) if tk_unat else 0,
                              "unattributed_cost": frappe.utils.flt(tk_unat.c) if tk_unat else 0,
                              "exhausted": 1 if (tk_rq <= 0.005 or tk_rc <= 0.005) else 0})
        out["tasks"] = tasks

    elif action == "budgets":
        # Every approved master plan for a farm, so the planner can offer the periods
        # that may actually be planned instead of the person guessing a date range and
        # discovering afterwards that no budget covers it.
        bg_farm = frappe.form_dict.get("farm")
        if not bg_farm:
            out["budgets"] = []
        else:
            out["budgets"] = frappe.db.sql("""
                SELECT mp.name, mp.plan_name, mp.period_from, mp.period_to, mp.total_cost,
                       (SELECT COUNT(*) FROM `tabWork Management Master Plan Activity` a
                         WHERE a.parent = mp.name AND a.consultant_state = 'OK') activities
                FROM `tabWork Management Master Plan` mp
                WHERE mp.farm = %(f)s AND mp.workflow_state = 'Approved'
                ORDER BY mp.period_from DESC
            """, {"f": bg_farm}, as_dict=True)
            for bg in out["budgets"]:
                bg["period_from"] = str(bg["period_from"])
                bg["period_to"] = str(bg["period_to"])

    elif action == "compare":
        rows = frappe.db.get_all("Work Management Planner",
            filters={"farm":frappe.form_dict.get("farm"),"block_section":frappe.form_dict.get("block"),
                     "task":frappe.form_dict.get("task"),"workflow_state":"Approved"},
            fields=["name","quantity","people_per_day","person_days","total_cost","from_date","to_date","approval_date"],
            order_by="approval_date desc", limit=1)
        out["last"] = rows[0] if rows else None

    elif action == "pending":
        # EVERY STEP THIS PERSON MAY TAKE, not the one step the code used to name.
        # One query per step rather than one for all of them: a farm-scoped step is
        # narrowed to the farms this person decides, and an unscoped step must NOT
        # be -- HR decides for the business. A single filtered query would either
        # hide HR's queue from an HR head with no farm role, or hand a farm manager
        # every farm's HR queue.
        #
        # FARM SCOPING (unchanged for the scoped step): a farm manager only sees
        # plans awaiting approval for their own farm(s). GM / System Manager / HR
        # see all. Uses farm-specific roles, the same signal as Assigner/Actuals.
        prl = frappe.db.get_all("Has Role", filters={"parent": frappe.session.user}, pluck="role")
        pbypass = ("System Manager" in prl) or ("General Manager" in prl) or any(_r_ in prl for _r_ in HR_HEAD_ROLES) or (frappe.session.user == "Administrator")
        pallowed = []
        for _farm_, _role_ in FARM_APPROVER_ROLE.items():
            if _role_ in prl: pallowed.append(_farm_)
        pfields = ["name","farm","block_section","task","quantity","people_per_day","person_days",
                   "total_hours","total_cost","from_date","to_date","requested_by","request_date",
                   "workflow_state","uom","daily_target","rate","working_days","master_plan"]
        out["pending"] = []
        # what the screen needs to label its buttons and its empty state: the steps
        # this person may take, in chain order, whether or not any request waits
        out["steps"] = []
        for p_step in AP_STEPS:
            p_may = False
            pflt = {"workflow_state": p_step["state"]}
            if p_step.get("scoped"):
                p_may = bool(pbypass or pallowed)
                if not pbypass:
                    pflt["farm"] = ["in", pallowed] if pallowed else ["in", ["__none__"]]
            else:
                # may_take_step()'s rule: the step's own role, System Manager as the
                # unstick-the-pipeline bypass, and General Manager deliberately not
                p_may = bool(p_step.get("role") and (p_step["role"] in prl
                                                     or "System Manager" in prl))
            out["steps"].append({"key": p_step["key"], "label": p_step.get("label"),
                                 "action": p_step.get("action"), "state": p_step["state"],
                                 "scoped": p_step.get("scoped") or 0,
                                 "role": p_step.get("role"), "mine": 1 if p_may else 0})
            if not p_may:
                continue
            for p_row in frappe.db.get_all("Work Management Planner", filters=pflt,
                    fields=pfields, order_by="request_date desc", limit=200):
                # which step it waits in travels with the row, so the screen labels
                # the button with the step's own action rather than always "Approve"
                p_row["step"] = p_step["key"]
                p_row["step_label"] = p_step.get("label")
                p_row["step_action"] = p_step.get("action") or "Approve"
                out["pending"].append(p_row)

        # WHAT APPROVING THIS LEAVES. An approver could see the request but not the
        # ceiling it draws on, so "is there room for this?" was unanswerable without
        # opening the master plan in another tab. Remaining here already counts this
        # request -- Pending Approval holds budget the same way Approved does -- so
        # these figures read as "with this request counted", and rejecting returns them.
        pb_plan = {}   # link|farm|from|to -> the plan this request draws on, or None
        pb_amb = {}    # ... -> 1 where the dates alone cannot say which
        pb_act = {}    # plan -> task -> the budget line
        pb_use = {}    # plan -> task -> what every live request has drawn
        for pr in out["pending"]:
            # WHICH BUDGET THIS REQUEST DRAWS ON -- the link it carries, which is
            # what the requester chose. This took whichever approved plan started
            # latest, which is exact while a farm holds one budget per period and a
            # silent wrong answer once it can hold two: the approver was shown a
            # ceiling belonging to a plan the request had nothing to do with, and
            # decided against it. resolve_master_plan()'s rule, applied to reading
            # rather than writing.
            pb_key = (str(pr.get("master_plan")) + "|" + str(pr.get("farm")) + "|"
                      + str(pr.get("from_date")) + "|" + str(pr.get("to_date")))
            if pb_key not in pb_plan:
                pb_amb[pb_key] = 0
                if pr.get("master_plan"):
                    pb_hit = frappe.db.sql("""
                        SELECT name, period_from, period_to FROM `tabWork Management Master Plan`
                        WHERE name = %(n)s AND workflow_state = 'Approved'
                    """, {"n": pr.get("master_plan")}, as_dict=True)
                else:
                    pb_hit = frappe.db.sql("""
                        SELECT name, period_from, period_to FROM `tabWork Management Master Plan`
                        WHERE farm = %(f)s AND workflow_state = 'Approved'
                          AND period_from <= %(a)s AND period_to >= %(b)s
                        ORDER BY period_from DESC
                    """, {"f": pr.get("farm"), "a": pr.get("from_date"), "b": pr.get("to_date")},
                        as_dict=True)
                    if len(pb_hit) > 1:
                        # two budgets could have funded this and the request names
                        # neither. Showing one of them is the guess; say so instead.
                        pb_amb[pb_key] = 1
                        pb_hit = []
                pb_plan[pb_key] = pb_hit[0] if pb_hit else None
            pb_mp = pb_plan[pb_key]
            pr["budget_plan"] = pb_mp.name if pb_mp else None
            pr["budget_ambiguous"] = pb_amb.get(pb_key) or 0
            if not pb_mp:
                continue
            if pb_mp.name not in pb_act:
                pb_rows = {}
                for pb_a in frappe.db.get_all("Work Management Master Plan Activity",
                        filters={"parent": pb_mp.name, "consultant_state": "OK"},
                        fields=["task", "uom", "work_qty", "cost"]):
                    pb_rows[pb_a.task] = pb_a
                pb_act[pb_mp.name] = pb_rows
                pb_seen = {}
                for pb_u in frappe.db.sql("""
                    SELECT p.task task, COALESCE(SUM(p.quantity),0) q,
                           COALESCE(SUM(p.total_cost),0) c
                    FROM `tabWork Management Planner` p
                    WHERE p.farm = %(f)s AND IFNULL(p.workflow_state,'') != 'Rejected'
                      AND """ + attributed_to_plan("p") + """
                    GROUP BY p.task
                """, {"f": pr.get("farm"), "plan": pb_mp.name,
                      "pfrom": pb_mp.period_from, "pto": pb_mp.period_to},
                    as_dict=True):
                    pb_seen[pb_u.task] = pb_u
                pb_use[pb_mp.name] = pb_seen
            pb_line = pb_act[pb_mp.name].get(pr.get("task"))
            if not pb_line:
                continue
            pb_drawn = pb_use[pb_mp.name].get(pr.get("task"))
            pb_dq = frappe.utils.flt(pb_drawn.q) if pb_drawn else 0
            pb_dc = frappe.utils.flt(pb_drawn.c) if pb_drawn else 0
            pr["budget_uom"] = pb_line.uom
            pr["budget_qty"] = frappe.utils.flt(pb_line.work_qty)
            pr["budget_cost"] = frappe.utils.flt(pb_line.cost, 2)
            pr["budget_remaining_qty"] = frappe.utils.flt(pb_line.work_qty) - pb_dq
            pr["budget_remaining_cost"] = frappe.utils.flt(frappe.utils.flt(pb_line.cost) - pb_dc, 2)

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

    elif action == "decide_scope":
        out["can_decide_any"] = AP_BYPASS
        out["farms"] = AP_FARMS

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
        # Submitting crosses a workflow transition; saving a draft does not, and
        # stays open to whoever may raise the plan. The step's own configured role
        # gates it and System Manager bypasses -- may_take_step()'s rule, which
        # every approve action already applies.
        #
        # The refusal happened without this, but at the bottom of the stack: the
        # write below moves the plan by assigning workflow_state and saving, and
        # Frappe validates that against the generated workflow. ignore_permissions
        # does not reach that check -- only flags.ignore_validate would -- so a
        # section head without the role got
        #
        #     Workflow State transition not allowed from Draft to Pending Approval
        #
        # which names neither the role required nor their own, arriving as a 417
        # with a traceback. Refuse here instead, in words, before anything is written.
        if not err and submit_now and not (STAGE_ROLE["planner_submit"] in MY_ROLES
                                           or "System Manager" in MY_ROLES):
            err = ("Only " + str(STAGE_ROLE["planner_submit"]) + " can submit a plan "
                   "for approval. Save it as a draft, or ask somebody holding that "
                   "role to submit it.")
        if err:
            out["error"] = err
        else:
            wd = frappe.utils.date_diff(to_date, from_date) + 1
            if wd < 1: wd = 0
            # Resolve once, before the cap runs, whether this submit will edit plan_name
            # in place or clone it -- the same state test the write path applies further
            # down. Both the cap's committed-sum exclusion and the write path use this
            # one resolved value, so they can never disagree about which document this is.
            plan_editing = 0
            if plan_name and frappe.db.exists("Work Management Planner", plan_name):
                plan_state = frappe.db.get_value("Work Management Planner", plan_name, "workflow_state")
                if plan_state in ("Draft", "Rejected", "Pending Approval"):
                    plan_editing = 1
            cap_me = plan_name if plan_editing else ""
            # ---- MASTER PLAN CAP ------------------------------------------------
            # A plan may only be raised for an activity the approved master plan
            # allows, and only up to its budgeted quantity and cost. Mirrors
            # check_plan_allowed() in upande_work_management/master_plan.py.
            mp_named = frappe.form_dict.get("master_plan") or ""
            cap_all = frappe.db.sql("""
                SELECT name, period_from, period_to FROM `tabWork Management Master Plan`
                WHERE farm = %(f)s AND workflow_state = 'Approved'
                  AND period_from <= %(from)s AND period_to >= %(to)s
                ORDER BY period_from DESC
            """, {"f": farm, "from": from_date, "to": to_date}, as_dict=True)
            cap_names = []
            for cap_c in cap_all:
                if cap_c.name:
                    cap_names.append(cap_c.name)
            # resolve_master_plan(), inlined -- no def in the sandbox. Keep in step
            # with work_management/master_plan.py, which is unit-tested. The link the
            # request carries wins; nothing named with one candidate resolves to it,
            # which is how requests raised before the field keep working; two
            # candidates refuses rather than guesses, because guessing which budget
            # work came from is the whole error this exists to prevent.
            cap_pick = None
            cap_err = None
            cap_line = None
            if mp_named:
                if mp_named in cap_names:
                    cap_pick = mp_named
                else:
                    cap_err = (mp_named + " does not cover this request's farm and dates. "
                               "Choose a master plan whose period contains them.")
            elif not cap_names:
                cap_err = ("No approved master plan covers " + str(from_date) + " to " +
                           str(to_date) + " for " + str(farm) +
                           ". A master plan must be approved before work can be planned.")
            elif len(cap_names) > 1:
                cap_err = ("More than one approved master plan covers these dates: " +
                           ", ".join(sorted(cap_names)) +
                           ". Say which one this work is planned against.")
            else:
                cap_pick = cap_names[0]
            cap_mp = []
            for cap_c in cap_all:
                if cap_c.name == cap_pick:
                    cap_mp.append(cap_c)
            if not cap_err:
                cm = cap_mp[0]
                cap_rows = frappe.db.sql("""
                    SELECT name, work_qty, cost FROM `tabWork Management Master Plan Activity`
                    WHERE parent = %(p)s AND task = %(t)s AND consultant_state = 'OK'
                    LIMIT 1
                """, {"p": cm.name, "t": task}, as_dict=True)
                if not cap_rows:
                    cap_err = (str(task) + " is not an approved activity on master plan " +
                               cm.name + " (" + str(cm.period_from) + " to " + str(cm.period_to) + ").")
                else:
                    cap_line = cap_rows[0]
                    # WHAT THE PLAN BEING DRAWN ON HAS ALREADY SPENT -- that plan's own
                    # requests, by the link they carry, and not every request whose dates
                    # happen to sit in the period. With two overlapping approved plans the
                    # date rule charged each of them both plans' requests, so the cap
                    # refused work that had budget for it and the refusal below quoted a
                    # figure belonging to neither plan. cap_pick is the plan resolved for
                    # THIS request a few lines up, so the cap and the stored link agree by
                    # construction.
                    # The ambiguous remainder is deliberately not charged here either:
                    # never double-charge is the rule, and a request nobody can attribute
                    # must not silently eat a named plan's headroom.
                    cap_used = frappe.db.sql("""
                        SELECT COALESCE(SUM(p.quantity),0) q, COALESCE(SUM(p.total_cost),0) c
                        FROM `tabWork Management Planner` p
                        WHERE p.task = %(t)s AND p.farm = %(f)s
                          AND IFNULL(p.workflow_state,'') != 'Rejected'
                          AND p.name != %(me)s
                          AND """ + attributed_to_plan("p") + """
                    """, {"t": task, "f": farm, "me": cap_me, "plan": cm.name,
                          "pfrom": cm.period_from, "pto": cm.period_to}, as_dict=True)[0]
                    cap_rq = frappe.utils.flt(cap_line.work_qty) - frappe.utils.flt(cap_used.q)
                    cap_rc = frappe.utils.flt(cap_line.cost) - frappe.utils.flt(cap_used.c)
                    # report (and compare against) the true remaining figure, negative
                    # when the line is already over-consumed -- clamping to 0 would make
                    # a genuine overrun look like an exact fit, and would disagree with
                    # what headroom() reports for the same line at the same moment.
                    cap_tinfo = frappe.db.get_value("Task", task,
                        ["custom_daily_target", "custom_rate"], as_dict=True)
                    cap_rate = frappe.utils.flt(cap_tinfo.custom_rate) if cap_tinfo else 0
                    # identical arithmetic to d.total_cost = qty * rate below -- the cap
                    # must check the same figure the document is saved with, unrounded.
                    cap_cost = qty * cap_rate
                    # The figures are one master plan's, so the message says which.
                    # "12 left of 20" with two plans in force was unanswerable: the
                    # reader could not tell whose budget had refused them, and the
                    # number matched neither plan's own line.
                    if qty > cap_rq + 0.005:
                        cap_err = ("Over the budgeted quantity for " + str(task) +
                                   " on " + str(cm.name) + ": " +
                                   str(round(cap_rq, 2)) + " left of " +
                                   str(frappe.utils.flt(cap_line.work_qty)) +
                                   ", this plan asks for " + str(qty) + ".")
                    elif cap_cost > cap_rc + 0.005:
                        cap_err = ("Over the budgeted cost for " + str(task) +
                                   " on " + str(cm.name) + ": KES " +
                                   str(round(cap_rc, 2)) + " left of " +
                                   str(frappe.utils.flt(cap_line.cost)) +
                                   ", this plan costs " + str(round(cap_cost, 2)) + ".")
            if cap_err:
                out["error"] = cap_err
            else:
                out["master_plan"] = cap_mp[0].name
                tinfo = frappe.db.get_value("Task", task, ["custom_daily_target","custom_rate","custom_uom"], as_dict=True)
                tgt = frappe.utils.flt(tinfo.custom_daily_target) if tinfo else 0
                rate = frappe.utils.flt(tinfo.custom_rate) if tinfo else 0
                uom = tinfo.custom_uom if tinfo else None
                # HOW MANY PEOPLE. The client: "Allow us indicate the number of
                # people we want to allocate. (The system currently indicates the
                # number needed.)" So the computed figure becomes a SUGGESTION and
                # the requester's own number, when they give one, is what is kept.
                #
                # It changes nothing else. Cost is quantity x rate and man-days are
                # quantity / daily target -- both properties of the WORK, not of how
                # many people are sent at it. Twelve people finish sooner than six;
                # they do not finish more, and they do not cost more per unit. The
                # only thing a bigger crew buys is days, which is what the screen
                # now shows beside the number.
                ppd_suggested = 0
                if tgt > 0 and wd > 0:
                    raw = qty / tgt / wd
                    ppd_suggested = int(raw)
                    if ppd_suggested < raw: ppd_suggested = ppd_suggested + 1
                ppd_asked = frappe.utils.cint(frappe.form_dict.get("people_per_day"))
                ppd = ppd_asked if ppd_asked > 0 else ppd_suggested
                editing = plan_editing
                if editing:
                    d = frappe.get_doc("Work Management Planner", plan_name)
                    d.set("extra_blocks", [])   # rebuild blocks from the new selection
                else:
                    d = frappe.new_doc("Work Management Planner")
                d.farm = farm; d.company = DEFAULT_COMPANY; d.block_section = primary
                # The budget this request draws against, recorded rather than inferred.
                # Once two plans can cover one period the dates no longer identify one.
                d.master_plan = cap_pick
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
                        th = th + frappe.utils.flt(STANDARD_DAY.get("saturday"))
                    elif wdi == 6:
                        th = th + frappe.utils.flt(STANDARD_DAY.get("sunday"))
                    else:
                        th = th + frappe.utils.flt(STANDARD_DAY.get("weekday"))
                    cursor = frappe.utils.add_days(cursor, 1)
                    guard = guard + 1
                # man-days are the labour the QUANTITY represents: quantity / daily target.
                # Deriving them from the rounded crew instead (ppd * wd) inflated them --
                # 1000 units at 100/day over 3 days is 10 man-days, not the 12 a crew of
                # 4 implies. The crew still rounds up, because people come whole.
                d.quantity = qty
                d.people_per_day = ppd
                d.person_days = frappe.utils.flt(qty / tgt, 2) if tgt > 0 else (ppd * wd)
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
                    d.workflow_state = STAGE_NEXT["planner_submit"]; d.save(ignore_permissions=True)
                out["name"] = d.name; out["workflow_state"] = d.workflow_state
                out["total_cost"] = d.total_cost; out["people_per_day"] = d.people_per_day
                # both figures, so the screen can say which is which afterwards
                out["people_per_day_suggested"] = ppd_suggested
                out["people_per_day_is_custom"] = 1 if (ppd_asked > 0 and ppd_asked != ppd_suggested) else 0
                out["blocks"] = block_list
                out["editing"] = editing

    elif action in ("raise_target", "adjust_target"):
        # MORE OF THE SAME WORK, ON A REQUEST ALREADY APPROVED.
        #
        # A week's plan is approved for 500 and the crew can clearly do 700. Today
        # that needs a second request, through the whole chain, for work already
        # under way -- or an edit, which sends the approved plan back to Draft and
        # loses the approval it already has. So: raise the quantity in place.
        #
        # UP, OR DOWN TO WHAT IS ALREADY RECORDED. The client also asked for
        # "flexibility in adjusting the number of people already planned for a
        # specific task and targets for the day", and a plan that over-asked has
        # to be closable honestly.
        #
        # The floor is the work already recorded against this request -- the very
        # sum the actuals HARD TARGET CAP counts against the target, so the floor
        # here and the ceiling there are one number. Below it, recorded work would
        # exceed its own target and the plan could never reach 100% and therefore
        # never be submitted. check_cut_allowed() refuses the same move on a
        # master plan line for the same reason.
        #
        # Lowering FREES the master plan line: its consumption is summed from the
        # requests drawn against it, so the headroom comes back by arithmetic
        # rather than by anything here putting it back.
        #
        # NO NEW APPROVAL STAGE. Managers agree a spend increase offline, by
        # decision; what this needs is that the person recording the decision is
        # one who could have approved the request in the first place.
        rt_name = frappe.form_dict.get("name")
        rt_qty = frappe.utils.flt(frappe.form_dict.get("quantity"))
        rt_preview = frappe.utils.cint(frappe.form_dict.get("preview"))
        rt = frappe.db.get_value("Work Management Planner", rt_name,
            ["name", "farm", "task", "quantity", "total_cost", "rate", "uom",
             "daily_target", "working_days", "workflow_state", "master_plan",
             "original_qty", "original_cost", "from_date", "to_date"], as_dict=True)
        # WHO MAY RAISE ONE. The plan's own approval steps -- whoever could have
        # approved this request can agree to more of it -- plus GM and System
        # Manager. Never the requester role alone: raising your own approved target
        # is approving your own request, one step later and with nobody looking.
        rt_may = 0
        rt_roles = []
        for rt_step in AP_STEPS:
            if rt_step.get("role"):
                rt_roles.append(rt_step["role"])
                if rt_step["role"] in MY_ROLES:
                    rt_may = 1
        if ("System Manager" in MY_ROLES) or ("General Manager" in MY_ROLES):
            rt_may = 1
        rt_recorded = 0
        if rt:
            # what the actuals cap already counts against this request. The floor
            # under any target, and the figure that makes "never below what is
            # recorded" a fact rather than an intention.
            rt_done = frappe.db.sql("""
                SELECT COALESCE(SUM(ac.total_actual_qty),0) q
                FROM `tabWork Management Actuals` ac
                INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
                WHERE a2.planner_request = %(p)s
                  AND ac.workflow_state IN ('Pending HR Head','Pending GM','CONFIRMED')
            """, {"p": rt_name}, as_dict=True)
            rt_recorded = frappe.utils.flt(rt_done[0].q) if rt_done else 0
        # WHAT THE MASTER PLAN LINE HAS LEFT, by the same attribution rule as
        # everything else: this plan's own requests, not every request whose dates
        # happen to sit in the period. The raise is a DELTA -- the current quantity
        # is already counted in cap_used -- so the line only has to have room for
        # the increase.
        rt_line = None
        rt_left_q = 0
        rt_left_c = 0
        rt_rate = frappe.utils.flt(rt.rate) if rt else 0
        rt_delta = (rt_qty - frappe.utils.flt(rt.quantity)) if rt else 0
        if rt and rt.master_plan:
            rt_mp = frappe.db.get_value("Work Management Master Plan", rt.master_plan,
                ["name", "period_from", "period_to", "workflow_state"], as_dict=True)
            if rt_mp and rt_mp.workflow_state == "Approved":
                rt_rows = frappe.db.sql("""
                    SELECT name, work_qty, cost FROM `tabWork Management Master Plan Activity`
                    WHERE parent = %(p)s AND task = %(t)s AND consultant_state = 'OK'
                    LIMIT 1
                """, {"p": rt_mp.name, "t": rt.task}, as_dict=True)
                if rt_rows:
                    rt_line = rt_rows[0]
                    rt_used = frappe.db.sql("""
                        SELECT COALESCE(SUM(p.quantity),0) q, COALESCE(SUM(p.total_cost),0) c
                        FROM `tabWork Management Planner` p
                        WHERE p.task = %(t)s AND p.farm = %(f)s
                          AND IFNULL(p.workflow_state,'') != 'Rejected'
                          AND """ + attributed_to_plan("p") + """
                    """, {"t": rt.task, "f": rt.farm, "plan": rt_mp.name,
                          "pfrom": rt_mp.period_from, "pto": rt_mp.period_to},
                        as_dict=True)[0]
                    rt_left_q = frappe.utils.flt(rt_line.work_qty) - frappe.utils.flt(rt_used.q)
                    rt_left_c = frappe.utils.flt(rt_line.cost) - frappe.utils.flt(rt_used.c)

        rt_err = None
        if not rt:
            rt_err = "no such plan: " + str(rt_name)
        elif rt.workflow_state != "Approved":
            # Anything not yet approved can simply be edited, which is the existing
            # path and keeps the chain honest. This exists for the one state where
            # editing would throw away an approval.
            rt_err = ("Only an approved request's target can be raised in place ("
                      + str(rt.workflow_state) + "). Edit it instead — it has not "
                      "been approved yet, so nothing is lost.")
        elif not rt_may:
            rt_err = ("Raising an approved target is the approver's decision. "
                      + ("Only " + ", ".join(sorted(set(rt_roles))) +
                         " or the general manager may take it. " if rt_roles else "")
                      + "You hold none of them.")
        elif rt_qty <= 0:
            rt_err = "A target has to be a number greater than zero."
        elif rt_qty < rt_recorded - 0.005:
            rt_err = (str(rt_recorded) + " is already recorded against this request, "
                      "so its target cannot go below that: " + str(rt_qty) +
                      " is less. Recorded work reads the target live, so a target "
                      "under the work already done puts that work over its own "
                      "target and leaves the plan unable to complete. Lower it to " +
                      str(rt_recorded) + " or more.")
        elif abs(rt_qty - frappe.utils.flt(rt.quantity)) <= 0.005:
            rt_err = ("This request is already at " + str(frappe.utils.flt(rt.quantity)) + ".")
        elif not rt.master_plan:
            rt_err = ("This request names no master plan, so there is no budget to "
                      "check the raise against. Set its master plan first.")
        elif not rt_line:
            rt_err = (str(rt.task) + " is not an approved activity on " +
                      str(rt.master_plan) + ", so its budget cannot fund a raise.")
        elif rt_delta > 0 and rt_delta > rt_left_q + 0.005:
            # Refused in the same style as the planner's raise cap, and pointing at
            # the same fix: the master plan line can itself be raised first --
            # check_cut_allowed() permits raises and refuses only cuts below what is
            # committed -- and then this will go through.
            rt_err = ("Over the budgeted quantity for " + str(rt.task) + " on " +
                      str(rt.master_plan) + ": " + str(round(rt_left_q, 2)) +
                      " left of " + str(frappe.utils.flt(rt_line.work_qty)) +
                      ", this raise asks for " + str(round(rt_delta, 2)) + " more.")
        elif rt_delta > 0 and rt_delta * rt_rate > rt_left_c + 0.005:
            rt_err = ("Over the budgeted cost for " + str(rt.task) + " on " +
                      str(rt.master_plan) + ": KES " + str(round(rt_left_c, 2)) +
                      " left of " + str(frappe.utils.flt(rt_line.cost)) +
                      ", this raise costs " + str(round(rt_delta * rt_rate, 2)) + " more.")

        if rt:
            # BEFORE AND AFTER, always -- the preview IS the decision, and a
            # refusal that shows the figures is worth more than one that does not.
            out["plan"] = rt_name
            out["task"] = rt.task
            out["uom"] = rt.uom
            out["can_raise"] = rt_may
            out["approver_roles"] = sorted(set(rt_roles))
            out["current_qty"] = frappe.utils.flt(rt.quantity)
            out["current_cost"] = frappe.utils.flt(rt.total_cost)
            out["recorded_qty"] = rt_recorded
            # the lowest this target may go: what is already recorded against it
            out["floor_qty"] = rt_recorded
            out["original_qty"] = frappe.utils.flt(rt.original_qty) or None
            out["new_qty"] = rt_qty
            out["new_cost"] = frappe.utils.flt(rt_qty * rt_rate, 2)
            out["delta_qty"] = rt_delta
            out["delta_cost"] = frappe.utils.flt(rt_delta * rt_rate, 2)
            out["master_plan"] = rt.master_plan
            out["budget_left_qty"] = rt_left_q
            out["budget_left_cost"] = rt_left_c
            # what the line has left AFTER this raise, which is the figure the
            # person deciding actually wants
            out["budget_after_qty"] = rt_left_q - rt_delta
            out["budget_after_cost"] = rt_left_c - (rt_delta * rt_rate)

        if rt_err:
            out["error"] = rt_err
        elif rt_preview:
            out["preview"] = 1
        else:
            rd = frappe.get_doc("Work Management Planner", rt_name)
            rt_was_q = frappe.utils.flt(rd.quantity)
            rt_was_c = frappe.utils.flt(rd.total_cost)
            # SNAPSHOT ONCE. A second raise must not overwrite the first snapshot
            # with the first raise's figure -- "originally approved" means the
            # figure the chain approved, not the one before the latest edit.
            if not frappe.utils.flt(rd.original_qty):
                rd.original_qty = rt_was_q
                rd.original_cost = rt_was_c
            rd.quantity = rt_qty
            rd.total_cost = rt_qty * rt_rate
            # the crew and the labour follow the quantity, by the same arithmetic
            # the request was written with: man-days are quantity / daily target,
            # and the crew rounds up because people come whole.
            rt_tgt = frappe.utils.flt(rd.daily_target)
            rt_wd = frappe.utils.cint(rd.working_days)
            if rt_tgt > 0 and rt_wd > 0:
                rt_raw = rt_qty / rt_tgt / rt_wd
                rt_ppd = int(rt_raw)
                if rt_ppd < rt_raw:
                    rt_ppd = rt_ppd + 1
                rd.people_per_day = rt_ppd
            rd.person_days = (frappe.utils.flt(rt_qty / rt_tgt, 2) if rt_tgt > 0
                              else frappe.utils.flt(rd.people_per_day) * rt_wd)
            rd.flags.ignore_permissions = True
            # allow_on_submit is what lets an approved (submitted) request take
            # this; the fields it touches carry it for exactly this reason.
            rd.save(ignore_permissions=True)
            rd.add_comment("Comment",
                ("Target raised by " if rt_qty > rt_was_q else "Target lowered by ")
                + frappe.session.user + " on " +
                frappe.utils.today() + ": " + str(rt_was_q) + " → " + str(rt_qty) +
                " " + str(rt.uom or "") + " (KES " + str(round(rt_was_c, 2)) + " → " +
                str(round(rt_qty * rt_rate, 2)) + "), against " + str(rt.master_plan) +
                ". Agreed offline; no separate approval step.")
            frappe.db.commit()
            out["raised"] = 1
            out["direction"] = "up" if rt_qty > rt_was_q else "down"
            out["floor"] = rt_recorded
            out["was_qty"] = rt_was_q
            out["was_cost"] = rt_was_c
            out["quantity"] = frappe.utils.flt(rd.quantity)
            out["total_cost"] = frappe.utils.flt(rd.total_cost)
            out["people_per_day"] = frappe.utils.flt(rd.people_per_day)
            out["person_days"] = frappe.utils.flt(rd.person_days)

    elif action == "trail":
        # WHAT CHANGED ON THIS RECORD, AND WHO DECIDED IT. Versions say what a
        # field became; audit comments say what somebody decided and why -- a
        # rejection reason, a target adjustment, a post-approval edit. Read either
        # alone and the record looks like it changed for no reason, or like it was
        # discussed and never changed. Merged and newest-first, in one place, so
        # the screens render a trail rather than assemble one.
        tr_name = frappe.form_dict.get("name")
        if not tr_name or not frappe.db.exists("Work Management Planner", tr_name):
            out["error"] = "no such record: " + str(tr_name)
        else:
            out["trail"] = audit.change_trail("Work Management Planner", tr_name)
            # The banner, computed here rather than in the browser: a summary
            # recomputed in JavaScript is a second implementation of the same
            # question, and the two disagree the first time either moves.
            out["amended"] = audit.amended_summary("Work Management Planner", tr_name)

    elif action == "approve":
        nm = frappe.form_dict.get("name")
        ap_doc = frappe.db.get_value("Work Management Planner", nm,
            ["workflow_state", "farm"], as_dict=True)
        cur_ws = ap_doc.workflow_state if ap_doc else None
        # WHICH STEP THIS REQUEST IS WAITING IN, from the configured chain rather
        # than from a step named in the code. One action serves every approval the
        # chain holds, which is what lets a site add one.
        ap_step = AP_STEP_AT.get(cur_ws)
        # Two dimensions gate a step and only one applies to each. A FARM-SCOPED
        # step asks which farms this person may decide -- the farm manager's own,
        # the GM's and the HR head's being all of them. An unscoped step asks
        # whether they hold the step's own role: may_take_step()'s rule, where
        # System Manager bypasses and General Manager deliberately does not,
        # because a GM taking the HR step erases the separation the chain exists
        # to express. Asking the farm question of an unscoped step would let any
        # farm manager take HR's decision.
        ap_ok = True
        ap_why = None
        if ap_step and ap_step.get("scoped"):
            if not AP_BYPASS and ap_doc and ap_doc.farm not in AP_FARMS:
                ap_ok = False
                ap_why = ("You cannot approve plans for " + str(ap_doc.farm) +
                          ". A farm manager decides their own farm; the general manager "
                          "and the HR head decide any farm.")
        elif ap_step:
            if not (ap_step.get("role") and (ap_step.get("role") in MY_ROLES
                                             or "System Manager" in MY_ROLES)):
                ap_ok = False
                ap_why = ("Only " + str(ap_step.get("role") or "a role nobody has configured") +
                          " can take the " + str(ap_step.get("label") or "") +
                          " step. You do not hold it.")
        if not ap_doc:
            out["error"] = "no such plan: " + str(nm)
        elif not ap_step:
            # Either the request is not awaiting anything, or it waits in a step
            # that has since been switched off. Both are "nothing to approve here",
            # and the state is in the message because the two look identical from
            # the screen.
            out["error"] = "Not awaiting approval (state: " + str(cur_ws) + ")"
        elif not ap_ok:
            out["error"] = ap_why
        else:
            ap_next = ap_step.get("next_state")
            frappe.db.set_value("Work Management Planner", nm, "workflow_state", ap_next, update_modified=False)
            if ap_next == AP_TERMINAL:
                # the last approval, and the only one that submits the document
                frappe.db.set_value("Work Management Planner", nm, "docstatus", 1, update_modified=False)
                frappe.db.set_value("Work Management Planner", nm, "approved_by", frappe.session.user, update_modified=False)
                frappe.db.set_value("Work Management Planner", nm, "approval_date", frappe.utils.today(), update_modified=False)
                # A DATE CANNOT ANCHOR AN AUDIT. `approval_date` is day-granular
                # and Version.creation is a timestamp, so "was this edited after
                # approval" compared a datetime against a date and read every
                # same-day edit -- including ones made minutes BEFORE the
                # approval -- as an amendment. The field for the moment already
                # existed on this doctype and nothing was writing it.
                frappe.db.set_value("Work Management Planner", nm, "custom_approved_at",
                    frappe.utils.now(), update_modified=False)
            else:
                # An intermediate step has no field of its own on this doctype --
                # `approved_by` means the final approval and must keep meaning it --
                # so who took it is recorded where the document already keeps its
                # history, rather than not at all.
                frappe.get_doc("Work Management Planner", nm).add_comment(
                    "Comment", str(ap_step.get("label") or ap_step.get("key")) +
                    " taken by " + frappe.session.user + " — now " + str(ap_next))
            out["name"] = nm; out["workflow_state"] = ap_next
            out["step"] = ap_step.get("key"); out["step_label"] = ap_step.get("label")

    elif action in ("approve_bulk", "reject_bulk"):
        # SEVERAL AT A TIME, one at a time. Each document goes through the single
        # `approve` / `reject` branch below -- same role gate, same stage check,
        # same writes -- because this re-enters this very dispatcher rather than
        # restating any of it. See work_management/bulk.py.
        bk_names = frappe.form_dict.get("names")
        try:
            bk_names = json.loads(bk_names or "[]")
        except Exception:
            bk_names = []
        bk_reject = action == "reject_bulk"
        bk_reason = frappe.form_dict.get("reason")
        bk_bad = bulk.check_selection(bk_names, bk_reason, needs_reason=bk_reject)
        if bk_bad:
            out["error"] = bk_bad
        else:
            bk_ok, bk_failed = bulk.run_bulk(
                wm_planner, "reject" if bk_reject else "approve", bk_names,
                base={"reason": bk_reason} if bk_reject else None)
            out["ok"] = bk_ok
            out["failed"] = bk_failed
            out["summary"] = bulk.summarise(bk_ok, bk_failed,
                "rejected" if bk_reject else "approved")

    elif action == "reject":
        nm = frappe.form_dict.get("name")
        rj_doc = frappe.db.get_value("Work Management Planner", nm,
            ["workflow_state", "farm"], as_dict=True)
        cur_ws = rj_doc.workflow_state if rj_doc else None
        # Rejecting is available at every approval step, not only the first: a
        # request HR refuses is rejected the same way the farm manager's is, and
        # whoever may approve a step may refuse it.
        rj_step = AP_STEP_AT.get(cur_ws)
        rj_ok = True
        rj_why = None
        if rj_step and rj_step.get("scoped"):
            if not AP_BYPASS and rj_doc and rj_doc.farm not in AP_FARMS:
                rj_ok = False
                rj_why = ("You cannot reject plans for " + str(rj_doc.farm) +
                          ". A farm manager decides their own farm; the general manager "
                          "and the HR head decide any farm.")
        elif rj_step:
            if not (rj_step.get("role") and (rj_step.get("role") in MY_ROLES
                                             or "System Manager" in MY_ROLES)):
                rj_ok = False
                rj_why = ("Only " + str(rj_step.get("role") or "a role nobody has configured") +
                          " can take the " + str(rj_step.get("label") or "") +
                          " step. You do not hold it.")
        if not rj_doc:
            out["error"] = "no such plan: " + str(nm)
        elif not rj_step:
            out["error"] = "Not awaiting approval (state: " + str(cur_ws) + ")"
        elif not rj_ok:
            out["error"] = rj_why
        else:
            frappe.db.set_value("Work Management Planner", nm, "workflow_state", "Rejected", update_modified=False)
            frappe.db.set_value("Work Management Planner", nm, "approved_by", None, update_modified=False)
            frappe.db.set_value("Work Management Planner", nm, "approval_date", None, update_modified=False)
            # WHY, where the document keeps its history. A rejection with no
            # reason sends the requester back to a screen that tells them nothing,
            # and the person who rejected has moved on. Optional on the single
            # action so nothing that calls it today breaks; required when
            # rejecting in bulk, where the reason is the only thing distinguishing
            # one refusal from twenty.
            rj_why = str(frappe.form_dict.get("reason") or "").strip()
            if rj_why:
                frappe.get_doc("Work Management Planner", nm).add_comment(
                    "Comment", "Rejected by " + frappe.session.user + " at the " +
                    str(rj_step.get("label") or rj_step.get("key")) + " step: " + rj_why)
            out["name"] = nm; out["workflow_state"] = "Rejected"
            out["step"] = rj_step.get("key"); out["step_label"] = rj_step.get("label")
            out["reason"] = rj_why or None

    # ===== ASSIGNER (a_) =====
    elif action == "plan_detail":
        nm = frappe.form_dict.get("plan")
        p = frappe.db.get_value("Work Management Planner", nm,
            ["name","farm","block_section","task","quantity","total_cost","from_date","to_date",
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

    elif action == "plan_trace":
        # ONE PLAN, END TO END: who asked for it, who approved it, the crews it was
        # staffed with, the people actually on those crews, what they recorded and
        # what it cost. The weekly board could only show a plan's own row, so there
        # was no way to answer "who approved this and who worked it".
        tr = frappe.form_dict.get("plan")
        pl = frappe.db.get_value("Work Management Planner", tr,
            ["name","farm","block_section","task","quantity","from_date","to_date",
             "workflow_state","uom","daily_target","rate","total_cost","people_per_day",
             "person_days","requested_by","request_date","approved_by","approval_date",
             "fulfilled_qty","remaining_qty","fulfilment_pct","custom_close_state"], as_dict=True)
        if not pl:
            out["error"] = "no such plan: " + str(tr)
        else:
            blist = []
            if pl.block_section:
                blist.append(pl.block_section)
            for b in frappe.db.get_all("Work Planner Block", filters={"parent": tr},
                                       fields=["block"], order_by="idx"):
                if b.block:
                    blist.append(b.block)
            pl["blocks"] = blist
            out["plan"] = pl

            # the approval chain, in the order it actually happens
            chain = []
            chain.append({"step": "Requested", "who": pl.requested_by, "when": str(pl.request_date or "")})
            chain.append({"step": "Farm Manager approved" if pl.approved_by else "Farm Manager approval",
                          "who": pl.approved_by, "when": str(pl.approval_date or "")})
            out["chain"] = chain

            asgs = frappe.db.get_all("Work Management Assigner",
                filters={"planner_request": tr},
                fields=["name","workflow_state","assigned_by","assign_date","approved_by",
                        "approval_date","from_date","to_date","planned_people","assigned_count",
                        "variance","planned_cost"],
                order_by="creation")
            out["assignments"] = asgs
            anames = [a.name for a in asgs]

            # the people put on those crews
            crew = []
            if anames:
                crew = frappe.db.sql("""
                    SELECT we.parent assignment, we.employee, we.employee_name,
                           we.status, we.left_date
                    FROM `tabWork Assignment Employee` we
                    WHERE we.parent IN %(a)s
                    ORDER BY we.employee_name
                """, {"a": tuple(anames)}, as_dict=True)
            out["crew"] = crew

            # what was recorded against those assignments
            acts = []
            worked = []
            if anames:
                acts = frappe.db.sql("""
                    SELECT ac.name, ac.assignment, ac.workflow_state, ac.entered_by,
                           ac.hr_approved_by, ac.gm_approved_by, ac.entry_date,
                           ac.total_actual_qty, ac.total_payment, ac.rate,
                           ac.payroll_people
                    FROM `tabWork Management Actuals` ac
                    WHERE ac.assignment IN %(a)s
                    ORDER BY ac.entry_date
                """, {"a": tuple(anames)}, as_dict=True)
                worked = frappe.db.sql("""
                    SELECT we.employee, we.employee_name,
                           COUNT(DISTINCT we.work_date) days,
                           COALESCE(SUM(we.actual_quantity),0) qty,
                           COALESCE(SUM(we.amount),0) amount,
                           MAX(IFNULL(we.paid,0)) paid,
                           MIN(we.work_date) first_day, MAX(we.work_date) last_day
                    FROM `tabWork Actuals Employee` we
                    INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
                    WHERE ac.assignment IN %(a)s
                    GROUP BY we.employee, we.employee_name
                    ORDER BY COALESCE(SUM(we.amount),0) DESC
                """, {"a": tuple(anames)}, as_dict=True)
            out["actuals"] = acts
            out["workers"] = worked

            act_qty = 0
            act_pay = 0
            for a in acts:
                if a.workflow_state == "CONFIRMED":
                    act_qty = act_qty + frappe.utils.flt(a.total_actual_qty)
                    act_pay = act_pay + frappe.utils.flt(a.total_payment)
            tgt = frappe.utils.flt(pl.quantity)
            bud = frappe.utils.flt(pl.total_cost)
            out["delivery"] = {
                "target": tgt, "actual": act_qty,
                "achieved_pct": (act_qty / tgt * 100) if tgt else 0,
                "planned": bud, "spent": act_pay,
                "of_planned_pct": (act_pay / bud * 100) if bud else 0,
                "crew_planned": frappe.utils.cint(pl.people_per_day),
                "crew_assigned": len(crew),
                "workers_paid": len(worked),
            }

    else:
        out["error"] = "unknown action: " + str(action)

    return out
