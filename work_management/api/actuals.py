# Ported from the upstream mirror's Server Script "wm_actuals" (API) — logic unchanged.
# Farms / projects / company / approver roles now come from Work Management Settings
# and the Work Management Farm doctype — see work_management/api/config.py.
# ON THE `altura` BRANCH THIS FILE IS SOURCE, not a port. Altura deploys the
# packaged app rather than Kaitet's Server Scripts, so no port_app.py run
# follows this file and nothing reverts an edit made here. Edit it directly,
# and do not run the mirror's porter against this checkout — see
# docs/ALTURA_FORK.md. On master the opposite still holds.

import json

import frappe

from work_management import bulk, chain, presence, stage_pills
from work_management.api.config import chain_states, get_config, sql_in


@frappe.whitelist()
def wm_actuals(**kwargs):
    _cfg = get_config()
    FARM_PROJECT = _cfg["farm_project"]
    DEFAULT_COMPANY = _cfg["default_company"]
    FARMS = _cfg["farms"]
    BLOCK_EXCLUDE = _cfg["block_exclude"]
    FARM_APPROVER_ROLE = _cfg["farm_approver_role"]
    HR_HEAD_ROLES = _cfg["hr_head_roles"]
    STAGE_ROWS = _cfg["stage_rows"]
    STAGE_STATES = _cfg["stage_states"]
    # WORKFLOW STATE LISTS, read from the chain (approvals.pipeline_states via
    # get_config) and spliced into SQL with sql_in(). They were spelled out by
    # hand -- ('Pending Farm Manager','Pending HR Head','Pending GM','Assigned') --
    # and stopped matching the day a step's state was anything else.
    ST_ASG_ACTIVE = chain_states(_cfg, "Work Management Assigner", "active")
    ST_ACT_ACTIVE = chain_states(_cfg, "Work Management Actuals", "active")
    ST_ACT_WAITING = chain_states(_cfg, "Work Management Actuals", "waiting")
    ST_ACT_OPEN = chain_states(_cfg, "Work Management Actuals", "open")
    ST_ACT_ENTERED = chain_states(_cfg, "Work Management Actuals", "entered")
    ST_ACT_PAST_FIRST = chain_states(_cfg, "Work Management Actuals", "past_first")
    ST_ACT_WAITING_PAST_FIRST = chain_states(_cfg, "Work Management Actuals", "waiting_past_first")
    ST_ACT_DRAFT_WAITING = (chain_states(_cfg, "Work Management Actuals", "draft") + chain_states(_cfg, "Work Management Actuals", "waiting"))
    CAPABILITIES = _cfg["capabilities"]
    ALLOW_CONCURRENT_PLANS = _cfg["allow_concurrent_master_plans"]
    ALLOW_SPLIT_DAY = _cfg["allow_split_day"]
    ALLOW_SHORT_SUBMIT = _cfg["allow_short_submit"]
    STANDARD_DAY = _cfg["standard_day"]
    HOLIDAY_X = _cfg["public_holiday_pay_multiplier"]

    # ==================================================================
    # SERVER SCRIPT — "WM Actuals" (API, api_method=wm_actuals)
    # Powers: Planner + Assigner (a_) + Actuals (act_) + Payment (pay_) + dash
    # Multi-block planner (Option A) + fast grouped-query dashboard.
    # ==================================================================


    # WHO COUNTS AS A TASK WORKER
    # The same settings-driven test wm_payment uses, so the people this screen will
    # let you assign are exactly the people payment will later pay. Matching on
    # employment_type alone -- as this script used to -- disagreed with payment the
    # moment anyone configured a designation or a category instead, and produced
    # assignments whose work could never be paid.
    # An employee qualifies if ANY of the three configured lists matches.
    # Read the pickers first and the old typed boxes second, so both shapes work
    # while sites migrate: an empty picker changes nothing at all. A picked value is
    # a Link target or a Select option rather than something typed, so it needs no
    # character check -- an apostrophe in a designation is a docname, not a hazard.
    TW_SOURCES = [
        ("employment_type", "Work Management Payable Employment Type", "employment_type", "tw_employment_types"),
        ("designation", "Work Management Payable Designation", "designation", "tw_designations"),
        ("custom_category", "Work Management Payable Category", "category", "tw_categories"),
    ]
    # Only the Employee columns THIS site actually has. employment_type and
    # designation are standard; custom_category is a custom field one site created,
    # and naming a column the site has not got does not narrow the query, it kills
    # it -- (1054, "Unknown column 'twe.custom_category' in 'WHERE'") took a whole
    # screen down on a site that never had the field. frappe.db.has_column is not in
    # the sandbox's globals, but the meta is, and it knows custom fields too.
    TW_META = frappe.get_meta("Employee")
    TW_COLUMNS = []
    for tw_mc in ("employment_type", "designation", "custom_category"):
        if TW_META.get_field(tw_mc):
            TW_COLUMNS.append(tw_mc)

    TW_CLAUSES = []
    for tw_col, tw_child, tw_cfield, tw_box in TW_SOURCES:
        # the three lists are ORed, so dropping the column this site lacks costs
        # nothing -- there is no Settings list it could have matched anyway
        if tw_col not in TW_COLUMNS:
            continue
        tw_vals = []
        # frappe.get_all() on a doctype this site does not have raises rather than
        # returning nothing, so ask before looking.
        if frappe.db.exists("DocType", tw_child):
            for tw_r in frappe.get_all(tw_child,
                    filters={"parenttype": "Work Management Settings"}, fields=[tw_cfield]):
                tw_p = str(tw_r.get(tw_cfield) or "").strip()
                if tw_p:
                    tw_vals.append("'" + tw_p.replace("'", "''") + "'")
        if not tw_vals:
            # the Settings fields are multi-line boxes, so people list one value per line
            # as readily as they comma-separate them. Accept either: a newline that
            # survived into a value used to fail the character check below and take the
            # WHOLE list with it, silently, which stopped 315 task workers being payable.
            tw_raw = frappe.db.get_single_value("Work Management Settings", tw_box)
            for tw_v in str(tw_raw or "").replace("\r", "\n").replace("\n", ",").split(","):
                tw_c = tw_v.strip()
                # values come from Settings and land in SQL, so allow only the shapes a
                # job title can actually take and drop anything else outright
                tw_ok = 1
                for tw_ch in tw_c:
                    if not (tw_ch.isalnum() or tw_ch in " -_/&().'"):
                        tw_ok = 0
                if tw_c and tw_ok:
                    tw_vals.append("'" + tw_c.replace("'", "''") + "'")
        if tw_vals:
            TW_CLAUSES.append("e." + tw_col + " IN (" + ", ".join(tw_vals) + ")")
    if not TW_CLAUSES:
        # never leave the gate wide open if Settings is blank or unusable
        TW_CLAUSES = ["e.employment_type = 'Task Worker'"]
    TW_MATCH = "(" + " OR ".join(TW_CLAUSES) + ")"

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


    # ---------------------------------------------------------------- the chain
    #
    # Every approval below addresses a step of this chain by KEY -- never by the
    # step's action, state, label or role. See work_management/chain.py.
    ACT_DT = "Work Management Actuals"
    ACT_TERMINAL = STAGE_STATES.get(ACT_DT, {}).get("terminal")
    # Which farms this person decides. The farm dimension, asked once: a
    # farm-scoped step narrows to these, an unscoped one ignores them entirely.
    ACT_FARMS = []
    for _act_farm, _act_role in (FARM_APPROVER_ROLE or {}).items():
        if _act_role in MY_ROLES and _act_farm not in ACT_FARMS:
            ACT_FARMS.append(_act_farm)

    # CLOSING A PLAN, AND OVERRIDING AN ABSENT DAY, ASKED OF THE CHAIN.
    #
    # Five gates here used to read `r.startswith("Farm Manager")`, `r ==
    # "Production Section Head"` and `"General Manager" in roles` -- three job
    # titles out of the chain this app happens to ship with. On Altura, where
    # the same steps are taken by a Production Manager, they answered no to the
    # person who takes every one of them, so a plan could not be closed and a
    # crew could not be changed except by granting somebody a role whose name
    # means something else entirely.
    #
    # The chain answers both questions, and they are two different questions:
    #
    #   DECIDING a close is the last approval step's own decision -- the step
    #   whose approval reaches the end of the chain. That is already what
    #   act_close_pending tells whoever may not see the queue, in those words.
    #
    #   ASKING for one is open to anybody this chain involves -- whoever takes
    #   an approval step, and whoever the Submit step names, which is the person
    #   who records the work and is usually the one who knows the crop finished.
    #   That is the shipped rule ("the farm's approver, or the section head who
    #   raised it") said without naming anybody. A request decides nothing, so
    #   erring wide here costs a queue entry and never a figure; erring narrow
    #   costs the site the only way to stop a plan.
    #
    # Farm scope travels with it, because chain.may_take() asks the farm
    # question of a farm-scoped step and ignores it everywhere else.
    ACT_FINAL_STEP = None
    for _act_step in chain.approval_steps(STAGE_ROWS, ACT_DT, enabled_only=True):
        if _act_step.get("next_state") == ACT_TERMINAL:
            ACT_FINAL_STEP = _act_step
    ACT_MAY_DECIDE = 1 if (ACT_FINAL_STEP and chain.may_take(
        ACT_FINAL_STEP, MY_ROLES, farms=ACT_FARMS) is None) else 0
    ACT_MAY_REQUEST = 1 if chain.takeable(
        STAGE_ROWS, ACT_DT, MY_ROLES, farms=ACT_FARMS) else 0
    if not ACT_MAY_REQUEST:
        if (STAGE_ROLE.get("actuals_submit") in MY_ROLES) or ("System Manager" in MY_ROLES):
            ACT_MAY_REQUEST = 1
    ACT_DECIDER_LABEL = chain.label_of(ACT_FINAL_STEP, "whoever takes the last approval")

    # WHERE A SHIPPED STEP STAMPS ITSELF -- columns this doctype already has,
    # named after the chain as it shipped. A fallback constant keyed by the one
    # name that is stable; a step this app never shipped stamps nothing extra and
    # is recorded on the document's own comment history instead.
    ACT_STAMP = {
        "actuals_farm_manager": ("fm_approved_by", "fm_approval_date"),
        "actuals_hr_head": ("hr_approved_by", "hr_approval_date"),
        "actuals_gm": ("gm_approved_by", "gm_approval_date"),
    }

    # Who may do what, beyond approving. In the app, port_app.py strips this and
    # rebuilds CAPABILITIES from get_config(), so it is whatever Settings holds. Here
    # it is what this site has always allowed -- these were four lists compiled into
    # the code, naming this company's job titles, so a farm could say who approves a
    # plan and not who may change a rate.

    # May one worker's day be shared between two tasks, and how long is a day?
    #
    # port_app.py strips both and rebuilds them from get_config(), so in the app they
    # are whatever Work Management Settings holds. Here they are the literals, and
    # False keeps live behaving exactly as it does today.
    #
    # STANDARD_DAY is the denominator every man-day figure divides by. Sunday is
    # worked on these farms, so it is a full day and not zero -- a zero there would
    # divide by nothing on every Sunday row. Mirrors work_management/split_day.py,
    # which is unit-tested; keep the two in step.

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
    elif action == "act_assigned":
        # How many assignments the clerk is offered. The cap is applied at the END,
        # after the closed-early and already-fulfilled ones have been dropped, so it
        # means 200 assignments somebody can actually record against.
        #
        # It used to sit on the fetch instead, and the trimming ran after it -- so
        # the budget was spent on rows that were then thrown away. On this site:
        # 1,497 Assigned assignments, 200 fetched, 45 dropped as closed early and
        # 115 as already fully recorded, leaving 40 offered. The other 1,297 were
        # never looked at, and the actuals hanging off them could not be reached.
        #
        # The order is approval_date desc, which made it worse the day three weeks
        # of v15 work was migrated in: the window moved from 20 August to 26 August
        # and displaced 130 assignments people were still working on.
        #
        # Fetching every Assigned assignment is only affordable because the planner
        # lookups below are now one query instead of two per assignment -- that
        # N+1 was the reason a fetch cap existed at all.
        SHOWN = 200
        asgs = frappe.db.get_all("Work Management Assigner", filters={"workflow_state":"Assigned"},
            fields=["name","farm","block_section","task","task_kpi","from_date","to_date",
                    "planned_people","planned_cost","planner_request","assigned_count"],
            order_by="approval_date desc")
        # plan target + fulfilled, so we can show remaining and only hide FULLY fulfilled assignments
        plan_target = {}
        plan_done = {}
        plan_closed = {}
        plan_wanted = []
        for a in asgs:
            pr = a.planner_request
            if pr and pr not in plan_target:
                # 0 until the batch below says otherwise, which is also what the old
                # per-row get_value returned for a planner that no longer exists
                plan_target[pr] = 0
                plan_wanted.append(pr)
        if plan_wanted:
            for p in frappe.db.get_all("Work Management Planner",
                    filters={"name": ["in", plan_wanted]},
                    fields=["name", "quantity", "custom_close_state"]):
                plan_target[p.name] = frappe.utils.flt(p.quantity)
                plan_closed[p.name] = p.custom_close_state or ""
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
            WHERE ac.workflow_state IN (""" + sql_in(ST_ACT_DRAFT_WAITING) + """)
            GROUP BY a2.planner_request
        """, as_dict=True):
            plan_pending[r.pr] = frappe.utils.flt(r.q)
        # count entries currently in review (pending) per assignment, to warn the clerk
        inreview = {}
        for r in frappe.db.sql("""
            SELECT assignment, COUNT(name) n
            FROM `tabWork Management Actuals`
            WHERE workflow_state IN (""" + sql_in(ST_ACT_WAITING_PAST_FIRST) + """)
            GROUP BY assignment
        """, as_dict=True):
            inreview[r.assignment] = r.n
        # WORK THIS CALLER HAS ALREADY STARTED IS NOT CLUTTER.
        #
        # Read before the filter runs, because both the drop below and the cap below
        # that would otherwise take it away. Draft and Rejected only -- the two states
        # the screen draws an "Edit" link for; a CONFIRMED entry is finished and has no
        # business back in the picker.
        mine = {}
        for r in frappe.db.sql("""
            SELECT DISTINCT assignment FROM `tabWork Management Actuals`
            WHERE entered_by = %s AND workflow_state IN ('Draft','Rejected')
              AND IFNULL(assignment,'') != ''
        """, (frappe.session.user,), as_dict=True):
            mine[r.assignment] = 1
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
            #
            # ...and keep the caller's own unfinished entries, whatever the total says.
            # `recorded` is confirmed PLUS pending, and pending counts Draft -- so a
            # clerk who enters a draft meeting the target trips this test with their own
            # unfinished work, and the assignment leaves the picker taking the draft with
            # it. On kaitet-group that was 16 of the 19 stranded drafts: the target was
            # met only by counting the very entry that could no longer be reached.
            # Hiding a finished assignment is clutter control; hiding somebody's
            # unfinished work is not, so the test has to ask whose work it is.
            if a["fulfilled_done"] and not mine.get(a.name):
                continue
            rows.append(a)
        # The caller's own, first, so the cap falls on rows nobody has touched. Raising
        # 200 to 500 would only move where the cliff falls; a cap may shorten a list, it
        # may not decide what somebody is allowed to finish.
        if mine:
            pinned = []
            others = []
            for a in rows:
                if mine.get(a.name):
                    pinned.append(a)
                else:
                    others.append(a)
            rows = pinned + others
        # NOW the cap, on assignments that survived the trim rather than on the fetch
        if len(rows) > SHOWN:
            rows = rows[:SHOWN]
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
        # ANSWER, DO NOT RAISE. With no assignment -- or a name that does not exist --
        # every `a[...]` below assigns into None and the request dies with
        # `TypeError: 'NoneType' object does not support item assignment`: a 500
        # where an error message belongs. Reached by passing the wrong parameter
        # name, which is easily done since the field is `assignment` and the
        # doctype's own is `name`.
        if not a:
            out["error"] = ("No such assignment: " + str(name or "(none given)") +
                ". Pass ?assignment=<name>.")
            # and something for the rest of this block to write into. The sandbox
            # has no `return`, and wrapping 269 lines in a conditional to avoid one
            # bad parameter would be a worse change than this: an empty _dict reads
            # every field as None, the queries below filter on a parent that does
            # not exist and come back empty, and the date-dependent parts are
            # already guarded by `if fromd and tod`. The caller gets the error.
            a = {}
        rate = 0
        target = 0
        uom = None
        pr = a.get("planner_request")
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
        # WHETHER THE SCREEN ASKS FOR HOURS AT ALL. With splitting off the grid is
        # exactly as it has always been -- no extra box, nothing to type. On, each
        # cell offers the hours beside the quantity, pre-filled with the standard for
        # that date so an ordinary day still needs nothing typed.
        a["allow_split_day"] = 1 if ALLOW_SPLIT_DAY else 0
        # WHETHER THIS SITE LETS A SHORT WEEK BE SUBMITTED. Off -- the default --
        # the submit button stays locked below target exactly as it always has,
        # and the screen has nothing extra to draw. On, it unlocks and asks for a
        # reason, because the plan is about to be capped at what was done.
        a["allow_short_submit"] = 1 if ALLOW_SHORT_SUBMIT else 0
        a["standard_day"] = {
            "weekday": frappe.utils.flt(STANDARD_DAY.get("weekday")),
            "saturday": frappe.utils.flt(STANDARD_DAY.get("saturday")),
            "sunday": frappe.utils.flt(STANDARD_DAY.get("sunday")),
        }
        # total block area (Ha) = primary block_section + extra_blocks, summed from Warehouse.custom_area_ha
        block_area = 0
        bset = {}
        prim_block = a.get("block_section")
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
                  AND ac.workflow_state IN (""" + sql_in(ST_ACT_PAST_FIRST) + """)
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
        # WHO IS PAID PER TASK, decided once, here. The screen used to answer this
        # itself with employment_type == "Task Worker" -- the very test this script
        # stopped using, and for the same reason: a site that names its task workers
        # by designation or category has none at all by employment_type, so the grid
        # called every one of them salaried, priced none of their work, and hid the
        # swap and release controls from every row -- while payment, reading Settings,
        # went on paying them. TW_MATCH is that same settings-driven test.
        tw_names = {}
        if workers:
            tw_asked = []
            for w in workers:
                tw_asked.append(w.employee)
            for tw_row in frappe.db.sql("""
                SELECT e.name FROM `tabEmployee` e
                WHERE e.name IN %(names)s AND """ + TW_MATCH,
                    {"names": tuple(tw_asked)}, as_dict=True):
                tw_names[tw_row.name] = 1
        for w in workers:
            w["is_task_worker"] = 1 if tw_names.get(w.employee) else 0
        # off-days per worker within the plan period (from their Employee.holiday_list)
        # .get(), not attribute access: with no such assignment `a` is a plain {}
        # so the error can be reported without the next 250 lines raising, and a
        # frappe as_dict row answers .get() just the same.
        fromd = a.get("from_date")
        tod = a.get("to_date")
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
        # ── PRESENCE PER WORKER-DAY: biometric scan (with first scan time),
        # submitted Present attendance, and submitted ABSENT attendance — the grid
        # distinguishes P (evidence of presence), A (known absent) and ? (no record
        # either way / presence unknown). ──
        #
        # ASKED OF EACH CELL'S OWN DATE, and always was: the three reads below are
        # bounded by `fromd`/`tod`, the assignment's window, and keyed by
        # (employee, date) so a cell for last Tuesday carries Tuesday's evidence.
        # Audited against finding #1 on 2026-09-23 and correct as it stands --
        # the fault was on the assigner's picker, which asked `DATE(time) = today`
        # three times over whatever the window was. `a["today"]` below is not a
        # date filter: it is the cue the grid uses to leave FUTURE cells blank,
        # since a day that has not happened has no scan to be missing.
        scan_by = {}
        attp_by = {}
        abs_by = {}
        # The window's own days, up to today -- the same arithmetic the assigner's
        # picker uses, so the two screens cannot disagree about which days a
        # presence question covers. A window still running reads to today; one
        # that finished reads to its own last day; one that has not started reads
        # nothing, and the grid draws no marks rather than "?" on every cell.
        ev_from, ev_to, ev_days = presence.evidence_window(
            fromd, tod, str(frappe.utils.today()))
        a["presence_window"] = {"from": ev_from, "to": ev_to, "days": ev_days}
        if workers and ev_from:
            wemps = tuple([w.employee for w in workers])
            for r in frappe.db.sql("""
                SELECT employee, DATE(`time`) d, MIN(`time`) t FROM `tabEmployee Checkin`
                WHERE employee IN %s AND DATE(`time`) BETWEEN %s AND %s
                GROUP BY employee, DATE(`time`)
            """, (wemps, ev_from, ev_to), as_dict=True):
                m = scan_by.get(r.employee)
                if m is None:
                    m = {}
                    scan_by[r.employee] = m
                m[str(r.d)] = str(r.t)[11:16]
            for r in frappe.db.sql("""
                SELECT employee, attendance_date d, status FROM `tabAttendance`
                WHERE docstatus = 1
                  AND status IN ('Present','Half Day','Work From Home','Absent')
                  AND employee IN %s AND attendance_date BETWEEN %s AND %s
            """, (wemps, ev_from, ev_to), as_dict=True):
                if r.status == "Absent":
                    m = abs_by.get(r.employee)
                    if m is None:
                        m = {}
                        abs_by[r.employee] = m
                    m[str(r.d)] = 1
                else:
                    m = attp_by.get(r.employee)
                    if m is None:
                        m = {}
                        attp_by[r.employee] = m
                    m[str(r.d)] = 1
        # a Present-class record corrects an Absent one on the same day
        for pe in attp_by:
            if pe in abs_by:
                for dd in attp_by[pe]:
                    if dd in abs_by[pe]:
                        del abs_by[pe][dd]
        for w in workers:
            w["scan_dates"] = scan_by.get(w.employee, {})
            w["present_dates"] = attp_by.get(w.employee, {})
            w["absent_dates"] = abs_by.get(w.employee, {})
        a["today"] = str(frappe.utils.today())
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
                       CASE WHEN """ + TW_MATCH + """ THEN 1 ELSE 0 END tw,
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
                dayw[k].append({"employee": r.emp, "name": r.nm, "et": r.et,
                    "is_task_worker": r.tw, "qty": r.qty})
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
        cell_hours = {}
        cell_notes = {}
        if draft:
            for r in frappe.db.sql("""
                    SELECT employee, work_date, actual_quantity, hours, note
                    FROM `tabWork Actuals Employee` WHERE parent = %s
            """, (draft[0].name,), as_dict=True):
                cells[str(r.employee) + "~" + str(r.work_date)] = r.actual_quantity
                # only when somebody typed one -- an empty box is the screen's cue to
                # fill in that date's standard, and sending a 0 would suppress it
                if frappe.utils.flt(r.hours) > 0:
                    cell_hours[str(r.employee) + "~" + str(r.work_date)] = frappe.utils.flt(r.hours)
                # WHY THAT DAY WAS WHAT IT WAS. Per worker-day, not per document:
                # "sent home 11am, rain" is about one person's Tuesday and saying
                # it once for the whole grid would attach it to everybody.
                if (r.note or "").strip():
                    cell_notes[str(r.employee) + "~" + str(r.work_date)] = str(r.note).strip()
        a["cells"] = cells
        a["cell_hours"] = cell_hours
        a["cell_notes"] = cell_notes
        # also: is there a live (in-review/confirmed) doc blocking new entry?
        live = frappe.db.sql("""
            SELECT name, workflow_state FROM `tabWork Management Actuals`
            WHERE assignment = %s AND workflow_state IN (""" + sql_in(ST_ACT_PAST_FIRST) + """) LIMIT 1
        """, (name,), as_dict=True)
        a["live_name"] = live[0].name if live else None
        a["live_state"] = live[0].workflow_state if live else None
        # A LOCKED GRID STILL SHOWS ITS NOTES. Once the entry is submitted the
        # cells go read-only and `draft` is empty, so the notes typed on the way
        # in would vanish from the screen that collected them -- which is the
        # "a note nobody can read later is decoration" failure, one step earlier
        # than the report.
        if live and not draft:
            for r in frappe.db.sql("""
                    SELECT employee, work_date, note FROM `tabWork Actuals Employee`
                    WHERE parent = %s AND IFNULL(note, '') != ''
            """, (live[0].name,), as_dict=True):
                cell_notes[str(r.employee) + "~" + str(r.work_date)] = str(r.note).strip()
        out["detail"] = a

    elif action == "act_submit":
        # payload = per-worker-per-day cells: "emp~date~qty|emp~date~qty|..."
        assignment = frappe.form_dict.get("assignment")
        payload = frappe.form_dict.get("rows")
        # A NOTE PER WORKER-DAY, sent alongside rather than as a fifth `~` field.
        # Free text is exactly what must not be squeezed into a delimited string:
        # "sent home 11am, rain | machine down" would split into three cells and
        # a tilde in a note would move a quantity. JSON, keyed the same way the
        # grid keys a cell, so the two halves cannot get out of step.
        notes_raw = frappe.form_dict.get("notes")
        cell_note = {}
        if notes_raw:
            try:
                for nk, nv in (json.loads(notes_raw) or {}).items():
                    nt = str(nv or "").strip()
                    if nt:
                        # a note is a sentence, not an essay; the column is a
                        # Small Text and the report prints it in a cell
                        cell_note[str(nk)] = nt[:500]
            except Exception:
                # a malformed notes payload must not lose the quantities beside
                # it -- the grid is a worker-by-day entry somebody typed
                cell_note = {}
        submit_now = frappe.form_dict.get("submit_now")
        err = None
        if not assignment: err = "Assignment is required"
        # Submitting crosses a workflow transition; recording the work does not, and
        # stays open to whoever enters it. The step's own configured role gates the
        # submit and System Manager bypasses -- may_take_step()'s rule, which every
        # approve action already applies.
        #
        # Nothing enforced this before. The write below moves the state with
        # db.set_value(), under a comment saying it exists to get around the workflow's
        # transition-role gate because "the enterer doesn't hold" those roles, and that
        # "access is gated by the completion check above". A completion check gates the
        # document, never the person -- so the step was open to anybody who could reach
        # the endpoint.
        #
        # Refused as submit_blocked rather than as an error, which is what this screen
        # already does when the target is not complete: the grid is a worker-by-day
        # entry that must not be thrown away because the person who typed it may not be
        # the one to submit it. The actuals land as a Draft and the toast says why.
        if submit_now and not (STAGE_ROLE["actuals_submit"] in MY_ROLES
                               or "System Manager" in MY_ROLES):
            submit_now = 0
            out["submit_blocked"] = ("Saved as a draft: only " + str(STAGE_ROLE["actuals_submit"]) +
                                     " can submit actuals for approval. Ask somebody holding "
                                     "that role to submit it.")
        if err:
            out["error"] = err
        else:
            # read the assignment's plan link without get_doc (which hits the doctype-access gate
            # for farm managers / section heads / clerks who lack broad DocPerms)
            a_pr = frappe.db.get_value("Work Management Assigner", assignment, "planner_request")
            rate = 0
            unit_value = 0
            if a_pr:
                pinfo0 = frappe.db.get_value("Work Management Planner", a_pr,
                    ["rate", "daily_target", "task", "from_date"], as_dict=True)
                rate = frappe.utils.flt(pinfo0.rate) if pinfo0 else 0
                unit_value = rate
                # WAGE SNAP: a rate stored with too few decimals makes a full day pay
                # 340.50 / 387.60 instead of the intended wage. Snap to the wage the
                # task's rate period is actually derived from — the old code hardcoded
                # 340, which silently became wrong the day the wage moved to 387.
                # Rates are stored at 6dp since 2026-08-04, so this normally no-ops.
                if pinfo0 and frappe.utils.flt(pinfo0.daily_target) > 0 and rate > 0:
                    dw0 = rate * frappe.utils.flt(pinfo0.daily_target)
                    snap_wage = 0
                    if pinfo0.task:
                        wrow = frappe.db.sql("""
                            SELECT daily_wage_basis b FROM `tabWork Task Rate`
                            WHERE task = %(t)s AND derived = 1
                              AND valid_from <= %(d)s
                              AND (valid_to IS NULL OR valid_to >= %(d)s)
                            ORDER BY valid_from DESC LIMIT 1
                        """, {"t": pinfo0.task,
                              "d": pinfo0.from_date or frappe.utils.today()}, as_dict=True)
                        if wrow and frappe.utils.flt(wrow[0].b) > 0:
                            snap_wage = frappe.utils.flt(wrow[0].b)
                    if not snap_wage:
                        snap_wage = 340.0
                    if abs(dw0 - snap_wage) <= snap_wage * 0.01 and abs(dw0 - snap_wage) > 0.001:
                        unit_value = snap_wage / frappe.utils.flt(pinfo0.daily_target)
            edit_doc = frappe.form_dict.get("edit_doc")  # approver editing a pending doc in place
            # ONE doc per assignment: resume existing Draft/Rejected, else create new.
            existing = frappe.db.get_all("Work Management Actuals",
                filters={"assignment": assignment, "workflow_state": ["in", ["Draft", "Rejected"]]},
                pluck="name", limit=1)
            live = frappe.db.get_all("Work Management Actuals",
                filters={"assignment": assignment, "workflow_state": ["in", ST_ACT_ACTIVE]},
                pluck="name", limit=1)
            editing_pending = 0
            if edit_doc and frappe.db.exists("Work Management Actuals", edit_doc):
                estate = frappe.db.get_value("Work Management Actuals", edit_doc, "workflow_state")
                if estate in ST_ACT_WAITING:
                    editing_pending = 1
            # ── TIME & ATTENDANCE GATE (toggles in Work Management Settings): a
            # quantity recorded for a worker who is marked Absent, on approved
            # leave, or on their off day ON THAT EXACT DATE needs a logged override.
            att_conflicts = []
            att_override = frappe.form_dict.get("att_override")
            gate_absent = 1
            gate_leave = 1
            gate_off = 1
            gate_noscan = 1
            try:
                gate_absent = frappe.utils.cint(frappe.db.get_single_value("Work Management Settings", "att_block_absent"))
                gate_leave = frappe.utils.cint(frappe.db.get_single_value("Work Management Settings", "att_block_leave"))
                gate_off = frappe.utils.cint(frappe.db.get_single_value("Work Management Settings", "att_block_off"))
                gate_noscan = frappe.utils.cint(frappe.db.get_single_value("Work Management Settings", "att_block_noscan_actuals"))
            except Exception:
                pass
            if (gate_absent or gate_leave or gate_off or gate_noscan) and payload:
                pairs = []
                pemps = {}
                pdates = {}
                for c in (payload.split("|") if payload else []):
                    bits = c.split("~")
                    if len(bits) >= 3 and bits[0] and bits[1] and frappe.utils.flt(bits[2]) > 0:
                        pairs.append((bits[0], bits[1]))
                        pemps[bits[0]] = 1
                        pdates[bits[1]] = 1
                if pairs:
                    emp_t = tuple(pemps.keys())
                    date_t = tuple(pdates.keys())
                    dmin = min(pdates.keys())
                    dmax = max(pdates.keys())
                    absent_set = {}
                    if gate_absent:
                        for r in frappe.db.sql("""
                            SELECT att.employee, att.attendance_date FROM `tabAttendance` att
                            WHERE att.docstatus = 1 AND att.status = 'Absent'
                              AND att.employee IN %s AND att.attendance_date IN %s
                              AND NOT EXISTS (
                                SELECT 1 FROM `tabAttendance` pp
                                WHERE pp.employee = att.employee AND pp.attendance_date = att.attendance_date
                                  AND pp.docstatus = 1 AND pp.status IN ('Present','Half Day','Work From Home')
                              )
                        """, (emp_t, date_t), as_dict=True):
                            absent_set[(r.employee, str(r.attendance_date))] = 1
                    leave_ranges = {}
                    if gate_leave:
                        for r in frappe.db.sql("""
                            SELECT employee, leave_type, from_date, to_date FROM `tabLeave Application`
                            WHERE docstatus < 2 AND (status='Approved' OR docstatus=1)
                              AND from_date <= %s AND to_date >= %s AND employee IN %s
                        """, (dmax, dmin, emp_t), as_dict=True):
                            leave_ranges.setdefault(r.employee, []).append((str(r.from_date), str(r.to_date), r.leave_type or "leave"))
                    off_set = {}
                    emp_hl = {}
                    if gate_off:
                        for r in frappe.db.sql("""
                            SELECT name, holiday_list FROM `tabEmployee`
                            WHERE name IN %s AND IFNULL(holiday_list,'') != ''
                        """, (emp_t,), as_dict=True):
                            emp_hl[r.name] = r.holiday_list
                        if emp_hl:
                            for r in frappe.db.sql("""
                                SELECT parent, holiday_date FROM `tabHoliday`
                                WHERE parent IN %s AND holiday_date IN %s
                            """, (tuple(set(emp_hl.values())), date_t), as_dict=True):
                                off_set[(r.parent, str(r.holiday_date))] = 1
                    # positive-presence evidence per (employee, date): a biometric
                    # scan or a submitted Present attendance. Used by the no-scan
                    # check — future dates are skipped (nothing to scan yet).
                    #
                    # PER CELL DATE, not per today: `date_t` is the set of dates
                    # actually typed into the grid, and every lookup below is
                    # keyed `(employee, pd)`. A row backfilled to last Tuesday is
                    # judged against Tuesday. `ns_today` appears once, as the
                    # future cutoff, which is the only thing today decides here.
                    scan_set = {}
                    present_set = {}
                    if gate_noscan:
                        for r in frappe.db.sql("""
                            SELECT employee, DATE(`time`) d FROM `tabEmployee Checkin`
                            WHERE employee IN %s AND DATE(`time`) IN %s
                            GROUP BY employee, DATE(`time`)
                        """, (emp_t, date_t), as_dict=True):
                            scan_set[(r.employee, str(r.d))] = 1
                        for r in frappe.db.sql("""
                            SELECT employee, attendance_date FROM `tabAttendance`
                            WHERE docstatus = 1 AND status IN ('Present','Half Day','Work From Home')
                              AND employee IN %s AND attendance_date IN %s
                        """, (emp_t, date_t), as_dict=True):
                            present_set[(r.employee, str(r.attendance_date))] = 1
                    # the future cutoff, and nothing else: a date that has not
                    # arrived cannot be missing a scan
                    ns_today = str(frappe.utils.today())
                    reasons_map = {}
                    for (pe, pd) in pairs:
                        flagged = 0
                        if absent_set.get((pe, pd)):
                            reasons_map.setdefault(pe, []).append("marked Absent on " + pd)
                            flagged = 1
                        for (lf, lt, ltype) in leave_ranges.get(pe, []):
                            if lf <= pd <= lt:
                                reasons_map.setdefault(pe, []).append("on " + ltype + " on " + pd)
                                flagged = 1
                                break
                        if emp_hl.get(pe) and off_set.get((emp_hl[pe], pd)):
                            reasons_map.setdefault(pe, []).append("off day / holiday on " + pd)
                            flagged = 1
                        # no-scan check only when nothing else explains the day
                        if gate_noscan and not flagged and pd <= ns_today and not scan_set.get((pe, pd)) and not present_set.get((pe, pd)):
                            reasons_map.setdefault(pe, []).append("no scan or attendance on " + pd)
                    for ce in reasons_map:
                        cnm = frappe.db.get_value("Employee", ce, "employee_name") or ce
                        # de-duplicate + cap so the dialog stays readable
                        seenr = {}
                        rlist = []
                        for rr in reasons_map[ce]:
                            if rr not in seenr:
                                seenr[rr] = 1
                                rlist.append(rr)
                        att_conflicts.append({"employee": ce, "name": cnm, "reasons": rlist[:6]})
            # DUPLICATE-DAY GUARD: the same worker + the same task + the same date
            # already recorded in ANOTHER live actuals document means double pay
            # (two overlapping assignments for one task). Needs an explicit,
            # logged override.
            if payload and assignment:
                cur_task = frappe.db.get_value("Work Management Assigner", assignment, "task")
                pairs2 = []
                demps2 = {}
                ddates2 = {}
                for c2 in payload.split("|"):
                    bits2 = c2.split("~")
                    if len(bits2) >= 3 and bits2[0] and bits2[1] and frappe.utils.flt(bits2[2]) > 0:
                        pairs2.append((bits2[0], bits2[1]))
                        demps2[bits2[0]] = 1
                        ddates2[bits2[1]] = 1
                if pairs2 and cur_task:
                    dup_hits = frappe.db.sql("""
                        SELECT we.employee, we.work_date d, ac.name doc
                        FROM `tabWork Actuals Employee` we
                        INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
                        WHERE ac.workflow_state IN (""" + sql_in(ST_ACT_ENTERED) + """)
                          AND ac.task = %s AND ac.assignment != %s
                          AND we.actual_quantity > 0
                          AND we.employee IN %s AND we.work_date IN %s
                    """, (cur_task, assignment, tuple(demps2.keys()), tuple(ddates2.keys())), as_dict=True)
                    dupmap = {}
                    for r2 in dup_hits:
                        dupmap.setdefault((r2.employee, str(r2.d)), r2.doc)
                    dup_reasons = {}
                    for (pe2, pd2) in pairs2:
                        hit = dupmap.get((pe2, pd2))
                        if hit:
                            dup_reasons.setdefault(pe2, []).append("already has " + str(cur_task) + " recorded on " + pd2 + " in " + hit + " — double pay")
                    if dup_reasons:
                        merged = {}
                        for cx in att_conflicts:
                            merged[cx["employee"]] = cx
                        for pe2 in dup_reasons:
                            cx = merged.get(pe2)
                            if cx:
                                cx["reasons"] = cx["reasons"] + dup_reasons[pe2]
                            else:
                                nm2 = frappe.db.get_value("Employee", pe2, "employee_name") or pe2
                                att_conflicts.append({"employee": pe2, "name": nm2, "reasons": dup_reasons[pe2]})
            # ABSENT-day entries are an APPROVER's decision, and the approver is
            # whoever this chain says decides this farm's work -- not
            # `"Farm Manager" in roles`, a shipped job title that answered no to
            # Altura's Production Manager while the site's own farm-scoped step
            # named exactly him.
            #
            # Two steps open it: the farm-scoped step of this chain, asked for
            # THIS assignment's farm, and the step that ends the chain. That is
            # the same shape the old rule had -- the farm's own approver, or the
            # person above them -- said in the chain's vocabulary instead of in
            # one company's.
            has_absent_conflict = 0
            for cchk in att_conflicts:
                for rchk in cchk.get("reasons", []):
                    if "marked Absent" in rchk:
                        has_absent_conflict = 1
            can_override = 1
            ov_who = ACT_DECIDER_LABEL
            if has_absent_conflict:
                ov_farm = frappe.db.get_value("Work Management Assigner", assignment, "farm") if assignment else None
                allowed = ACT_MAY_DECIDE
                for ov_step in chain.approval_steps(STAGE_ROWS, ACT_DT, enabled_only=True):
                    if not ov_step.get("scoped"):
                        continue
                    ov_who = chain.label_of(ov_step, ov_who)
                    if chain.may_take(ov_step, MY_ROLES, farm=ov_farm, farms=ACT_FARMS) is None:
                        allowed = 1
                if not allowed:
                    can_override = 0
            if att_conflicts and att_override and not can_override:
                out["error"] = ("These entries include workers marked Absent — only " + str(ov_who) +
                                " (or " + str(ACT_DECIDER_LABEL) + ") can approve recording actuals on "
                                "an absent day. Ask them to enter or approve this, or fix the "
                                "attendance first.")
            elif att_conflicts and not att_override:
                out["needs_att_override"] = 1
                out["att_conflicts"] = att_conflicts
                out["can_override"] = can_override
                if not can_override:
                    out["override_blocked"] = ("Entries for workers marked Absent need " + str(ov_who) +
                        " (or " + str(ACT_DECIDER_LABEL) + ") — you can save the other workers by "
                        "removing the flagged ones, or ask them to approve.")
            elif live and not existing and not editing_pending:
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
                day_hours = {}
                long_days = {}
                released_after = []
                joined_before = []
                cells = payload.split("|") if payload else []
                # PUBLIC HOLIDAY PAY. A day worked on a public holiday is worth
                # HOLIDAY_X times an ordinary day -- 2 on a site that has said so,
                # 1 everywhere else, in which case none of this changes a figure.
                #
                # A PUBLIC holiday is a Holiday row on the worker's own list with
                # `weekly_off` NOT ticked. A row WITH it ticked is their rest day,
                # which is the off-day bonus's business and not this one's. Reading
                # the flag the wrong way round pays double for every rest day.
                #
                # Read once for the whole payload rather than per cell: a full grid
                # is one row per worker per day, and asking the Holiday table for
                # each of them is the same answer several hundred times.
                hx_days = {}
                if HOLIDAY_X != 1:
                    hx_emps = []
                    hx_dates = []
                    for c in cells:
                        if not c:
                            continue
                        hx_b = c.split("~")
                        if len(hx_b) < 3:
                            continue
                        if hx_b[0] not in hx_emps:
                            hx_emps.append(hx_b[0])
                        if hx_b[1] not in hx_dates:
                            hx_dates.append(hx_b[1])
                    if hx_emps and hx_dates:
                        hx_list = {}
                        for hx_r in frappe.db.sql("""
                            SELECT name, holiday_list FROM `tabEmployee`
                            WHERE name IN %(e)s AND IFNULL(holiday_list,'') != ''
                        """, {"e": tuple(hx_emps)}, as_dict=True):
                            hx_list[hx_r.name] = hx_r.holiday_list
                        hx_pub = {}
                        if hx_list:
                            for hx_h in frappe.db.sql("""
                                SELECT parent, holiday_date d FROM `tabHoliday`
                                WHERE parent IN %(p)s AND holiday_date IN %(d)s
                                  AND IFNULL(weekly_off, 0) = 0
                            """, {"p": tuple(set(hx_list.values())),
                                  "d": tuple(hx_dates)}, as_dict=True):
                                hx_pub[(hx_h.parent, str(hx_h.d))] = 1
                        for hx_e in hx_emps:
                            for hx_d in hx_dates:
                                if hx_list.get(hx_e) and hx_pub.get((hx_list[hx_e], hx_d)):
                                    hx_days[(hx_e, hx_d)] = 1
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
                    # HOW LONG, beside how much. A fourth field, optional: a client
                    # that sends three still works and gets the standard day, which
                    # is what every row written before this field existed means.
                    #
                    # standard_hours(), inlined -- the sandbox allows no functions.
                    # Keep in step with work_management/split_day.py.
                    wd_i = frappe.utils.getdate(wdate).weekday()  # Mon=0 .. Sun=6
                    if wd_i == 5:
                        std_h = frappe.utils.flt(STANDARD_DAY.get("saturday"))
                    elif wd_i == 6:
                        std_h = frappe.utils.flt(STANDARD_DAY.get("sunday"))
                    else:
                        std_h = frappe.utils.flt(STANDARD_DAY.get("weekday"))
                    hrs = frappe.utils.flt(bits[3]) if len(bits) > 3 else 0
                    if hrs <= 0:
                        hrs = std_h
                    day_hours[wdate] = frappe.utils.flt(day_hours.get(wdate)) + hrs
                    if std_h > 0 and hrs > std_h + 0.005:
                        long_days[wdate] = 1
                    etype = frappe.db.get_value("Employee", emp, "employment_type")
                    # the same test the substitute picker and payment use. Reading
                    # employment_type alone here meant a person payment WOULD pay had
                    # their day-rows written at zero and flagged out of payroll.
                    in_pay = 1 if frappe.db.sql("""
                        SELECT e.name FROM `tabEmployee` e WHERE e.name = %(n)s AND """ + TW_MATCH + """
                        LIMIT 1
                    """, {"n": emp}, as_dict=True) else 0
                    # 1 on an ordinary day, so the arithmetic is unchanged there.
                    hol_x = HOLIDAY_X if hx_days.get((emp, wdate)) else 1
                    amt = round(qty * (unit_value or rate) * hol_x, 2) if in_pay else 0
                    row = d.append("employees", {})
                    row.employee = emp
                    row.work_date = wdate
                    row.employment_type = etype
                    row.actual_quantity = qty
                    row.hours = hrs
                    row.count_in_payroll = in_pay
                    row.amount = amt
                    # the note for THIS worker on THIS date, keyed as the grid
                    # keys its cells. Absent is absent: an empty string would
                    # overwrite a note an approver had already typed.
                    row.note = cell_note.get(emp + "~" + str(wdate)) or None
                    # STORED, INCLUDING THE 1. What the amount was multiplied by is
                    # the only thing that makes it explainable six weeks later --
                    # and storing it on ordinary rows too is what tells a row this
                    # feature priced from a row written before it existed. Those
                    # older rows carry nothing here, and the discrepancy check reads
                    # that as "judge this one by the old rule", so history is never
                    # retroactively flagged as underpaid.
                    row.holiday_multiplier = hol_x
                    # RECORDED AFTER THEY WERE RELEASED. Warned, never refused: a
                    # clerk may be entering a day that genuinely predates the
                    # release, or correcting one, and blocking that would cost more
                    # than the wrong row it prevents. The audit lists the pattern.
                    rel_on = frappe.db.sql("""
                        SELECT we.left_date d FROM `tabWork Assignment Employee` we
                        WHERE we.parent = %s AND we.employee = %s
                          AND IFNULL(we.status,'Active') = 'Left'
                          AND we.left_date IS NOT NULL
                        ORDER BY we.left_date DESC LIMIT 1
                    """, (d.assignment, emp), as_dict=True)
                    if rel_on and str(wdate) > str(rel_on[0].d):
                        released_after.append(str(emp) + " on " + str(wdate) +
                            " (released " + str(rel_on[0].d) + ")")
                    # AND THE OTHER END. Work recorded before somebody joined is as
                    # doubtful as work recorded after somebody left, and until crew
                    # could be added mid-period there was nothing to check: every
                    # start_date was the assignment's own. Warned, not refused, for
                    # the same reason as the release end -- a clerk may be correcting
                    # a day, and blocking that costs more than the wrong row it stops.
                    joined_on = frappe.db.sql("""
                        SELECT we.start_date d FROM `tabWork Assignment Employee` we
                        WHERE we.parent = %s AND we.employee = %s
                          AND we.start_date IS NOT NULL
                        ORDER BY we.start_date ASC LIMIT 1
                    """, (d.assignment, emp), as_dict=True)
                    if joined_on and str(wdate) < str(joined_on[0].d):
                        joined_before.append(str(emp) + " on " + str(wdate) +
                            " (joined " + str(joined_on[0].d) + ")")
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
                # A DAY LONGER THAN THE DAY IS. Judged per date against that date's
                # own standard, so two ordinary full days are never read as one long
                # one. Warned and recorded: a wrong figure here spoils a metric and
                # never a wage, and somebody may genuinely have worked over.
                long_list = []
                for ld in day_hours:
                    ld_i = frappe.utils.getdate(ld).weekday()
                    if ld_i == 5:
                        ld_std = frappe.utils.flt(STANDARD_DAY.get("saturday"))
                    elif ld_i == 6:
                        ld_std = frappe.utils.flt(STANDARD_DAY.get("sunday"))
                    else:
                        ld_std = frappe.utils.flt(STANDARD_DAY.get("weekday"))
                    if ld_std > 0 and frappe.utils.flt(day_hours.get(ld)) > ld_std + 0.005:
                        long_list.append(str(ld) + " (" + str(frappe.utils.flt(day_hours.get(ld))) +
                            "h of " + str(ld_std) + ")")
                if long_list:
                    out["long_day_warning"] = ("More hours recorded than the day is long: " +
                        ", ".join(long_list[:6]) + ". Recorded as typed -- check the split if that "
                        "was not deliberate.")
                if released_after:
                    out["released_warning"] = ("Work recorded for a worker already released from "
                        "this assignment: " + ", ".join(released_after[:6]) +
                        ". Recorded as typed.")
                if joined_before:
                    out["joined_warning"] = ("Work recorded for a worker before they joined this "
                        "assignment: " + ", ".join(joined_before[:6]) + ". Recorded as typed.")
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
                              AND ac.workflow_state IN (""" + sql_in(ST_ACT_PAST_FIRST) + """)
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
                    # ── SUBMITTING SHORT ──────────────────────────────────────
                    # The site switch, and what it does when it is on. OFF is the
                    # default and is exactly the behaviour above: short of target
                    # the entry saves as a Draft and the screen says how much more
                    # is needed. Nothing below runs.
                    #
                    # ON, and short, the submit is ALLOWED and a reason is
                    # required -- and the plan is capped at what was done, which
                    # is the same outcome close-plan-early reaches: the remaining
                    # target is closed out, nothing further can be recorded or
                    # paid against the plan, and the unspent master-plan headroom
                    # is released so a new plan can be raised for the rest.
                    # Confirmed as the intended behaviour on 2026-09-23; the
                    # alternative ("submit short, plan stays open") is not built.
                    #
                    # The cap is done by bringing the plan's `quantity` down to
                    # what was delivered, with the approved figure kept in
                    # `original_qty`. That is one write with four consequences,
                    # all of them wanted:
                    #   * the hard target cap above refuses any further entry,
                    #     because the target is now the delivered figure;
                    #   * the master plan's headroom is `work_qty - SUM(planner
                    #     .quantity)`, so the unspent part returns to the budget
                    #     and a new plan can be raised against it;
                    #   * `audit.fallback_change()` already reads original_qty vs
                    #     quantity, so the plan's own banner says it moved;
                    #   * nothing is deleted -- the approved target is still on
                    #     the record, in the field that exists to hold it.
                    short_reason = (frappe.form_dict.get("short_reason") or "").strip()
                    short_by = 0
                    short_of = 0
                    if a_pr:
                        plan_target2 = frappe.utils.flt(frappe.db.get_value("Work Management Planner", a_pr, "quantity"))
                        if plan_target2 > 0:
                            odr = frappe.db.sql("""
                                SELECT COALESCE(SUM(ac.total_actual_qty),0) q
                                FROM `tabWork Management Actuals` ac
                                INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
                                WHERE a2.planner_request = %s
                                  AND ac.workflow_state IN (""" + sql_in(ST_ACT_PAST_FIRST) + """)
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
                            elif submit_now and ALLOW_SHORT_SUBMIT:
                                # short, and this site allows it. The reason is the
                                # price of the permission, so it is refused rather
                                # than defaulted -- a blank one would make "closed
                                # short" a category with nothing in it to read.
                                if not short_reason:
                                    submit_blocked_msg = (
                                        "A reason is required to submit short of the target — "
                                        + str(projected2) + " of " + str(plan_target2)
                                        + " done. Say why the target was not met, and the plan "
                                        "will be closed at what was done.")
                                else:
                                    completed = 1
                                    short_by = 1
                                    short_of = plan_target2 - projected2
                            else:
                                need2 = plan_target2 - projected2
                                # an em dash, not the six characters `\u2014`. The
                                # escape was doubled on the way through the port,
                                # so this refusal has always reached the screen as
                                # "Target not yet completed \\u2014 15.0 of 60.0".
                                submit_blocked_msg = ("Target not yet completed — " + str(projected2) + " of " +
                                                      str(plan_target2) + " done. Enter " + str(need2) +
                                                      " more before submitting. Saved as Draft.")
                            # document the balance vs target on THIS actual (snapshot)
                            d.custom_balance_qty = plan_target2 - projected2
                    if a_pr and not d.get("custom_balance_qty"):
                        d.custom_balance_qty = 0
                    if short_by:
                        # stamped on the actuals document before it is written, so
                        # the reason and the entry are one save
                        d.custom_short_reason = short_reason
                        d.custom_closed_early = 1
                        d.custom_close_reason = short_reason
                    if is_new:
                        d.insert(ignore_permissions=True)
                    elif editing_pending:
                        # keep the current workflow_state (approver edit-in-place)
                        d.save(ignore_permissions=True)
                    else:
                        d.workflow_state = "Draft"
                        d.save(ignore_permissions=True)
                    if submit_now and completed and not editing_pending:
                        # written directly rather than through save(): the workflow's own
                        # transition-role gate would refuse from the bottom of the stack,
                        # naming neither the role required nor the enterer's. Who may take
                        # this step is checked at the top of this action, against
                        # STAGE_ROLE["actuals_submit"], before any of this was written.
                        frappe.db.set_value("Work Management Actuals", d.name, "workflow_state", STAGE_NEXT["actuals_submit"], update_modified=False)
                        d.workflow_state = STAGE_NEXT["actuals_submit"]
                        # ── CAP THE PLAN AT WHAT WAS DONE ────────────────────
                        # Only once the entry has actually gone into the chain:
                        # capping a plan whose submit was then refused would
                        # close a week nobody had finished recording.
                        if short_by and a_pr:
                            sc_was = frappe.utils.flt(frappe.db.get_value(
                                "Work Management Planner", a_pr, "quantity"))
                            sc_orig = frappe.utils.flt(frappe.db.get_value(
                                "Work Management Planner", a_pr, "original_qty"))
                            sc_done = sc_was - frappe.utils.flt(short_of)
                            # THE MONEY COMES DOWN WITH THE QUANTITY. A master
                            # plan line budgets both, and its headroom is
                            # exhausted when EITHER runs out -- so capping the
                            # quantity and leaving `total_cost` where it was
                            # would release the work and keep the money, and the
                            # audit's "budget freed" would always read 0.
                            # Recomputed at the plan's own rate, which is the
                            # arithmetic the request was written with and the one
                            # adjust_target already uses. A plan with no rate
                            # keeps its cost rather than zeroing it: `sc_done * 0`
                            # would report the whole budget as released when
                            # nothing about the money is known.
                            sc_rate = frappe.utils.flt(frappe.db.get_value(
                                "Work Management Planner", a_pr, "rate"))
                            sc_was_cost = frappe.utils.flt(frappe.db.get_value(
                                "Work Management Planner", a_pr, "total_cost"))
                            sc_cost = (sc_done * sc_rate) if sc_rate > 0 else sc_was_cost
                            sc_set = {
                                # THE CAP. The target becomes what was delivered,
                                # so the hard cap above refuses further entry and
                                # the master plan's headroom -- work_qty minus the
                                # sum of its plans' quantities -- gets the unspent
                                # part back for a new plan.
                                "quantity": sc_done,
                                "total_cost": sc_cost,
                                "fulfilled_qty": sc_done,
                                "remaining_qty": 0,
                                "fulfilment_pct": 100 if sc_done > 0 else 0,
                                "custom_balance_qty": 0,
                                # and the plan is closed, which is what stops
                                # anything further being recorded or paid against
                                # it whatever the arithmetic says
                                "custom_close_state": "Closed",
                                "custom_closed_by": frappe.session.user,
                                "custom_closed_date": frappe.utils.today(),
                                "custom_close_reason": short_reason,
                            }
                            # THE APPROVED FIGURE IS KEPT. original_qty is the
                            # snapshot this app already uses for a target moved
                            # after approval, and audit.fallback_change() reads it
                            # -- so the plan's own banner says the target came
                            # down, and by how much, without a second mechanism.
                            # Only written when empty: a plan whose target had
                            # already been adjusted keeps the figure it was
                            # APPROVED at, not the one it was adjusted to.
                            if not sc_orig:
                                sc_set["original_qty"] = sc_was
                                sc_set["original_cost"] = sc_was_cost
                            frappe.db.set_value("Work Management Planner", a_pr, sc_set,
                                                update_modified=False)
                            # RELEASE THE CREW. A closed plan holds nobody: every
                            # still-active worker is freed for other tasks, which
                            # is what close-plan-early does and what stops a capped
                            # plan quietly blocking next week's assignment.
                            sc_freed = 0
                            for sc_r in frappe.db.sql("""
                                SELECT we.name row_id
                                FROM `tabWork Assignment Employee` we
                                INNER JOIN `tabWork Management Assigner` a2 ON we.parent = a2.name
                                WHERE a2.planner_request = %s
                                  AND IFNULL(we.status,'Active') = 'Active'
                            """, (a_pr,), as_dict=True):
                                frappe.db.set_value("Work Assignment Employee", sc_r.row_id,
                                    "status", "Left", update_modified=False)
                                frappe.db.set_value("Work Assignment Employee", sc_r.row_id,
                                    "left_date", frappe.utils.today(), update_modified=False)
                                sc_freed = sc_freed + 1
                            # ── SAID ON THE RECORD, ON BOTH DOCUMENTS ────────
                            # The figures and the reason, as a comment on each, so
                            # the plan trace and the actuals history both carry it.
                            # A stamped field can be read; a comment is what a
                            # person scrolling the record actually sees.
                            sc_line = ("Closed short: " + str(sc_done) + " of " + str(sc_was)
                                + " done, " + str(frappe.utils.flt(short_of)) + " short. "
                                + "Reason: " + short_reason.rstrip(". ") + ".")
                            try:
                                frappe.get_doc("Work Management Actuals", d.name).add_comment(
                                    "Comment", sc_line + " — submitted by " + frappe.session.user + ".")
                                frappe.get_doc("Work Management Planner", a_pr).add_comment(
                                    "Comment", sc_line + " Plan capped at what was done by "
                                    + frappe.session.user + "; the unspent "
                                    + str(frappe.utils.flt(short_of)) + " (KES "
                                    + str(round(sc_was_cost - sc_cost, 2)) + ")"
                                    + " is released back to the master plan. "
                                    + str(sc_freed) + " worker(s) released.")
                            except Exception:
                                # a comment is a record, not the record: the cap
                                # itself is written above and must not be undone by
                                # a failure to narrate it
                                pass
                            frappe.db.commit()
                            out["closed_short"] = 1
                            out["short_of"] = frappe.utils.flt(short_of)
                            out["short_reason"] = short_reason
                            out["capped_target"] = sc_done
                            out["approved_target"] = sc_was
                            out["short_cost"] = frappe.utils.flt(sc_was_cost - sc_cost, 2)
                            out["workers_released"] = sc_freed
                            out["closed_short_message"] = (
                                "Submitted short and the plan is now closed at " + str(sc_done)
                                + " of " + str(sc_was) + ". The unspent "
                                + str(frappe.utils.flt(short_of))
                                + " has gone back to the master plan — raise a new plan for the "
                                "rest if the work is still to be done.")
                    elif submit_now and not completed and not editing_pending:
                        # keep as Draft; report why submit didn't go through
                        out["submit_blocked"] = submit_blocked_msg or "Target not completed; saved as Draft."
                    # audit trail: an attendance override is always logged on the document
                    if att_conflicts and att_override:
                        ov_lines = []
                        for cx in att_conflicts:
                            ov_lines.append(cx["name"] + " (" + cx["employee"] + "): " + "; ".join(cx["reasons"]))
                        d.add_comment("Comment", "Attendance override by " + frappe.session.user + " — actuals recorded despite: " + " | ".join(ov_lines))
                        out["att_overridden"] = len(att_conflicts)
                    out["name"] = d.name
                    out["workflow_state"] = d.workflow_state
                    out["total_payment"] = d.total_payment
                    out["payroll_people"] = d.payroll_people
                    out["actual_people"] = d.actual_people
                    out["total_actual_qty"] = d.total_actual_qty
                    out["tw_qty"] = d.custom_tw_qty
                    out["salaried_qty"] = d.custom_salaried_qty
                    out["balance_qty"] = d.custom_balance_qty
                    # A NOTE WITH NO ROW TO LIVE ON. Only a cell with a quantity
                    # becomes a child row, so a note typed against an empty cell
                    # has nothing to be saved with. Reported rather than dropped
                    # in silence -- somebody typed it, and a note that vanishes is
                    # worse than one that was never offered.
                    nd_kept = {}
                    for nd_r in d.employees:
                        nd_kept[str(nd_r.employee) + "~" + str(nd_r.work_date)] = 1
                    nd_lost = [nk for nk in cell_note if nk not in nd_kept]
                    if nd_lost:
                        out["notes_dropped"] = len(nd_lost)
                        out["notes_dropped_warning"] = (
                            str(len(nd_lost)) + " note" + ("" if len(nd_lost) == 1 else "s") +
                            " could not be saved: a note belongs to a recorded day, and "
                            "these cells have no quantity. Enter the quantity, or leave the "
                            "note off. (" + ", ".join(sorted(nd_lost)[:5]) + ")")
    elif action == "act_my":
        out["actuals"] = frappe.db.get_all("Work Management Actuals",
            filters={"entered_by":frappe.session.user},
            fields=["name","assignment","farm","task","total_actual_qty","actual_people","payroll_people",
                    "total_payment","cost_variance","workflow_state","entry_date"],
            order_by="creation desc", limit=200)

    elif action == "act_pending":
        # WHICH QUEUE, by the key the tab carries. `Pending HR Head` was both the
        # default and the name of a step this site may not have; the first enabled
        # approval step is the honest default. A state is still accepted, because
        # that is the other name the server itself publishes for a step.
        pd_keys = chain.stage_keys(STAGE_ROWS, ACT_DT, enabled_only=True)
        pd_step, pd_bad = chain.resolve(STAGE_ROWS, ACT_DT,
            stage=frappe.form_dict.get("stage") or (pd_keys[0] if pd_keys else None))
        if pd_bad or not pd_step:
            out["error"] = pd_bad or "This chain has no approval step to list."
        else:
            fmflt = {"workflow_state": pd_step["state"]}
            # A FARM-SCOPED step shows a farm manager their own farms and nobody
            # else's -- read from the step's own flag, not from a state name.
            if pd_step.get("scoped"):
                fmbypass = ("System Manager" in MY_ROLES) or ("General Manager" in MY_ROLES)
                if not fmbypass:
                    fmflt["farm"] = ["in", ACT_FARMS] if ACT_FARMS else ["in", ["__none__"]]
            out["pending"] = frappe.db.get_all("Work Management Actuals",
                filters=fmflt,
                fields=["name","assignment","farm","task","block_section","planned_people","actual_people","payroll_people",
                        "planned_cost","total_payment","cost_variance","total_actual_qty","entered_by","entry_date"],
                order_by="entry_date desc", limit=200)
            out["step"] = pd_step["key"]
            out["step_label"] = chain.label_of(pd_step)

    elif action in ("act_approve", "act_fm_approve", "act_hr_approve", "act_gm_approve"):
        # ONE APPROVAL, WHICHEVER STEP IT IS. There were three branches here, one
        # per step of the chain as it shipped, and between them they knew the whole
        # of the old vocabulary. The step is resolved from the configured chain
        # now, by the key the screen was handed with its tab, and everything that
        # used to be per-branch is read off the step: `on`, `state`, `role`,
        # `scoped`, `next_state`. What the final approval does -- confirm the
        # document and settle the plan it belongs to -- hangs off "the step whose
        # next_state is the terminal", which is what made it the last step at all.
        #
        # The three old action names remain, as the keys they always meant.
        ap_alias = {"act_fm_approve": "actuals_farm_manager",
                    "act_hr_approve": "actuals_hr_head",
                    "act_gm_approve": "actuals_gm"}
        nm = frappe.form_dict.get("name")
        ap_stage = ap_alias.get(action) or frappe.form_dict.get("stage")
        cur = frappe.db.get_value(ACT_DT, nm,
            ["workflow_state", "farm", "assignment"], as_dict=True)
        ap_step, ap_bad = chain.resolve(STAGE_ROWS, ACT_DT, stage=ap_stage,
                                        state=cur.workflow_state if cur else None)
        ap_why = None
        if ap_step:
            ap_why = chain.may_take(ap_step, MY_ROLES, farm=cur.farm if cur else None,
                                    farms=ACT_FARMS)
        if not cur:
            out["error"] = "Record not found"
        elif ap_bad:
            out["error"] = ap_bad
        elif not ap_step:
            out["error"] = "Not awaiting approval (state: " + str(cur.workflow_state) + ")"
        elif cur.workflow_state != ap_step["state"]:
            out["error"] = ("Not at the " + str(chain.label_of(ap_step)) +
                            " step (state: " + str(cur.workflow_state) + ")")
        elif ap_why:
            out["error"] = ap_why
        else:
            ap_next = ap_step["next_state"]
            # direct DB writes, bypassing the get_doc doctype-access gate and the
            # workflow engine. Trusted script; the step and the role were verified
            # above.
            frappe.db.set_value(ACT_DT, nm, "workflow_state", ap_next, update_modified=False)
            ap_by, ap_on = ACT_STAMP.get(ap_step["key"], (None, None))
            if ap_by:
                try:
                    frappe.db.set_value(ACT_DT, nm, ap_by, frappe.session.user, update_modified=False)
                    frappe.db.set_value(ACT_DT, nm, ap_on, frappe.utils.today(), update_modified=False)
                except Exception:
                    pass
            out["name"] = nm
            out["workflow_state"] = ap_next
            out["step"] = ap_step["key"]
            out["step_label"] = chain.label_of(ap_step)
            if ap_next != ACT_TERMINAL:
                if not ap_by:
                    # an added step has no column of its own, so who took it is
                    # recorded where the document already keeps its history
                    frappe.get_doc(ACT_DT, nm).add_comment(
                        "Comment", str(chain.label_of(ap_step)) + " taken by " +
                        frappe.session.user + " — now " + str(ap_next))
            else:
                # THE FINAL APPROVAL. Confirming the actuals submits the document
                # and its lines, then settles the plan: how much of the target this
                # confirms, and -- when the target is met -- freeing the crew.
                frappe.db.set_value(ACT_DT, nm, "docstatus", 1, update_modified=False)
                for kid in frappe.db.get_all("Work Actuals Employee", filters={"parent": nm}, pluck="name"):
                    frappe.db.set_value("Work Actuals Employee", kid, "docstatus", 1, update_modified=False)
                fulfilled = 0
                remaining = 0
                asg = cur.assignment and frappe.db.get_value("Work Management Assigner", cur.assignment, "planner_request")
                if asg:
                    conf = frappe.db.sql("""
                        SELECT COALESCE(SUM(ac.total_actual_qty),0) q
                        FROM `tabWork Management Actuals` ac
                        INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
                        WHERE a2.planner_request = %s AND ac.workflow_state = %s
                    """, (asg, ACT_TERMINAL), as_dict=True)
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
                out["fulfilled_qty"] = fulfilled
                out["remaining_qty"] = remaining
                out["workers_released"] = released_auto

    elif action in ("act_approve_bulk", "act_reject_bulk"):
        # SEVERAL AT A TIME, one at a time. Every document goes through the very
        # branch its own button uses -- same role gate, same stage check, same
        # writes -- because this re-enters this dispatcher rather than restating
        # any of it. See work_management/bulk.py.
        #
        # `stage` picks WHICH approval, and the screen only ever sends the stage
        # whose queue is on screen: this tab shows one stage at a time, and
        # approving across stages in one press would mean approving work the user
        # is not looking at.
        # It is a stage KEY, validated against the chain this site runs. It used to
        # be one of `fm`, `gm`, `hr` -- three abbreviations of the shipped chain --
        # so a configured chain could not name its own queue here at all.
        bk_names = frappe.form_dict.get("names")
        try:
            bk_names = json.loads(bk_names or "[]")
        except Exception:
            bk_names = []
        bk_reject = action == "act_reject_bulk"
        bk_stage = str(frappe.form_dict.get("stage") or "").strip()
        bk_reason = frappe.form_dict.get("reason")
        bk_bad = bulk.check_selection(bk_names, bk_reason, needs_reason=bk_reject)
        bk_step = None
        if not bk_bad and not bk_reject:
            bk_step, bk_bad = chain.resolve(STAGE_ROWS, ACT_DT, stage=bk_stage)
            if not bk_bad and not bk_step:
                bk_bad = chain.unknown_stage(bk_stage, STAGE_ROWS, ACT_DT)
        if bk_bad:
            out["error"] = bk_bad
        else:
            bk_ok, bk_failed = bulk.run_bulk(
                wm_actuals, "act_reject" if bk_reject else "act_approve", bk_names,
                base={"reason": bk_reason} if bk_reject
                     else {"stage": bk_step["key"]})
            out["ok"] = bk_ok
            out["failed"] = bk_failed
            out["summary"] = bulk.summarise(bk_ok, bk_failed,
                "rejected" if bk_reject else "approved")

    elif action == "act_reject":
        nm = frappe.form_dict.get("name")
        cur = frappe.db.get_value("Work Management Actuals", nm, ["workflow_state","docstatus","assignment"], as_dict=True)
        # Rejectable at every approval step this chain holds, switched-off ones
        # included -- rejecting is not a step and is how a document parked in a
        # retired step gets out of it -- and from the terminal state, which is
        # this pipeline's own "un-confirm". Named four states, which on a
        # reconfigured chain is either too few or entirely wrong.
        rj_at = chain.at_state(STAGE_ROWS, ACT_DT, cur.workflow_state if cur else None)
        if not cur or not (rj_at or cur.workflow_state == ACT_TERMINAL):
            out["error"] = "Not rejectable (state: " + str(cur.workflow_state if cur else "not found") + ")"
        else:
            # if submitted, "cancel" it by flipping docstatus to 2 (Cancelled) directly, then mark Rejected.
            if cur.docstatus == 1:
                frappe.db.set_value("Work Management Actuals", nm, "docstatus", 2, update_modified=False)
                for kid in frappe.db.get_all("Work Actuals Employee", filters={"parent": nm}, pluck="name"):
                    frappe.db.set_value("Work Actuals Employee", kid, "docstatus", 2, update_modified=False)
            frappe.db.set_value("Work Management Actuals", nm, "workflow_state", "Rejected", update_modified=False)
            # WHY, on the document's own history. Optional here so nothing that
            # calls this today changes; required when rejecting in bulk, where it
            # is the only thing telling one refusal from twenty.
            rj_why = str(frappe.form_dict.get("reason") or "").strip()
            if rj_why:
                frappe.get_doc("Work Management Actuals", nm).add_comment(
                    "Comment", "Rejected by " + frappe.session.user + ": " + rj_why)
                out["reason"] = rj_why
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
        out["user"] = frappe.session.user
        # `is_gm` keeps its NAME -- it has been in this payload since the close
        # feature shipped and an older screen may still read it -- but not its
        # meaning. It is no longer "holds the role General Manager"; it is
        # whoever takes the step that ends this chain, which is the only honest
        # answer on a site that hands that step to somebody else.
        out["is_gm"] = ACT_MAY_DECIDE
        out["can_request"] = ACT_MAY_REQUEST
        out["can_close_now"] = ACT_MAY_DECIDE
        out["decider_label"] = ACT_DECIDER_LABEL
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
        err = None
        if not plan:
            err = "No plan resolved for this close request"
        if not reason:
            err = "A reason is required to request a close"
        if not err and not ACT_MAY_REQUEST:
            # named from the chain: "need Farm Manager or Section Head" sent an
            # Altura reader looking for two roles the site has not got.
            err = ("Only somebody who takes a step of this work's approval chain can "
                   "ask for a plan to be closed. " + str(ACT_DECIDER_LABEL) + " decides it.")
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
        if not ACT_MAY_DECIDE:
            out["pending"] = []
            out["not_gm"] = 1
            # WHY, in the server's words. The screen said "Only the General
            # Manager sees close requests" -- a shipped role name printed at a
            # site that may hand the last step to somebody else entirely.
            out["not_gm_why"] = ("Close requests are decided by "
                + str(ACT_DECIDER_LABEL) + ", and are not yours to see.")
        else:
            rows = frappe.db.get_all("Work Management Planner",
                filters={"custom_close_state": "Close Requested"},
                fields=["name", "farm", "block_section", "task", "quantity", "fulfilled_qty",
                        "remaining_qty", "uom", "custom_close_requested_by", "custom_close_request_date",
                        "custom_close_reason"],
                order_by="custom_close_request_date desc", limit=200)
            # fulfilled/remaining stored on the plan are stale — compute LIVE from
            # every recorded actuals doc (drafts and pending included, since a
            # close finalises them). done = recorded so far; remaining = target - done.
            if rows:
                done_map = {}
                for r2 in frappe.db.sql("""
                    SELECT a2.planner_request pr, COALESCE(SUM(ac.total_actual_qty),0) q,
                           COALESCE(SUM(CASE WHEN ac.workflow_state = 'CONFIRMED' THEN ac.total_actual_qty ELSE 0 END),0) qc
                    FROM `tabWork Management Actuals` ac
                    INNER JOIN `tabWork Management Assigner` a2 ON ac.assignment = a2.name
                    WHERE a2.planner_request IN %s
                      AND ac.workflow_state IN (""" + sql_in(ST_ACT_ENTERED) + """)
                    GROUP BY a2.planner_request
                """, (tuple([r.name for r in rows]),), as_dict=True):
                    done_map[r2.pr] = (frappe.utils.flt(r2.q), frappe.utils.flt(r2.qc))
                for r in rows:
                    dq = done_map.get(r.name, (0, 0))
                    r["fulfilled_qty"] = dq[0]
                    r["confirmed_qty"] = dq[1]
                    tgt = frappe.utils.flt(r.get("quantity"))
                    rem = tgt - dq[0]
                    r["remaining_qty"] = rem if rem > 0 else 0
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
        err = None
        if not plan:
            err = "No plan resolved for this close"
        if not err and not ACT_MAY_DECIDE:
            err = "Only " + str(ACT_DECIDER_LABEL) + " can confirm a close."
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
                        ac.workflow_state IN (""" + sql_in(ST_ACT_OPEN) + """)
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
        # Who enters work, and who works with payments, are capabilities set in
        # Settings -- they used to be these role names, compiled in.
        out["is_clerk"] = 1 if (("System Manager" in rl) or any(
            r in rl for r in (CAPABILITIES.get("enter_work") or []))) else 0
        out["is_hr_head"] = ("System Manager" in rl) or any(_r_ in rl for _r_ in HR_HEAD_ROLES)
        # `is_gm` used to live here -- "General Manager" in rl -- and gated the
        # Close Requests queue, the close dialog's verb and, on the planner, the
        # button's own wording. It named a role a site need not have, so on
        # Altura the person the chain puts at the end of it was offered none of
        # them. `may_close_plans` below answers the same question from the chain
        # and nothing reads the role name any more.
        out["is_accounts"] = 1 if (("System Manager" in rl) or any(
            r in rl for r in (CAPABILITIES.get("handle_payments") or []))) else 0
        # Whoever decides a farm's work, from the farm-scoped steps' own roles.
        # `"Farm Manager" in rl` sat in front of that list -- this app's shipped
        # role name, which a site that maps the step onto its own role does not
        # have, and which a site that has it for another reason gets for free.
        out["is_farm_manager"] = 1 if (("System Manager" in rl)
            or any(_r_ in rl for _r_ in (FARM_APPROVER_ROLE or {}).values())) else 0
        # THE TAB STRIP, from the configured chain rather than from a list
        # written into the screen. NOT filtered by `rl`: which queues exist is
        # not a question about who is looking, and answering it that way hid the
        # farm manager's queue from everybody else. See
        # work_management/stage_pills.py.
        # WHETHER THIS PERSON APPROVES ANYTHING HERE, and what to call them --
        # both from the configured chain. The header said "· HR Head" for anyone
        # the shipped HR question said yes to, so Altura's Production Manager was
        # greeted as an HR Head. `chain.takeable()` asks the same question the
        # approve action asks, on the same data, so the tab is offered exactly
        # when a press would be allowed and the suffix names the step it would
        # take.
        out["is_approver"] = 1 if chain.takeable(
            STAGE_ROWS, 'Work Management Actuals', rl, farms=ACT_FARMS) else 0
        out["approver_label"] = chain.approver_suffix(
            STAGE_ROWS, ['Work Management Actuals'], rl, farms=ACT_FARMS)
        # MAY THEY CHANGE THE CREW. The grid decided this itself, by OR-ing the
        # three role flags above -- two of which name roles a site need not have
        # -- so the Add-a-worker button was dark for the very person a_add_crew
        # would have allowed. One answer, from the assigner's chain, which is the
        # chain a_add_crew and a_release actually gate on.
        ac_asg_farms = []
        for _ac_farm, _ac_role in (FARM_APPROVER_ROLE or {}).items():
            if _ac_role in rl and _ac_farm not in ac_asg_farms:
                ac_asg_farms.append(_ac_farm)
        out["may_change_crew"] = 1 if chain.takeable(
            STAGE_ROWS, 'Work Management Assigner', rl, farms=ac_asg_farms) else 0
        # ...and whether the Close Requests queue is theirs. The screen asked
        # `is_gm`, a shipped role name, for a queue that belongs to whoever
        # takes the step ending this chain -- which act_close_pending and
        # act_close_confirm now both gate on.
        out["may_close_plans"] = ACT_MAY_DECIDE
        out["decider_label"] = ACT_DECIDER_LABEL
        out["stages"] = stage_pills.for_document_type(
            "Work Management Actuals", STAGE_ROWS, FARM_APPROVER_ROLE, rl)

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
                WHERE a.workflow_state IN (""" + sql_in(ST_ASG_ACTIVE) + """)
                  AND a.name != %s
                  AND IFNULL(we.status,'Active') = 'Active'
                  AND a.from_date <= %s AND a.to_date >= %s
            """, (nm, adates.to_date, adates.from_date), as_dict=True)
            for r in busyrows:
                busy_map[r.emp] = 1
        cands = []
        for emp in frappe.db.sql("""
                SELECT e.name, e.employee_name FROM `tabEmployee` e
                WHERE e.status = 'Active' AND e.custom_farm = %(f)s AND """ + TW_MATCH + """
                ORDER BY e.employee_name LIMIT 1000
            """, {"f": farm}, as_dict=True):
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
            rep_ok = frappe.db.sql("""
                SELECT e.name FROM `tabEmployee` e WHERE e.name = %(n)s AND """ + TW_MATCH + """
                LIMIT 1
            """, {"n": replacement}, as_dict=True)
            if not rep_ok:
                err = ("Replacement is not a task worker under the current Work Management "
                       "Settings, so their work could never be paid through this system.")
        if not err:
            # cross-assignment overlap guard: replacement must not be Active elsewhere over this period
            rdates = frappe.db.get_value("Work Management Assigner", nm, ["from_date", "to_date"], as_dict=True)
            if rdates and rdates.from_date and rdates.to_date:
                clash = frappe.db.sql("""
                    SELECT a.name asg
                    FROM `tabWork Assignment Employee` we
                    INNER JOIN `tabWork Management Assigner` a ON we.parent = a.name
                    WHERE a.workflow_state IN (""" + sql_in(ST_ASG_ACTIVE) + """)
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
                child.employment_type = rep_type
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
