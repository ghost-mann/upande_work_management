# Assign the Day Before — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Late assignments (saved after 18:00 the day before the start) need a reason. Add a 16:00 "no crew yet for tomorrow" email, plus Late-assigning and People tabs on the team leader dashboard card.

**Architecture:** The rules live in a new app module `work_management/assign_ahead.py`. It holds pure functions plus thin DB wrappers. The ported screens (mirror `server_scripts/wm_assigner.py`, `wm_dashboard.py` → app `api/`) reach it with `frappe.call("work_management.assign_ahead.<fn>", ...)`, the same way `missing_work.open_check` is called today. The reminder is a cron hook in `hooks.py`.

**Tech Stack:** Frappe v16 app, Python, plain JS screens. Tests are the site-less unittest suite.

**Spec:** `docs/superpowers/specs/2026-11-26-assign-day-before-design.md`

## Global Constraints
- Edit the mirror (`~/vscodeProjects/kaitet-work-management`), then `python3 port_app.py`. Never hand-edit `api/*.py`. Screen JS in the app's `public/js` must be byte-identical to the mirror's `web_pages/*.js` (copy after editing).
- Mirror code must compile in the Server Script sandbox, so no names starting with `_`.
- Settings: `assign_day_before` (Check, 0), `assign_cutoff_time` (Time, `18:00:00`), `assign_reminder` (Check, 0), `assign_reminder_notify` (Small Text). The reminder cron is fixed at `0 16 * * *`. A Time field for it would be unused because cron is static. *(builder's call: drop `assign_reminder_time`)*
- Reasons, exact copy: `Replacing absent worker`, `Weather`, `Urgent work`, `Other`. Auto reason: `Plan approved late`.
- Sender is `Kaitet Work Management <notifications@karenroses.com>` (same as missing_work).
- Commits are authored as ghost-mann, with no Claude co-author line.
- Run tests with `PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest discover -s work_management/tests -t .`

## Review Focus
- Switch off → no prompt anywhere, and saves behave exactly as today (test in Task 2).
- Editing an existing draft or pending assignment never re-asks, because lateness is decided when the record is first created (test in Task 2).
- Add crew for a payroll check (`add_for`) already requires a reason, so it is not asked twice (test in Task 2).
- A team leader stored as an Employee ID (no login) still gets a name in both tabs (Task 3 test: name fallback).
- An assignment with no planner, or a planner with no `from_date`, is not late and doesn't crash (Task 1 test).

---

### Task 1: Rules module + fields

**Files:**
- Create: `work_management/assign_ahead.py`
- Modify: the `work_management_settings.json` doctype (four fields in a new section "Assign the day before", after `max_backdate_days`)
- Modify: the `work_management_assigner.json` doctype (`late_assignment` Check RO, `late_reason` Data RO, `late_note` Small Text RO, appended after `custom_submitted_at`)
- Test: `work_management/tests/test_assign_ahead.py`

**Interfaces (Produces):**
- `REASONS: list[str]`, `PLAN_LATE = "Plan approved late"`
- `deadline(start, cutoff="18:00:00") -> str` returns `"YYYY-MM-DD HH:MM:SS"` = start − 1 day at cutoff. Returns `None` when start is empty.
- `is_late(saved_at, start, cutoff="18:00:00") -> bool`
- `reason_err(reason, note) -> str`, which returns "" when OK. Errors: empty reason, reason not in REASONS, Other without a note.
- `check(start, planner=None, now=None) -> dict`, which reads Settings and returns `{"late": 0|1, "deadline": str, "auto_reason": str|None}`. It returns late 0 when the switch is off. `auto_reason = PLAN_LATE` when the planner's `custom_approved_at` (or `approval_date` at 00:00) is after the deadline. Whitelisted.
- `summarise(rows, cutoff) -> {"by_leader": [...], "by_saver": [...], "late_rows": [...]}`. Each input row has `asg, start, created, approved_at, tl, tl_name, saver, saver_name, reason, note, farm, task, block`. A summary row has `key, name, total, late, plan_late, pct_late, top_reason`. `late_rows` holds only late rows, with `reason or "No reason given"`. `pct_late` excludes plan_late from the numerator.

- [ ] Tests: deadline("2026-11-27") == "2026-11-26 18:00:00"; is_late at 17:59 → False, 18:01 → True, on the day → True; empty start → not late; reason_err cases; summarise ranks by late desc and splits plan_late; history rows with no reason show "No reason given"; check() with switch off → late 0 (fake frappe).
- [ ] Run → fail; implement; run → pass.
- [ ] JSON fields; a test asserts the field names exist in both doctypes.
- [ ] Commit.

### Task 2: Assigner gate + screen

**Files:** mirror `server_scripts/wm_assigner.py`, `web_pages/work-assigner.js` → port + copy to app `public/js/work-assigner.js`. Test: `work_management/tests/test_assign_day_before_gate.py`

**Consumes:** `assign_ahead.check`, `reason_err`, `REASONS`.

- `a_submit`, NEW records only (not `editing`): after the backdate check, `lt = frappe.call("work_management.assign_ahead.check", start=bd_start, planner=planner)`. If `lt["late"]` and no `auto_reason`: when `late_reason` is not in form_dict, return `out["needs_late_reason"]=1`, `out["deadline"]`, `out["reasons"]` and write nothing. Otherwise validate with `reason_err`. Before insert, set `d.late_assignment=1`, `d.late_reason` (or the auto reason), `d.late_note`. After insert, add the comment `"Assigned late (deadline <deadline>) by <user>: <reason> — <note>"`.
- `a_add_crew` (skip when `add_for`) and `a_substitute`: the same check on the start date. Late → reason required (same needs_late_reason handshake) → comment on the assignment. No fields are set, because the KPI counts new assignments only.
- `a_pending` fields add `late_assignment`, `late_reason`, `late_note`.
- JS: one shared `askLate(d, args, resend)` modal (reason select + note), used by doSubmit, add crew and substitute. In the stage table, a red "Late" pill with the reason as a tooltip after the Ref.
- [ ] Tests (source-level, like test_one_worker_one_day): each of the three actions calls `assign_ahead.check`; a_submit only when not editing; add crew skips when add_for; a_pending lists late fields; the JS has `needs_late_reason` handling in all three calls; REASONS in the JS match the module.
- [ ] Fail → implement → port_app → copy JS → pass → check_ported → commit both repos.

### Task 3: Dashboard tabs

**Files:** mirror `server_scripts/wm_dashboard.py` (new actions `tl_late`, `tl_people`), `web_pages/work-management-dashboard.js` → port + copy. App `assign_ahead.py`: `late_report(farms, from_date, to_date, farm=None, team_leader=None)` and `crew_people(farms, from_date, to_date, team_leader, day=None)`. Test: `work_management/tests/test_tl_tabs.py`

- Both actions use the same visibility as `tl_kpis`: non-managers are forced to `team_leader = session.user`.
- `late_report`: assignments (docstatus<2, state != Rejected) whose `from_date` is in range, on FARMS, joined to the planner for `team_leader`, `custom_approved_at`/`approval_date`. Saver = `assigned_by or owner`. Names come from User full_name, else Employee employee_name, else the key. Cutoff = Settings value, else 18:00. → `summarise`.
- `crew_people`: workers on crews of assignments whose planner `team_leader` = tl and whose crew window overlaps the range. Per worker: activities (task label + block), days worked = distinct `work_date` on non-cancelled actuals of those assignments in range, today's status (Leave > Absent > Present(scan or Present-class attendance) > "Not scanned").
- JS: tabs `Performance | Late assigning | People` above the card body. Performance = the current tlLoad output. Late assigning: a `By team leader / By who saved` toggle; clicking a row lists its late rows. People: needs a team leader (picker from TLK.d.leaders when can_see_all), table of workers.
- [ ] Tests: summarise via late_report with a fake db; name fallback for an Employee ID; crew_people status precedence (pure helper `day_status(scan, att, leave)`); the dashboard source has both actions with the tl_all guard; the JS has the three tab labels.
- [ ] Fail → implement → port → copy → pass → commit.

### Task 4: 16:00 reminder

**Files:** `assign_ahead.py` (`unassigned_tomorrow(plans, taken)` pure, `send_reminder()`), `hooks.py` cron `"0 16 * * *"`. Test: added to test_assign_ahead.py.

- `send_reminder`: return 0 unless `assign_reminder`. Plans: workflow_state Approved, `from_date` = tomorrow, not closed (`custom_close_state` empty), with no assignment in a live state (Draft and Pending count as taken; Rejected doesn't). Group by farm. FMs = Stage Approver `stage_label = 'Assigner: Farm Manager'` with a scope. The notify list gets all farms. If nothing to list, nothing is sent. The link goes to `/work-assigner`. Escape names.
- [ ] Tests: unassigned_tomorrow excludes taken/closed/other days; gated on the setting; hook registered; sender; escape_html.
- [ ] Fail → implement → pass → full suite + check_ported → commit.

### Task 5: Verify on webstore.localhost
- [ ] Migrate webstore.localhost and switch the feature on. As a real FM or clerk: a late save prompts, a save before the cut-off doesn't, the FM tab shows the Late pill, the dashboard tabs render, and `send_reminder` returns its count. Then merge to master in both repos and push the app.
