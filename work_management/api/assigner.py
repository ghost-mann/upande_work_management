# Ported from the upstream mirror's Server Script "wm_assigner" (API) — logic unchanged.
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
def wm_assigner(**kwargs):
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
    ST_ASG_WAITING = chain_states(_cfg, "Work Management Assigner", "waiting")
    ST_ASG_OPEN = chain_states(_cfg, "Work Management Assigner", "open")
    CAPABILITIES = _cfg["capabilities"]
    ALLOW_CONCURRENT_PLANS = _cfg["allow_concurrent_master_plans"]
    ALLOW_SPLIT_DAY = _cfg["allow_split_day"]
    STANDARD_DAY = _cfg["standard_day"]

    # ==================================================================
    # SERVER SCRIPT — "WM Assigner" (API, api_method=wm_assigner)
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
    # This screen advances one document type, and every approval below addresses a
    # step of its chain by KEY -- never by the step's action, state, label or role.
    # See work_management/chain.py for why: the screen used to post the workflow
    # ACTION it had been handed for the tab's wording (`FM Approve`) as this
    # dispatcher's own `action`, and got `unknown action: FM Approve`.
    ASG_DT = "Work Management Assigner"
    ASG_TERMINAL = STAGE_STATES.get(ASG_DT, {}).get("terminal")
    # Which farms this person decides. The farm dimension, asked once: a
    # farm-scoped step narrows to these, an unscoped one ignores them entirely.
    ASG_FARMS = []
    for _asg_farm, _asg_role in (FARM_APPROVER_ROLE or {}).items():
        if _asg_role in MY_ROLES and _asg_farm not in ASG_FARMS:
            ASG_FARMS.append(_asg_farm)

    # WHO MAY CHANGE AN APPROVED CREW -- add somebody, or release them.
    #
    # Both gates read `rr.startswith("Farm Manager")`, the HR head list and
    # `"General Manager" in roles`: three job titles out of the chain this app
    # ships with, and none of them Altura's, where every one of those steps is
    # taken by a Production Manager. He was refused by his own pipeline.
    #
    # The chain answers it. Changing the crew on work that has already been
    # approved is a decision of the people who approved it, so the test is
    # "takes any enabled step of this chain" -- the same rule, without naming
    # anybody, and with farm scope carried by chain.may_take() for the steps
    # that have it.
    ASG_MAY_CHANGE_CREW = 1 if chain.takeable(
        STAGE_ROWS, ASG_DT, MY_ROLES, farms=ASG_FARMS) else 0
    # ...and who that is, for the refusal. The steps' own configured labels, so
    # the sentence sends the reader to a desk the site actually has -- it used to
    # say "a Farm Manager, the HR head or the GM" whatever the chain was.
    ASG_APPROVER_LABELS = []
    for _asg_step in chain.approval_steps(STAGE_ROWS, ASG_DT, enabled_only=True):
        _asg_lbl = chain.short_label(_asg_step)
        if _asg_lbl and _asg_lbl not in ASG_APPROVER_LABELS:
            ASG_APPROVER_LABELS.append(_asg_lbl)
    ASG_APPROVERS = (" or ".join(ASG_APPROVER_LABELS) if ASG_APPROVER_LABELS
        else "an approver on this work")

    # WHERE A SHIPPED STEP STAMPS ITSELF. These are columns this doctype already
    # has, named after the chain as it shipped, and a column cannot be renamed by
    # a Settings row. So the mapping is from stage KEY -- which is stable -- to the
    # pair of columns that step has always written, and it is a fallback constant
    # rather than a rule: a step this app never shipped stamps nothing extra and
    # is recorded, like every intermediate step already is, on the document's own
    # comment history.
    ASG_STAMP = {
        "assigner_farm_manager": ("fm_approved_by", "fm_approval_date"),
        "assigner_hr_head": ("hr_approved_by", "hr_approval_date"),
        "assigner_gm": ("gm_approved_by", "gm_approval_date"),
    }

    # Who may do what, beyond approving. In the app, port_app.py strips this and
    # rebuilds CAPABILITIES from get_config(), so it is whatever Settings holds. Here
    # it is what this site has always allowed -- these were four lists compiled into
    # the code, naming this company's job titles, so a farm could say who approves a
    # plan and not who may change a rate.

    # May one worker's day be shared between two tasks?
    #
    # Off, a worker already on a live assignment over these dates cannot be put on
    # another -- which is how this has always worked, and the guard below refuses.
    # On, the guard says so and lets it through, and hours on the actuals rows keep
    # the day counting once however many tasks it spanned.
    #
    # port_app.py strips both of these and rebuilds them from get_config(), so in
    # the app they are whatever Work Management Settings holds. Here they are the
    # literals, and False keeps live behaving exactly as it does today.

    # How long a full day is. The denominator every man-day figure divides by.
    # Sunday is worked on these farms, so it is a full day and not zero.

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
    elif action == "a_approved_planners":
        # How many plans the picker offers, applied at the END -- after the ones
        # already assigned, closed early or fully delivered have been dropped.
        #
        # Both caps here were wrong, and in different ways.
        #
        # The 200 on the fetch was spent before the filtering: of the newest 200
        # approved plans, 182 were already tied to a live assignment, so the picker
        # offered 18 -- while 114 genuinely unassigned plans sat outside the window
        # and could not be assigned at all.
        #
        # The 500 on `assigned` was worse than a display limit. It builds the map of
        # which plans are already taken, and there are 1,543 live assignments, so it
        # knew 496 of the 1,518 taken plans -- with no order_by, an arbitrary 496.
        # Every plan it missed reads as free, which is how the same plan could be
        # assigned twice. It takes one small field, so it now fetches all of them.
        SHOWN = 200
        plans = frappe.db.get_all("Work Management Planner", filters={"workflow_state":"Approved"},
            fields=["name","farm","block_section","task","task_kpi","from_date","to_date","people_per_day","total_cost","quantity","custom_close_state"],
            order_by="approval_date desc")
        assigned = frappe.db.get_all("Work Management Assigner",
            filters={"workflow_state":["in", ST_ASG_ACTIVE]}, fields=["planner_request"])
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
        # NOW the cap, on plans that are genuinely assignable rather than on the fetch
        if len(rows) > SHOWN:
            rows = rows[:SHOWN]
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
                WHERE a.workflow_state IN (""" + sql_in(ST_ASG_ACTIVE) + """)
                  AND a.name != %s
                  AND IFNULL(we.status,'Active') = 'Active'
                  AND a.from_date <= %s AND a.to_date >= %s
            """, (exclude_asg, pt, pf), as_dict=True)
            for r in rows:
                if r.emp and r.emp not in allocated:
                    allocated[r.emp] = {"assignment": r.asg, "farm": r.farm, "task": r.task}
        # ── TIME & ATTENDANCE flags (toggles live in Work Management Settings).
        # leave = approved Leave Application overlapping the window; absent = a
        # submitted Absent attendance inside the window (past days only, naturally);
        # off = the window is FULLY covered by holiday-list off days. ──
        att_absent_on = 1
        att_leave_on = 1
        att_off_on = 1
        off_rule = "Entire window"
        try:
            att_absent_on = frappe.utils.cint(frappe.db.get_single_value("Work Management Settings", "att_block_absent"))
            att_leave_on = frappe.utils.cint(frappe.db.get_single_value("Work Management Settings", "att_block_leave"))
            att_off_on = frappe.utils.cint(frappe.db.get_single_value("Work Management Settings", "att_block_off"))
            off_rule = str(frappe.db.get_single_value("Work Management Settings", "att_off_window_rule") or "Entire window")
        except Exception:
            pass
        leave_map = {}
        absent_map = {}
        window_days = 0
        if pf and pt:
            window_days = frappe.utils.date_diff(pt, pf) + 1
        if pf and pt and emps:
            emp_names = tuple([e.name for e in emps])
            if att_leave_on:
                lrows = frappe.db.sql("""
                    SELECT employee, leave_type, from_date, to_date FROM `tabLeave Application`
                    WHERE docstatus < 2 AND (status='Approved' OR docstatus=1)
                      AND from_date <= %s AND to_date >= %s AND employee IN %s
                """, (pt, pf, emp_names), as_dict=True)
                for r in lrows:
                    if r.employee not in leave_map:
                        leave_map[r.employee] = (r.leave_type or "Leave") + " " + str(r.from_date) + " → " + str(r.to_date)
            if att_absent_on:
                arows = frappe.db.sql("""
                    SELECT employee, COUNT(*) n, MIN(attendance_date) d1, MAX(attendance_date) d2
                    FROM `tabAttendance` att
                    WHERE att.docstatus = 1 AND att.status = 'Absent'
                      AND att.attendance_date BETWEEN %s AND %s AND att.employee IN %s
                      AND NOT EXISTS (
                        SELECT 1 FROM `tabAttendance` pp
                        WHERE pp.employee = att.employee AND pp.attendance_date = att.attendance_date
                          AND pp.docstatus = 1 AND pp.status IN ('Present','Half Day','Work From Home')
                      )
                    GROUP BY att.employee
                """, (pf, pt, emp_names), as_dict=True)
                for r in arows:
                    absent_map[r.employee] = {"days": frappe.utils.cint(r.n), "from": str(r.d1), "to": str(r.d2)}
        out["att_checks"] = {"absent": att_absent_on, "leave": att_leave_on, "off": att_off_on}
        # ── PRESENCE OVER THE WINDOW'S OWN DAYS ────────────────────────────────
        #
        # This block asked `DATE(time) = today` three times over, whatever window
        # the plan covered. Altura backfills: master plans and actuals are raised
        # for PAST weeks, and against a window of 14-18 September the chips
        # reported who had scanned in THIS morning. Daniel was deciding whether a
        # day was payable against the wrong day's scan -- and against a scan that
        # had nothing to do with the work at all.
        #
        # The date asked about is the window's, always. `pres_to` is the last day
        # of the window that has actually happened, because a day in the future
        # has no scan to find and reporting "no record" for it is a finding that
        # is not one; `pres_from` is the window's own start. Where the window
        # contains today, pres_to IS today and nothing about the screen changes.
        #
        # THE MORNING-SCAN GATE IS DIFFERENT and stays as it is. "Has this crew
        # turned up today, and is it past the cutoff" is a question about today
        # by construction -- it exists to stop somebody assigning work to people
        # who never arrived this morning -- so it is the one rule here that is
        # explicitly about today, and `includes_today` already keeps it from
        # firing on a past window. See `scan_info.checked`.
        #
        # Night-shift workers are exempt from the gate (their arrival is in the
        # evening).
        scan_on = 1
        scan_cutoff = "09:00:00"
        try:
            scan_on = frappe.utils.cint(frappe.db.get_single_value("Work Management Settings", "att_require_scan"))
            scan_cutoff = str(frappe.db.get_single_value("Work Management Settings", "att_scan_cutoff") or "09:00:00")
        except Exception:
            pass
        # Time fields come back unpadded ("9:00:00") — normalise before string compare
        cparts = scan_cutoff.split(":")
        scan_cutoff = cparts[0].zfill(2) + ":" + (cparts[1].zfill(2) if len(cparts) > 1 else "00") + ":" + (cparts[2][:2].zfill(2) if len(cparts) > 2 else "00")
        today_str = str(frappe.utils.today())
        includes_today = presence.applies_today(pf, pt, today_str)
        # The days this window can be asked about: its own, up to today. A window
        # entirely in the future leaves pres_from empty and no read runs -- there
        # is nothing to have happened yet.
        pres_from, pres_to, pres_days = presence.evidence_window(pf, pt, today_str)
        scan_map = {}
        present_att = {}
        night_set = {}
        absent_today = {}
        seen_days = {}
        absent_days = {}
        # Presence over the window, when the project asks for it. Off by default:
        # a site without biometric hardware, or keeping attendance somewhere else,
        # gets "?" against every worker, which reads as a finding and is not. Off,
        # none of these reads run at all -- three queries and a shift-type scan
        # per load.
        asg_presence_on = frappe.utils.cint(
            frappe.db.get_single_value("Work Management Settings", "asg_show_today_presence"))
        out["show_today"] = asg_presence_on
        out["presence_window"] = {"from": pres_from, "to": pres_to, "days": pres_days,
            "is_today": 1 if (pres_to and pres_to == today_str) else 0,
            "past": 1 if (pres_to and pres_to < today_str) else 0}
        if emps and asg_presence_on and pres_from:
            emp_names2 = tuple([e.name for e in emps])
            # Two reads over the window's own days, and two things taken from
            # each: what happened on the REFERENCE day -- the last day of the
            # window that has happened, which is the day the chip names -- and
            # how many of the window's days there was evidence for at all, which
            # is the honest answer on a window of more than one day.
            seen_set = {}
            for r in frappe.db.sql("""
                SELECT employee, DATE(`time`) d, MIN(`time`) t FROM `tabEmployee Checkin`
                WHERE DATE(`time`) BETWEEN %s AND %s AND employee IN %s
                GROUP BY employee, DATE(`time`)
            """, (pres_from, pres_to, emp_names2), as_dict=True):
                seen_set.setdefault(r.employee, {})[str(r.d)] = 1
                if str(r.d) == pres_to:
                    scan_map[r.employee] = str(r.t)[11:16]
            for r in frappe.db.sql("""
                SELECT employee, attendance_date d FROM `tabAttendance`
                WHERE docstatus = 1 AND attendance_date BETWEEN %s AND %s
                  AND status IN ('Present','Half Day','Work From Home') AND employee IN %s
            """, (pres_from, pres_to, emp_names2), as_dict=True):
                seen_set.setdefault(r.employee, {})[str(r.d)] = 1
                if str(r.d) == pres_to:
                    present_att[r.employee] = 1
            for se in seen_set:
                seen_days[se] = len(seen_set[se])
            for r in frappe.db.sql("""
                SELECT employee, attendance_date d FROM `tabAttendance` att
                WHERE att.docstatus = 1 AND att.attendance_date BETWEEN %s AND %s
                  AND att.status = 'Absent' AND att.employee IN %s
                  AND NOT EXISTS (
                    SELECT 1 FROM `tabAttendance` pp
                    WHERE pp.employee = att.employee AND pp.attendance_date = att.attendance_date
                      AND pp.docstatus = 1 AND pp.status IN ('Present','Half Day','Work From Home')
                  )
            """, (pres_from, pres_to, emp_names2), as_dict=True):
                absent_days[r.employee] = frappe.utils.cint(absent_days.get(r.employee)) + 1
                if str(r.d) == pres_to:
                    absent_today[r.employee] = 1
            night_shifts = frappe.db.sql("SELECT name FROM `tabShift Type` WHERE TIME(end_time) < TIME(start_time)", as_dict=True)
            nset = set([r.name for r in night_shifts])
            for r in frappe.db.sql("""
                SELECT name, default_shift FROM `tabEmployee`
                WHERE name IN %s AND IFNULL(default_shift,'') != ''
            """, (emp_names2,), as_dict=True):
                if r.default_shift in nset:
                    night_set[r.name] = 1
        out["scan_info"] = {
            # `checked` is the MORNING-SCAN GATE, and it is the one rule here that
            # is explicitly about today: it asks whether this crew turned up this
            # morning, which is only a question at all when the window contains
            # this morning. On a past window it stays 0 and the gate does not
            # fire -- see the block comment above.
            "checked": 1 if includes_today else 0,
            "gate_on": scan_on,
            "cutoff": scan_cutoff,
            "cutoff_passed": 1 if str(frappe.utils.nowtime())[:8].zfill(8) >= scan_cutoff else 0,
            "present_count": 0,
            "total": len(emps),
            # what the presence figures are ABOUT, so the bar can say so rather
            # than printing "today" over a fortnight-old window.
            "from": pres_from,
            "to": pres_to,
            "days": pres_days,
            "is_today": 1 if (pres_to and pres_to == today_str) else 0,
        }
        for e in emps:
            oc = 0
            if e.holiday_list and pf and pt:
                oc = frappe.db.count("Holiday", {"parent": e.holiday_list, "holiday_date": ["between", [pf, pt]]})
            e["off_days"] = oc
            e["att_leave"] = leave_map.get(e.name)
            av = absent_map.get(e.name)
            e["att_absent_days"] = av["days"] if av else 0
            e["att_absent_span"] = (av["from"] + " → " + av["to"]) if av else None
            # off-day flag per the settings rule (Entire window / Any off day / Ignore)
            e["att_all_off"] = 0
            e["att_off_reason"] = None
            if att_off_on and window_days and oc > 0 and off_rule != "Ignore at assignment":
                if off_rule == "Any off day":
                    e["att_all_off"] = 1
                    e["att_off_reason"] = ("has " + str(oc) + " off day" + ("" if oc == 1 else "s") + " in this " + str(window_days) + "-day window")
                elif oc >= window_days:
                    e["att_all_off"] = 1
                    e["att_off_reason"] = ("off/holiday for the entire window (" + str(oc) + " of " + str(window_days) + " days)")
            e["is_night"] = 1 if night_set.get(e.name) else 0
            # WHAT HAPPENED ON THE DAY BEING ASKED ABOUT. `present_today` and
            # `absent_today` keep their names -- an older screen may still read
            # them -- but the day is the window's reference day, not the clock's.
            # On a window containing today the two are the same day and nothing
            # moves; on a past window they now answer for the work's own date,
            # which is the whole of finding #1.
            e["scan_in"] = scan_map.get(e.name)
            e["present_today"] = 1 if (scan_map.get(e.name) or present_att.get(e.name) or night_set.get(e.name)) else 0
            e["absent_today"] = 1 if absent_today.get(e.name) else 0
            # ...and over the window as a whole, which is the only honest figure
            # once it is more than a day long: "seen on 3 of the 5 days".
            e["present_days"] = frappe.utils.cint(seen_days.get(e.name))
            e["absent_days_window"] = frappe.utils.cint(absent_days.get(e.name))
            if e["present_today"] and not night_set.get(e.name):
                out["scan_info"]["present_count"] = out["scan_info"]["present_count"] + 1
            al = allocated.get(e.name)
            if al:
                e["allocated_elsewhere"] = 1
                e["allocated_asg"] = al["assignment"]
                e["allocated_task"] = al["task"]
                e["allocated_farm"] = al["farm"]
            else:
                e["allocated_elsewhere"] = 0
        out["employees"] = emps
        # WHETHER A BUSY WORKER MAY BE PICKED. The rows above are tagged
        # `allocated_elsewhere` and the screen makes those non-selectable, which is
        # right while a worker can only be on one task at a time -- and hides exactly
        # the people the split-day switch was turned on to allow. So the screen is
        # told, and decides.
        out["allow_split_day"] = 1 if ALLOW_SPLIT_DAY else 0

    elif action == "a_my_assignments":
        out["assignments"] = frappe.db.get_all("Work Management Assigner",
            filters={"assigned_by":frappe.session.user},
            fields=["name","planner_request","farm","task","block_section","planned_people","assigned_count",
                    "variance","workflow_state","assign_date"], order_by="creation desc", limit=200)

    elif action == "a_pending":
        # WHICH QUEUE, by the key the tab carries. `Pending HR Head` was both the
        # default and the name of a step this site may not have; the first enabled
        # approval step is the honest default, and on a chain of one it is the only
        # queue there is. A state is still accepted, because that is the other name
        # the server itself publishes for a step.
        pd_keys = chain.stage_keys(STAGE_ROWS, ASG_DT, enabled_only=True)
        pd_step, pd_bad = chain.resolve(STAGE_ROWS, ASG_DT,
            stage=frappe.form_dict.get("stage") or (pd_keys[0] if pd_keys else None))
        if pd_bad or not pd_step:
            out["error"] = pd_bad or "This chain has no approval step to list."
        else:
            fmflt = {"workflow_state": pd_step["state"]}
            # A FARM-SCOPED step shows a farm manager their own farms and nobody
            # else's. Read from the step's `scoped` flag, which is the thing that
            # survives a chain being reconfigured -- the state name is not.
            if pd_step.get("scoped"):
                fmbypass = ("System Manager" in MY_ROLES) or ("General Manager" in MY_ROLES)
                if not fmbypass:
                    fmflt["farm"] = ["in", ASG_FARMS] if ASG_FARMS else ["in", ["__none__"]]
            out["pending"] = frappe.db.get_all("Work Management Assigner",
                filters=fmflt,
                fields=["name","planner_request","farm","task","block_section","from_date","to_date","planned_people",
                        "assigned_count","variance","planned_cost","assigned_by","assign_date"],
                order_by="assign_date desc", limit=200)
            out["step"] = pd_step["key"]
            out["step_label"] = chain.label_of(pd_step)

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
        # Submitting crosses a workflow transition; saving a draft does not, and stays
        # open to whoever may enter the crew. The step's own configured role gates it
        # and System Manager bypasses -- may_take_step()'s rule, which every approve
        # action already applies.
        #
        # Nothing enforced this before. The write below moves the state with
        # db.set_value(), which no validator sees, under a comment saying it exists to
        # get around the workflow's own transition-role gate. That gate was the only
        # thing checking who this person was, so going around it left the step open to
        # anybody who could reach the endpoint. Refuse here, in words, instead.
        if not err and submit_now and not (STAGE_ROLE["assigner_submit"] in MY_ROLES
                                           or "System Manager" in MY_ROLES):
            err = ("Only " + str(STAGE_ROLE["assigner_submit"]) + " can submit an "
                   "assignment for approval. Save it as a draft, or ask somebody "
                   "holding that role to submit it.")
        # HARD CAP: active assigned workers may not exceed the plan's people_per_day
        planned = 0
        if planner:
            planned = frappe.utils.cint(frappe.db.get_value("Work Management Planner", planner, "people_per_day"))
        if not err and planned > 0 and len(emp_list) > planned:
            # HEAD COUNT vs PERSON-DAYS. The plan budgets people per day, and this
            # counts heads against it -- which is exact while a worker gives a whole
            # day to one task.
            #
            # Once a day can be split it stops being exact, and it cannot be made
            # exact here: how the day divides is recorded in ACTUALS, hours by hours,
            # long after this screen has been left. Twenty half-day workers are ten
            # person-days and should fit a plan for ten, but nothing on this screen
            # knows they will be half days.
            #
            # So with splitting on this says so and lets it through, and the real
            # person-days comparison happens where the hours exist -- see
            # work_management/split_day.py and the man-day figures it feeds. A guard
            # enforcing a rule it cannot actually check is the trap this codebase
            # has already had to undo once.
            over_by = len(emp_list) - planned
            if ALLOW_SPLIT_DAY:
                out["crew_warning"] = ("Plan allows " + str(planned) + " per day and you selected " +
                    str(len(emp_list)) + ". Allowed because a day may be split -- but only the "
                    "hours recorded on the actuals screen will say whether " + str(len(emp_list)) +
                    " workers really cost " + str(planned) + " person-days.")
            else:
                err = ("Too many workers: plan allows " + str(planned) + " per day, you selected " +
                    str(len(emp_list)) + ". Remove " + str(over_by) + ", or turn on 'Allow a "
                    "worker's day to be split between tasks' in Work Management Settings.")
        # DOUBLE-ALLOCATION GUARD (server enforcement): reject workers already on an overlapping live assignment
        if not err and planner and emp_list:
            p_dates = frappe.db.get_value("Work Management Planner", planner, ["from_date","to_date"], as_dict=True)
            if p_dates and p_dates.from_date and p_dates.to_date:
                clash = frappe.db.sql("""
                    SELECT DISTINCT we.employee emp
                    FROM `tabWork Assignment Employee` we
                    INNER JOIN `tabWork Management Assigner` a ON we.parent = a.name
                    WHERE a.workflow_state IN (""" + sql_in(ST_ASG_ACTIVE) + """)
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
                    clash_who = ", ".join(names[:8]) + (" and more" if len(names) > 8 else "")
                    if ALLOW_SPLIT_DAY:
                        # Allowed, and still said. A worker on two assignments is
                        # usually a mistake; a split day is deliberate, and only the
                        # person doing it can tell the two apart. The hours typed on
                        # each actuals row are what keep the day counting once.
                        out["split_warning"] = ("Already assigned elsewhere over these dates: " +
                            clash_who + ". Their day will be split, so record the hours each "
                            "task took on the actuals screen.")
                        out["split_workers"] = names
                    else:
                        err = ("These workers are already assigned elsewhere for an overlapping period: " +
                            clash_who + ". Remove them to avoid double-allocation, or turn on "
                            "'Allow a worker's day to be split between tasks' in Work Management Settings.")
        # ── TIME & ATTENDANCE GATE (server enforcement; toggles in Work Management
        # Settings): a worker on approved leave, marked Absent inside the window, or
        # off for the WHOLE window needs an explicit, logged override. ──
        att_conflicts = []
        att_override = frappe.form_dict.get("att_override")
        if not err and planner and emp_list:
            gate_absent = 1
            gate_leave = 1
            gate_off = 1
            gate_off_rule = "Entire window"
            try:
                gate_absent = frappe.utils.cint(frappe.db.get_single_value("Work Management Settings", "att_block_absent"))
                gate_leave = frappe.utils.cint(frappe.db.get_single_value("Work Management Settings", "att_block_leave"))
                gate_off = frappe.utils.cint(frappe.db.get_single_value("Work Management Settings", "att_block_off"))
                gate_off_rule = str(frappe.db.get_single_value("Work Management Settings", "att_off_window_rule") or "Entire window")
            except Exception:
                pass
            if gate_off_rule == "Ignore at assignment":
                gate_off = 0
            g_dates = frappe.db.get_value("Work Management Planner", planner, ["from_date", "to_date"], as_dict=True)
            if (gate_absent or gate_leave or gate_off) and g_dates and g_dates.from_date and g_dates.to_date:
                gpf = str(g_dates.from_date)
                gpt = str(g_dates.to_date)
                gdays = frappe.utils.date_diff(gpt, gpf) + 1
                reasons_map = {}
                if gate_leave:
                    lrows = frappe.db.sql("""
                        SELECT employee, leave_type, from_date, to_date FROM `tabLeave Application`
                        WHERE docstatus < 2 AND (status='Approved' OR docstatus=1)
                          AND from_date <= %s AND to_date >= %s AND employee IN %s
                    """, (gpt, gpf, tuple(emp_list)), as_dict=True)
                    for r in lrows:
                        reasons_map.setdefault(r.employee, []).append(
                            "on " + (r.leave_type or "leave") + " " + str(r.from_date) + " → " + str(r.to_date))
                if gate_absent:
                    arows = frappe.db.sql("""
                        SELECT employee, COUNT(*) n, MIN(attendance_date) d1, MAX(attendance_date) d2
                        FROM `tabAttendance`
                        WHERE docstatus = 1 AND status = 'Absent'
                          AND attendance_date BETWEEN %s AND %s AND employee IN %s
                          AND NOT EXISTS (
                            SELECT 1 FROM `tabAttendance` pp
                            WHERE pp.employee = `tabAttendance`.employee
                              AND pp.attendance_date = `tabAttendance`.attendance_date
                              AND pp.docstatus = 1 AND pp.status IN ('Present','Half Day','Work From Home')
                          )
                        GROUP BY employee
                    """, (gpf, gpt, tuple(emp_list)), as_dict=True)
                    for r in arows:
                        span = str(r.d1) if str(r.d1) == str(r.d2) else str(r.d1) + " → " + str(r.d2)
                        reasons_map.setdefault(r.employee, []).append(
                            "marked Absent " + str(frappe.utils.cint(r.n)) + " day" + ("" if frappe.utils.cint(r.n) == 1 else "s") + " in this window (" + span + ")")
                if gate_off:
                    hl_rows = frappe.db.sql("""
                        SELECT name, holiday_list FROM `tabEmployee`
                        WHERE name IN %s AND IFNULL(holiday_list,'') != ''
                    """, (tuple(emp_list),), as_dict=True)
                    for hr in hl_rows:
                        oc = frappe.db.count("Holiday", {"parent": hr.holiday_list, "holiday_date": ["between", [gpf, gpt]]})
                        if oc >= gdays:
                            reasons_map.setdefault(hr.name, []).append("off/holiday for the entire window")
                # MORNING PRESENCE gate: window includes today + cutoff passed ->
                # a day worker with no scan and no Present attendance today is
                # flagged "not seen on site". Night-shift workers are exempt.
                #
                # THE ONE RULE HERE THAT IS ABOUT TODAY, deliberately: it asks
                # whether this crew turned up this morning, which a window that
                # finished last week cannot be asked. presence.applies_today()
                # is that condition, said once -- the three checks above are
                # about the window's own days and always were.
                gate_scan = 1
                scan_cut = "09:00:00"
                try:
                    gate_scan = frappe.utils.cint(frappe.db.get_single_value("Work Management Settings", "att_require_scan"))
                    scan_cut = str(frappe.db.get_single_value("Work Management Settings", "att_scan_cutoff") or "09:00:00")
                except Exception:
                    pass
                cqarts = scan_cut.split(":")
                scan_cut = cqarts[0].zfill(2) + ":" + (cqarts[1].zfill(2) if len(cqarts) > 1 else "00") + ":" + (cqarts[2][:2].zfill(2) if len(cqarts) > 2 else "00")
                g_today = str(frappe.utils.today())
                if gate_scan and presence.applies_today(gpf, gpt, g_today) \
                        and str(frappe.utils.nowtime())[:8].zfill(8) >= scan_cut:
                    seen_today = {}
                    for r in frappe.db.sql("""
                        SELECT employee, MIN(`time`) t FROM `tabEmployee Checkin`
                        WHERE DATE(`time`) = %s AND employee IN %s GROUP BY employee
                    """, (g_today, tuple(emp_list)), as_dict=True):
                        seen_today[r.employee] = str(r.t)[11:16]
                    for r in frappe.db.sql("""
                        SELECT employee FROM `tabAttendance`
                        WHERE docstatus = 1 AND attendance_date = %s
                          AND status IN ('Present','Half Day','Work From Home') AND employee IN %s
                    """, (g_today, tuple(emp_list)), as_dict=True):
                        seen_today.setdefault(r.employee, "manual")
                    night_shifts2 = frappe.db.sql("SELECT name FROM `tabShift Type` WHERE TIME(end_time) < TIME(start_time)", as_dict=True)
                    nset2 = set([r.name for r in night_shifts2])
                    night_emp2 = {}
                    for r in frappe.db.sql("""
                        SELECT name, default_shift FROM `tabEmployee`
                        WHERE name IN %s AND IFNULL(default_shift,'') != ''
                    """, (tuple(emp_list),), as_dict=True):
                        if r.default_shift in nset2:
                            night_emp2[r.name] = 1
                    for ce in emp_list:
                        if not seen_today.get(ce) and not night_emp2.get(ce):
                            reasons_map.setdefault(ce, []).append("no scan or Present attendance today (not seen on site by " + str(frappe.utils.nowtime())[:5] + ")")
                for ce in emp_list:
                    if reasons_map.get(ce):
                        cnm = frappe.db.get_value("Employee", ce, "employee_name") or ce
                        att_conflicts.append({"employee": ce, "name": cnm, "reasons": reasons_map[ce]})
        if err:
            out["error"] = err
        elif att_conflicts and not att_override:
            out["needs_att_override"] = 1
            out["att_conflicts"] = att_conflicts
        else:
            editing = 0
            editing_pending = 0  # approver editing a doc mid-approval (keep its state)
            if asg_name and frappe.db.exists("Work Management Assigner", asg_name):
                state = frappe.db.get_value("Work Management Assigner", asg_name, "workflow_state")
                if state in ("Draft", "Rejected"):
                    d = frappe.get_doc("Work Management Assigner", asg_name)
                    d.set("employees", [])
                    editing = 1
                elif state in ST_ASG_WAITING:
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
                # written directly rather than through save(): the workflow's own
                # transition-role gate would refuse the enterer here, and it is the
                # wrong place to refuse from -- it names neither the role required nor
                # theirs. Who may take this step is checked above, before anything was
                # written, against STAGE_ROLE["assigner_submit"].
                frappe.db.set_value("Work Management Assigner", d.name, "workflow_state", STAGE_NEXT["assigner_submit"], update_modified=False)
                d.workflow_state = STAGE_NEXT["assigner_submit"]
            # audit trail: an attendance override is always logged on the document
            if att_conflicts and att_override:
                ov_lines = []
                for c in att_conflicts:
                    ov_lines.append(c["name"] + " (" + c["employee"] + "): " + "; ".join(c["reasons"]))
                d.add_comment("Comment", "Attendance override by " + frappe.session.user + " — assigned despite: " + " | ".join(ov_lines))
                out["att_overridden"] = len(att_conflicts)
            out["name"] = d.name; out["workflow_state"] = d.workflow_state
            out["assigned_count"] = d.assigned_count; out["variance"] = d.variance
            out["editing"] = editing; out["editing_pending"] = editing_pending

    elif action in ("a_approve", "a_fm_approve", "a_hr_approve", "a_gm_approve"):
        # ONE APPROVAL, WHICHEVER STEP IT IS. There were three branches here, one
        # per step of the chain as it shipped, and between them they knew the whole
        # of the old vocabulary: which state each step waits in, which role takes
        # it, which of them submits the document. A site that renames its steps,
        # hands them to its own roles and switches two off still runs those three
        # branches -- and a site that ADDS a step has no branch for it at all.
        #
        # So the step is resolved from the configured chain, by the key the screen
        # was handed with its tab, and everything that used to be per-branch is read
        # off the step: `on`, `state`, `role`, `scoped`, `next_state`. What the last
        # step does -- submit the document and stamp the final approver -- is now
        # "the step whose next_state is the terminal", which is what made it the
        # last step in the first place.
        #
        # The three old action names remain, as the keys they always meant. They are
        # what bulk re-enters, what the mirror's tests read, and what anything
        # holding a bookmark still sends.
        ap_alias = {"a_fm_approve": "assigner_farm_manager",
                    "a_hr_approve": "assigner_hr_head",
                    "a_gm_approve": "assigner_gm"}
        nm = frappe.form_dict.get("name")
        ap_stage = ap_alias.get(action) or frappe.form_dict.get("stage")
        cur = frappe.db.get_value(ASG_DT, nm, ["workflow_state", "farm"], as_dict=True)
        ap_step, ap_bad = chain.resolve(STAGE_ROWS, ASG_DT, stage=ap_stage,
                                        state=cur.workflow_state if cur else None)
        ap_why = None
        if ap_step:
            # Two dimensions gate a step and only one applies to each; which one is
            # the step's own `scoped` flag, not something inferred from its name.
            ap_why = chain.may_take(ap_step, MY_ROLES, farm=cur.farm if cur else None,
                                    farms=ASG_FARMS)
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
            frappe.db.set_value(ASG_DT, nm, "workflow_state", ap_next, update_modified=False)
            ap_by, ap_on = ASG_STAMP.get(ap_step["key"], (None, None))
            if ap_by:
                try:
                    frappe.db.set_value(ASG_DT, nm, ap_by, frappe.session.user, update_modified=False)
                    frappe.db.set_value(ASG_DT, nm, ap_on, frappe.utils.today(), update_modified=False)
                except Exception:
                    pass
            if ap_next == ASG_TERMINAL:
                # The last approval, and the only one that submits the document.
                # Which step that is comes from the chain, so switching the GM step
                # off hands the job to whichever step is last instead of leaving
                # every assignment unsubmitted.
                frappe.db.set_value(ASG_DT, nm, "docstatus", 1, update_modified=False)
                for kid in frappe.db.get_all("Work Assignment Employee",
                        filters={"parent": nm}, pluck="name"):
                    frappe.db.set_value("Work Assignment Employee", kid, "docstatus", 1,
                                        update_modified=False)
                frappe.db.set_value(ASG_DT, nm, "approved_by", frappe.session.user, update_modified=False)
                frappe.db.set_value(ASG_DT, nm, "approval_date", frappe.utils.today(), update_modified=False)
            elif not ap_by:
                # An added step has no column of its own, so who took it is recorded
                # where the document already keeps its history -- the planner does
                # exactly this, and for the same reason.
                frappe.get_doc(ASG_DT, nm).add_comment(
                    "Comment", str(chain.label_of(ap_step)) + " taken by " +
                    frappe.session.user + " — now " + str(ap_next))
            out["name"] = nm
            out["workflow_state"] = ap_next
            out["step"] = ap_step["key"]
            out["step_label"] = chain.label_of(ap_step)

    elif action in ("a_approve_bulk", "a_reject_bulk"):
        # SEVERAL AT A TIME, one at a time. Every document goes through the very
        # branch its own button uses -- same role gate, same stage check, same
        # writes -- because this re-enters this dispatcher rather than restating
        # any of it. See work_management/bulk.py.
        #
        # `stage` picks WHICH approval, and the screen only ever sends the stage
        # whose queue is on screen: this tab shows one stage at a time, and
        # approving across stages in one press would mean approving work the user
        # is not looking at.
        #
        # It is a stage KEY, validated against the chain this site runs. It used to
        # be one of `fm`, `gm`, `hr` -- three abbreviations of the shipped chain,
        # which the screen derived by splitting `a_fm_approve` on an underscore.
        # Handed a configured action instead, that produced `undefined`, and the
        # refusal it earned named three steps Altura does not have.
        bk_names = frappe.form_dict.get("names")
        try:
            bk_names = json.loads(bk_names or "[]")
        except Exception:
            bk_names = []
        bk_reject = action == "a_reject_bulk"
        bk_stage = str(frappe.form_dict.get("stage") or "").strip()
        bk_reason = frappe.form_dict.get("reason")
        bk_bad = bulk.check_selection(bk_names, bk_reason, needs_reason=bk_reject)
        bk_step = None
        if not bk_bad and not bk_reject:
            bk_step, bk_bad = chain.resolve(STAGE_ROWS, ASG_DT, stage=bk_stage)
            if not bk_bad and not bk_step:
                bk_bad = chain.unknown_stage(bk_stage, STAGE_ROWS, ASG_DT)
        if bk_bad:
            out["error"] = bk_bad
        else:
            bk_ok, bk_failed = bulk.run_bulk(
                wm_assigner, "a_reject" if bk_reject else "a_approve", bk_names,
                base={"reason": bk_reason} if bk_reject
                     else {"stage": bk_step["key"]})
            out["ok"] = bk_ok
            out["failed"] = bk_failed
            out["summary"] = bulk.summarise(bk_ok, bk_failed,
                "rejected" if bk_reject else "approved")

    elif action == "a_reject":
        nm = frappe.form_dict.get("name")
        cur_ws = frappe.db.get_value("Work Management Assigner", nm, "workflow_state")
        # Rejectable at every approval step this chain holds, switched-off ones
        # included: rejecting is not a step and is how a document parked in a
        # retired step gets out of it. Named three states, which on a reconfigured
        # chain is either too few or entirely wrong.
        rj_step = chain.at_state(STAGE_ROWS, ASG_DT, cur_ws)
        if not rj_step:
            out["error"] = "Not awaiting approval (state: " + str(cur_ws) + ")"
        else:
            frappe.db.set_value("Work Management Assigner", nm, "workflow_state", "Rejected", update_modified=False)
            frappe.db.set_value("Work Management Assigner", nm, "approved_by", None, update_modified=False)
            frappe.db.set_value("Work Management Assigner", nm, "approval_date", None, update_modified=False)
            # WHY, on the document's own history. Optional here so nothing that
            # calls this today changes; required when rejecting in bulk, where it
            # is the only thing telling one refusal from twenty.
            rj_why = str(frappe.form_dict.get("reason") or "").strip()
            if rj_why:
                frappe.get_doc("Work Management Assigner", nm).add_comment(
                    "Comment", "Rejected by " + frappe.session.user + ": " + rj_why)
            out["name"] = nm; out["workflow_state"] = "Rejected"
            out["reason"] = rj_why or None

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
            STAGE_ROWS, 'Work Management Assigner', rl, farms=ASG_FARMS) else 0
        out["approver_label"] = chain.approver_suffix(
            STAGE_ROWS, ['Work Management Assigner'], rl, farms=ASG_FARMS)
        # MAY THEY CHANGE THE CREW -- the one answer a_add_crew and a_release
        # actually gate on. The crew screen decided it itself, by OR-ing the
        # three role flags above, so the release panel was hidden from the very
        # person the server would have allowed.
        out["may_change_crew"] = 1 if chain.takeable(
            STAGE_ROWS, ASG_DT, rl, farms=ASG_FARMS) else 0
        # Closing a plan is decided by the step that ends the ACTUALS chain --
        # wm_actuals owns the action, and this screen only needs to know which
        # of the two close verbs to offer. Same resolution, read from the same
        # chain rows, so the two screens cannot disagree.
        ar_act_final = None
        for ar_step in chain.approval_steps(STAGE_ROWS, "Work Management Actuals", enabled_only=True):
            if ar_step.get("next_state") == STAGE_STATES.get(
                    "Work Management Actuals", {}).get("terminal"):
                ar_act_final = ar_step
        ar_act_farms = []
        for _ar_farm, _ar_role in (FARM_APPROVER_ROLE or {}).items():
            if _ar_role in rl and _ar_farm not in ar_act_farms:
                ar_act_farms.append(_ar_farm)
        out["may_close_plans"] = 1 if (ar_act_final and chain.may_take(
            ar_act_final, rl, farms=ar_act_farms) is None) else 0
        out["decider_label"] = chain.label_of(ar_act_final, "the approver")
        out["stages"] = stage_pills.for_document_type(
            "Work Management Assigner", STAGE_ROWS, FARM_APPROVER_ROLE, rl)

    # ===== ACTUALS (act_) =====
    elif action == "a_detail":
        nm = frappe.form_dict.get("assignment")
        a = frappe.db.get_value("Work Management Assigner", nm,
            ["name","planner_request","farm","block_section","task","task_kpi","from_date","to_date",
             "planned_people","planned_cost","assigned_count","variance","workflow_state"], as_dict=True)
        if a:
            a["editable"] = 1 if a.workflow_state in ST_ASG_OPEN else 0
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
        # workers busy elsewhere on an overlapping live assignment, WITH what they
        # are busy on -- the picker names the other task rather than just refusing
        busy_map = {}
        if adates and adates.from_date and adates.to_date:
            busyrows = frappe.db.sql("""
                SELECT we.employee emp, a.name asg, a.task task, a.farm farm
                FROM `tabWork Assignment Employee` we
                INNER JOIN `tabWork Management Assigner` a ON we.parent = a.name
                WHERE a.workflow_state IN (""" + sql_in(ST_ASG_ACTIVE) + """)
                  AND a.name != %s
                  AND IFNULL(we.status,'Active') = 'Active'
                  AND a.from_date <= %s AND a.to_date >= %s
            """, (nm, adates.to_date, adates.from_date), as_dict=True)
            for r in busyrows:
                if r.emp and r.emp not in busy_map:
                    busy_map[r.emp] = {"assignment": r.asg, "task": r.task, "farm": r.farm}
        # TWO POOLS, because the two verbs on this screen have two different write
        # paths and a picker that disagrees with its own server is the bug this is
        # fixing. `candidates` feeds SWAP, whose a_substitute refuses a replacement
        # who is busy elsewhere whatever the split-day flag says -- so offering one
        # would offer something the server then refuses. `add_candidates` feeds ADD,
        # whose a_add_crew allows a busy worker when the flag is on and merely warns
        # -- so hiding them there hides exactly the people the switch permits.
        cands = []
        add_cands = []
        for emp in frappe.db.sql("""
                SELECT e.name, e.employee_name FROM `tabEmployee` e
                WHERE e.status = 'Active' AND e.custom_farm = %(f)s AND """ + TW_MATCH + """
                ORDER BY e.employee_name LIMIT 1000
            """, {"f": farm}, as_dict=True):
            if already_map.get(emp.name):
                # already on THIS roster -- refused by both verbs, whatever the flag.
                # Adding somebody twice is a mistake rather than a split day, and
                # a_add_crew says so in as many words.
                continue
            busy = busy_map.get(emp.name)
            if not busy:
                cands.append(emp)
                add_cands.append(emp)
                continue
            if ALLOW_SPLIT_DAY:
                tagged = dict(emp)
                tagged["allocated_elsewhere"] = 1
                tagged["allocated_asg"] = busy["assignment"]
                tagged["allocated_task"] = busy["task"]
                tagged["allocated_farm"] = busy["farm"]
                add_cands.append(tagged)
        out["candidates"] = cands
        out["add_candidates"] = add_cands
        # The screen no longer has to remember a flag it read during some earlier
        # flow: this payload carries it. The Manage crew dialog never calls
        # a_employees, so it was reading whatever `allow_split_day` a previous
        # assign had left in page state -- undefined on a fresh load, which meant
        # the split-day switch did nothing here at all.
        out["allow_split_day"] = 1 if ALLOW_SPLIT_DAY else 0

    elif action == "a_add_crew":
        # The third verb the crew never had. Swap needs somebody to take the
        # leaver's place; release says they have gone. Neither says "this person
        # worked and is not on the list", which is what a clerk finds while typing
        # the day's quantities -- and the actuals grid offers only the assignment's
        # own roster, so there was no way to record it at all.
        #
        # Mechanically this is the second half of a_substitute with the first half
        # removed: the same eligibility checks, the same child-row insert into a
        # submitted parent, the same recount afterwards.
        nm = frappe.form_dict.get("assignment")
        add_raw = frappe.form_dict.get("employees") or frappe.form_dict.get("employee") or ""
        add_from = frappe.form_dict.get("start_date")
        add_who = []
        for aw in str(add_raw).split(","):
            if aw.strip() and aw.strip() not in add_who:
                add_who.append(aw.strip())
        err = None
        if not nm or not add_who:
            err = "The assignment and at least one worker are required"
        elif not ASG_MAY_CHANGE_CREW:
            # the screens disable the control for everybody else; this is the same
            # rule where it counts. Release's gate lived only in the browser until
            # today, which is not a gate.
            err = "Only " + str(ASG_APPROVERS) + " may add a worker to approved work."
        d = None
        if not err:
            d = frappe.get_doc("Work Management Assigner", nm)
            if d.workflow_state != "Assigned":
                err = "Workers can only be added to an approved (Assigned) assignment"
            elif not add_from:
                add_from = d.from_date
            if not err and str(add_from) > str(d.to_date):
                err = ("They cannot start on " + str(add_from) + " -- this assignment ends " +
                    str(d.to_date) + ".")
        if not err:
            # already here? a mistake rather than a decision, so it is refused
            on_roster = {}
            for r in d.employees:
                on_roster[r.employee] = (r.status or "Active")
            dup = []
            for aw in add_who:
                if aw in on_roster:
                    dup.append(aw + " (" + on_roster[aw] + ")")
            if dup:
                err = ("Already on this assignment: " + ", ".join(dup[:6]) +
                    ". Use swap to replace somebody, or release and add them again to "
                    "restart their tally.")
        if not err:
            # a task worker under the CURRENT settings, or their work could never be
            # paid through this system and recording it would be recording something
            # nobody will settle
            not_tw = []
            for aw in add_who:
                ok = frappe.db.sql("""
                    SELECT e.name FROM `tabEmployee` e WHERE e.name = %(n)s AND """ + TW_MATCH + """
                    LIMIT 1
                """, {"n": aw}, as_dict=True)
                if not ok:
                    not_tw.append(frappe.db.get_value("Employee", aw, "employee_name") or aw)
            if not_tw:
                err = ("Not task workers under the current Work Management Settings, so "
                    "their work could never be paid through this system: " +
                    ", ".join(not_tw[:6]) + ".")
        if err:
            out["error"] = err
        else:
            # BUSY ELSEWHERE. Refused, or reported, exactly as the assign screen does
            # -- the switch is the one place that decides whether a shared day is a
            # fault or a plan.
            busy = frappe.db.sql("""
                SELECT DISTINCT we.employee emp, a.name asg
                FROM `tabWork Assignment Employee` we
                INNER JOIN `tabWork Management Assigner` a ON we.parent = a.name
                WHERE a.workflow_state IN (""" + sql_in(ST_ASG_ACTIVE) + """)
                  AND a.name != %s
                  AND IFNULL(we.status,'Active') = 'Active'
                  AND a.from_date <= %s AND a.to_date >= %s
                  AND we.employee IN %s
            """, (nm, d.to_date, add_from, tuple(add_who)), as_dict=True)
            busy_names = []
            for b in busy:
                busy_names.append((frappe.db.get_value("Employee", b.emp, "employee_name") or b.emp)
                    + " (" + str(b.asg) + ")")
            if busy and not ALLOW_SPLIT_DAY:
                out["error"] = ("Already assigned elsewhere over these dates: " +
                    ", ".join(busy_names[:6]) + ". Release them there first, or turn on "
                    "'Allow a worker's day to be split between tasks' in Work Management Settings.")
            else:
                if busy:
                    out["split_warning"] = ("Also assigned elsewhere over these dates: " +
                        ", ".join(busy_names[:6]) + ". Their day will be split, so record the "
                        "hours each task took on the actuals screen.")
                maxidx = frappe.db.sql("""
                    SELECT COALESCE(MAX(idx),0) m FROM `tabWork Assignment Employee` WHERE parent=%s
                """, (nm,), as_dict=True)
                next_idx = (maxidx[0].m if maxidx else 0) + 1
                added = []
                for aw in add_who:
                    # the parent is submitted, so the row is inserted directly -- the
                    # route a_substitute takes, and it needs no re-approval
                    child = frappe.new_doc("Work Assignment Employee")
                    child.parent = nm
                    child.parenttype = "Work Management Assigner"
                    child.parentfield = "employees"
                    child.idx = next_idx
                    child.employee = aw
                    child.employee_name = frappe.db.get_value("Employee", aw, "employee_name")
                    child.employment_type = frappe.db.get_value("Employee", aw, "employment_type")
                    child.status = "Active"
                    child.start_date = add_from
                    child.count_in_payroll = 1
                    child.db_insert()
                    added.append(aw)
                    next_idx = next_idx + 1
                active_rows = frappe.db.sql("""
                    SELECT COUNT(*) c FROM `tabWork Assignment Employee`
                    WHERE parent=%s AND (status IS NULL OR status='Active')
                """, (nm,), as_dict=True)
                active = active_rows[0].c if active_rows else 0
                planned = frappe.utils.cint(d.planned_people)
                frappe.db.set_value("Work Management Assigner", nm, "assigned_count", active,
                    update_modified=False)
                frappe.db.set_value("Work Management Assigner", nm, "variance",
                    active - planned, update_modified=False)
                # THE HEAD COUNT WARNS, IT DOES NOT REFUSE.
                #
                # people_per_day reads like a limit and is not a spending control.
                # The spending control is the plan's quantity, and this screen's
                # sibling refuses to pass it -- "Exceeds plan target". Pay is
                # quantity x rate, so total pay is capped however many people share
                # the work: another body means the same budgeted work divided
                # further, not more money.
                #
                # And 1,316 of 1,497 approved assignments sit exactly at their
                # people_per_day, so refusing here would block this on 88% of them
                # while protecting nothing.
                if planned > 0 and active > planned:
                    out["cap_warning"] = ("This assignment now has " + str(active) +
                        " active workers and the plan budgeted " + str(planned) +
                        " per day. Allowed -- the plan's quantity still caps what can be "
                        "recorded and paid -- but the crew is over its planned size.")
                frappe.db.commit()
                out["name"] = nm
                out["added"] = added
                out["added_count"] = len(added)
                out["start_date"] = str(add_from)
                out["active_count"] = active
                out["variance"] = active - planned
                out["planned_people"] = planned
                out["message"] = (str(len(added)) + " added from " + str(add_from) + ". " +
                    str(active) + " active now (plan budgeted " + str(planned) + ").")

    elif action == "a_release":
        # Release workers from the crew. No replacement, which is the whole point.
        #
        # The crew screen has offered this for a while -- checkboxes, a date, an
        # FM/HR/GM gate -- and there was no such action here, so ticking somebody and
        # confirming answered `unknown action: a_release`. This is that action, and
        # its arguments are the ones the screen has always sent.
        #
        # Two ways to release existed and neither fits. a_substitute releases somebody
        # only by naming who takes their place; closing the plan releases the entire
        # crew. Neither says "these have moved on, nobody is replacing them".
        #
        # Nothing recorded is touched. Their actuals rows, quantities and pay stay
        # exactly as they are, and every busy/overlap check already reads a 'Left'
        # row as free, so they can go onto another task at once -- the same day too,
        # where a split day is allowed. Closing a plan has always done precisely this
        # to the whole crew, which is why this is a small change.
        nm = frappe.form_dict.get("assignment")
        rel_raw = frappe.form_dict.get("employees") or frappe.form_dict.get("employee") or ""
        rel_day = (frappe.form_dict.get("release_date") or frappe.form_dict.get("left_date")
            or frappe.utils.today())
        rel_who = []
        for rw in str(rel_raw).split(","):
            if rw.strip():
                rel_who.append(rw.strip())
        err = None
        if not nm or not rel_who:
            err = "The assignment and at least one worker are required"
        elif not ASG_MAY_CHANGE_CREW:
            # the screen hides the controls from everybody else; this is the same rule
            # enforced where it counts
            err = "Only " + str(ASG_APPROVERS) + " may release a worker."
        d = None
        if not err:
            d = frappe.get_doc("Work Management Assigner", nm)
            if d.workflow_state != "Assigned":
                err = "Workers can only be released from an approved (Assigned) assignment"
        if err:
            out["error"] = err
        else:
            rel_rows = {}
            for r in d.employees:
                if r.employee in rel_who and (r.status or "Active") == "Active":
                    rel_rows[r.employee] = r.name
            rel_missing = []
            for rw in rel_who:
                if rw not in rel_rows:
                    rel_missing.append(rw)
            if not rel_rows:
                out["error"] = ("None of those workers is active on this assignment -- "
                    "they may already have been released.")
            else:
                # the parent is submitted, so child rows and parent counts are written
                # directly, which is the route a_substitute takes and needs no
                # re-approval
                for rw in rel_rows:
                    frappe.db.set_value("Work Assignment Employee", rel_rows[rw], "status",
                        "Left", update_modified=False)
                    frappe.db.set_value("Work Assignment Employee", rel_rows[rw], "left_date",
                        rel_day, update_modified=False)
                # assigned_count counts ACTIVE rows, so releasing without a replacement
                # moves it -- unlike a substitution, where one leaves as one joins
                active_rows = frappe.db.sql("""
                    SELECT COUNT(*) c FROM `tabWork Assignment Employee`
                    WHERE parent=%s AND (status IS NULL OR status='Active')
                """, (nm,), as_dict=True)
                active = active_rows[0].c if active_rows else 0
                planned = frappe.utils.cint(d.planned_people)
                frappe.db.set_value("Work Management Assigner", nm, "assigned_count", active,
                    update_modified=False)
                frappe.db.set_value("Work Management Assigner", nm, "variance",
                    active - planned, update_modified=False)
                # what they already did here, so the screen can say the work was kept
                # rather than leaving somebody to wonder whether releasing lost it
                kept = frappe.db.sql("""
                    SELECT COUNT(*) n, COALESCE(SUM(we.amount),0) c
                    FROM `tabWork Actuals Employee` we
                    INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
                    WHERE ac.assignment = %s AND we.employee IN %s
                """, (nm, tuple(rel_rows.keys())), as_dict=True)
                frappe.db.commit()
                out["name"] = nm
                out["released_count"] = len(rel_rows)
                out["released"] = list(rel_rows.keys())
                out["not_active"] = rel_missing
                out["release_date"] = str(rel_day)
                out["active_count"] = active
                out["variance"] = active - planned
                out["kept_rows"] = frappe.utils.cint(kept[0].n) if kept else 0
                out["kept_amount"] = frappe.utils.flt(kept[0].c, 2) if kept else 0
                out["message"] = (str(len(rel_rows)) + " released on " + str(rel_day) + ". " +
                    str(out["kept_rows"]) + " day-row(s) already recorded here are kept, worth KES " +
                    frappe.utils.fmt_money(out["kept_amount"]) +
                    ". They are free for another task now.")

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
