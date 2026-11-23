# Missing Work Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Find task-worker days with presence but no actuals. Farms clear each one, by entering work or by giving a "no work" reason, from a new Actuals tab. The payroll check blocks a farm's approval until its days are cleared. A daily email nags team leaders, farm managers, the GM and HR.

**Architecture:**
- One real Python module, `work_management/missing_work.py` (app-only, like `absent_pay.py`), holds all the logic:
  - the finding query, plus a pure `classify()` that unit tests can drive without a site;
  - the excuse writes and the stamping;
  - a whitelisted endpoint `wm_missing_work(action=…)` for the new tab;
  - the reminder job.
- The mirror's sandboxed scripts (`wm_payment`, `wm_assigner`) call it through
  `frappe.call("work_management.missing_work.<fn>", ...)`. In the app this is a plain `frappe.call` and resolves the dotted path.
- The screens are vanilla JS in the mirror's `web_pages/*.js`. They are copied byte-for-byte into the app's `public/js`.

**Tech Stack:** Frappe v16, MariaDB, the site-less unittest suite, vanilla JS.

**Spec:** `docs/superpowers/specs/2026-11-23-missing-work-design.md`. Read it first. It holds the user's decisions and the edge-case rules.

## Global Constraints

- **Edit the mirror, never `api/*.py`.** Mirror: `~/vscodeProjects/kaitet-work-management`. After each change run `python3 port_app.py`. `scripts/check_ported.py` fails on hand edits.
- **Screen JS** in the app's `public/js/<x>.js` must be byte-identical to the mirror's `web_pages/<x>.js`. Copy it after each edit.
- **Mirror code compiles in the Server Script sandbox.** No names starting with `_`, no imports, no `x["k"] += 1` (write `x["k"] = x["k"] + 1`).
- **Tests:** `cd ~/vscodeProjects/work_management && PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest discover -s work_management/tests -t .`. The whole suite must pass at the end of every task (1401+ tests).
- **Branch:** `feature/missing-work` in BOTH the app (remote `upande_work_management`) and the mirror, off current master (app b912d3a + docs 2400cec/edc5ec8; mirror 453e808).
- **Commits:** authored `ghost-mann <iamaob8@protonmail.com>`, NO Claude co-author line.
- **SQL:** `portion` is a MariaDB reserved word; backtick it if touched. Escape `_` in LIKE patterns.
- **Wording, copied from the spec:**
  - Issue title: "Present, no work recorded".
  - Reasons: "Sent home – no work", "Rain / weather", "Sick / left early", "Scanned but not working", "Other".
  - Tab label: "Missing work".
- **Settings fields:**
  - `missing_work_reminder`: Check, default 0.
  - `missing_work_notify`: Small Text, one email per line.
- **Reminder time:** a fixed cron, `30 7 * * *`. This is a builder's call that replaces the spec's "send time" setting; note it in the spec.

## Review Focus

1. **A worker scanned in on two farms' crews the same day.** The day must appear once, owned by the crew whose farm has no actuals for them. If they have actuals on either crew, the day is not missing.
2. **A worker who left the company mid-period.** Days after their `relieving_date` never appear. Days before it do.
3. **A day with both an Absent and a Present/Half Day attendance.** Present wins, so the day is missing when there is a scan and no actuals. This matches the `pp.status IN ('Present', 'Half Day', 'Work From Home')` rule elsewhere.
4. **Excusing a day, then the work gets entered anyway.** Actuals win: the day is not missing, and the excuse is ignored (not double-counted in the HR summary).
5. **A farm with 600 workers over 31 days.** `mw_list` must use a fixed number of queries, all batched by date range, never one per worker.

---

### Task 1: Branches, data model, Settings

**Files:**
- Create: app `work_management/work_management/doctype/work_missing_day_excuse/{__init__.py,work_missing_day_excuse.json,work_missing_day_excuse.py}`
- Modify: app `work_management/work_management/doctype/work_management_settings/work_management_settings.json` (add the two Settings fields in a "Missing work" section)
- Modify: app `work_management/work_management/doctype/work_assignment_employee/work_assignment_employee.json` (add `added_for_check`, Data, read-only, label "Added late for payroll check")
- Test: app `work_management/tests/test_missing_work_doctypes.py`

**Interfaces:**
- Produces:
  - **DocType `Work Missing Day Excuse`**, autoname `hash`, module Work Management, not submittable. Fields:
    - `employee` (Link Employee, reqd), `employee_name` (Data, fetch_from employee.employee_name)
    - `farm` (Data, reqd), `work_date` (Date, reqd)
    - `reason` (Select: the 5 reasons, reqd), `note` (Small Text)
    - `assignment` (Link Work Management Assigner)
    - `marked_by` (Link User), `marked_at` (Datetime)
    - `payroll_check` (Data, read_only)
  - Unique `(employee, work_date)` is enforced in the controller's `validate`, because Frappe has no composite unique.
  - Permissions: System Manager full; read for the roles the payroll check doctypes give read to (copy them from `work_management_payroll_check_fix.json`).

- [ ] **Step 1:** Create the branch in both repos: `git switch -c feature/missing-work`.
- [ ] **Step 2:** Write the failing tests in `test_missing_work_doctypes.py`:
  - `test_excuse_fields`: load the JSON and assert the field names and types above, and that the `reason` options equal the 5 reasons joined by `\n`.
  - `test_unique_employee_day`: the controller source contains `frappe.db.exists("Work Missing Day Excuse", {"employee": self.employee, "work_date": self.work_date, "name": ["!=", self.name]})` and throws.
  - `test_note_required_for_other`: the controller throws when `reason == "Other"` and `note` is blank.
  - `test_settings_fields`: the Settings JSON has `missing_work_reminder` (Check, default "0") and `missing_work_notify` (Small Text).
  - `test_crew_field`: the Work Assignment Employee JSON has `added_for_check` (Data, read_only 1).
- [ ] **Step 3:** Run them. Expected: FAIL (files missing).
- [ ] **Step 4:** Create the DocType files and the controller (`validate` with the two rules), and add the Settings and crew fields. Copy the JSON style (indent, `modified`, `engine: InnoDB`) from a sibling doctype.
- [ ] **Step 5:** Run the full suite. Expected: PASS. Fix any doctype-guard tests, such as `test_payroll_check_doctypes.py`-style permission audits and `test_no_dangling_references`, that list every doctype.
- [ ] **Step 6:** Commit: `feat: Work Missing Day Excuse doctype and missing-work settings`.

### Task 2: Finding missing days (`missing_work.py` core)

**Files:**
- Create: app `work_management/missing_work.py`
- Test: app `work_management/tests/test_missing_work_find.py`

**Interfaces:**
- Produces, in `work_management.missing_work`:
  - **`REASONS: list[str]`**: the 5 reasons.
  - **`classify(presence, actuals, excuses, crews, home_farm) -> list[dict]`**: pure, with no frappe calls.
    - `presence`: an iterable of `(employee, day)` pairs, already filtered to task workers who were employed, not on holiday, not on approved leave, and not Absent-without-Present.
    - `actuals`: a set of `(employee, day)` with any actuals row (docstatus < 2).
    - `excuses`: a dict `(employee, day) -> excuse dict` (name, reason, note, marked_by, payroll_check).
    - `crews`: a dict `(employee, day) -> list of {assignment, farm, task_name, block, planner, team_leader}`.
    - `home_farm`: a dict `employee -> farm`.
    - Returns one dict per presence day that has no actuals:
      `{employee, day, farm, crews, excuse}`. The `farm` is the first crew's farm if `crews` is non-empty, else `home_farm[employee]`. `excuse` is None or the excuse dict.
  - **`find(farms: list[str], from_date: str, to_date: str, include_excused=False) -> list[dict]`**: runs the batched queries and calls `classify`, keeping rows whose `farm` is in `farms`. When `include_excused` is false, it drops rows with an excuse.
  - **`counts(farms, from_date, to_date) -> dict[farm, int]`**: the number of unexcused missing days per farm.
- Queries (one each, batched over the date range):
  - **Task workers:** use the same payable rule as `dashboard.py` lines 5127-5139. Port it as `task_worker_sql()` returning the SQL condition.
  - **Employees:** Active, or `relieving_date >= from_date`.
  - **Checkins:** distinct `(employee, DATE(time))`.
  - **Attendance:** docstatus 1, with status Present/Half Day/Work From Home counting as present and Absent as absent. Present wins over Absent on the same day.
  - **Holidays:** via `Employee.holiday_list`.
  - **Approved leave:** Leave Application docstatus 1, status Approved.
  - **Actuals:** `Work Actuals Employee` joined to `Work Management Actuals`, docstatus < 2.
  - **Crews:** the `people_board` date rule (dashboard.py ~5153-5166), joined to the planner for `team_leader`.
  - **Excuses.**
- A day counts as present when there is a checkin, or a Present-class attendance, and it is not an Absent-only day, a holiday, a leave day, or past the relieving date.

- [ ] **Step 1:** Write the failing tests (`classify` only, plain dicts):
  - `test_no_actuals_is_missing`
  - `test_actuals_on_any_crew_clears_it`: two crews, one of them with actuals → not returned.
  - `test_farm_is_crew_farm_else_home`
  - `test_excused_day_carries_excuse`
  - `test_actuals_beat_excuse`: the excuse exists and so do actuals → not returned.
  - Plus a source test, `test_find_is_batched`: `find`'s body has no `for` loop that contains `frappe.db.sql`. Check this by walking the AST.
- [ ] **Step 2:** Run them. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement `classify`, `task_worker_sql`, `find` and `counts`.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Verify against the live slice on webstore.localhost (:8003):
  `bench --site webstore.localhost execute work_management.missing_work.counts --kwargs "{'farms':['Endebess','Vale','Lokitela','Saboti'],'from_date':'2026-10-21','to_date':'2026-11-08'}"`.
  Expected: non-zero counts, and a hand spot-check of 3 rows against the attendance sheet ("present, no work" cells).
- [ ] **Step 6:** Commit: `feat: find present task workers with no actuals`.

### Task 3: Tab endpoint, excuses and stamping

**Files:**
- Modify: app `work_management/missing_work.py`
- Test: app `work_management/tests/test_missing_work_api.py`

**Interfaces:**
- Consumes: `find`, `REASONS` (Task 2).
- Produces:
  - **`@frappe.whitelist() wm_missing_work(**kwargs) -> dict`**, dispatching on `action`:
    - **`mw_list(farm, from_date, to_date)`**
      - Returns `{rows: [...], counts: {...}, farms: [...], open_check: {name, period_from, period_to} | None, can_excuse: bool, can_add_late: bool}`.
      - `rows` come from `find(..., include_excused=True)`, so the screen shows excused days greyed out with Undo.
      - Farm scope: the caller's permitted farms, from the same `User Permission` + Settings source the actuals screen uses (`get_config()["farms"]` filtered by the user's `Farm` permissions). Copy the pattern of `pb_my` in dashboard.py (~5121-5126).
    - **`mw_excuse(rows, reason, note)`**
      - `rows` is a JSON list of `{employee, day}`.
      - Refused when: the caller may not record work on that row's farm (the `enter_work` capability or the farm's FM role, same rule as `act_submit`); the reason is not in `REASONS`; `reason == "Other"` with a blank note; the day already has an excuse stamped with a payroll check.
      - Inserts one excuse per row, with `marked_by`/`marked_at`, and commits.
    - **`mw_unexcuse(names)`**: deletes the excuses whose `payroll_check` is empty, if the caller passes the same permission check.
  - **`stamp_excuses(check: str, farm: str, period_from: str, period_to: str) -> int`** and **`unstamp_excuses(check: str) -> int`**: plain functions used by Task 4.
  - **`open_check(farm: str, day: str) -> dict | None`**: the Payroll Check with status "Farm Review", `is_top_up` 0, `period_from <= day <= period_to`, and a farm row for `farm` that is not Approved.

- [ ] **Step 1:** Write the failing source/wiring tests:
  - `test_actions_exist` (all three)
  - `test_excuse_checks_farm_permission`: the body of `mw_excuse` mentions `enter_work` and the FM role check.
  - `test_other_needs_note`
  - `test_stamped_excuse_cannot_change`: both `mw_excuse` and `mw_unexcuse` filter on an empty `payroll_check`.
  - `test_unstamp_clears_only_this_check`: the SQL is `SET payroll_check = '' WHERE payroll_check = %s`.
  - `test_screen_actions_exist`: extend `test_every_action_the_screens_call_exists.py`, if it enumerates endpoints, to know `wm_missing_work`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the full suite. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: missing-work endpoint, excuses and stamping`.

### Task 4: Payroll check integration (mirror `wm_payment` + `work-payment.js`)

**Files:**
- Modify: mirror `server_scripts/wm_payment.py`:
  - `WMI_CLASS` (~line 4025 of the generated file)
  - `wmi_issues` (~4066)
  - `chk_farm_approve` (~4462)
  - `chk_send_back` (~4548)
  - `chk_cancel` (~4925)
  - `chk_detail` (~4329)
- Modify: mirror `web_pages/work-payment.js`, then copy it to app `public/js/work-payment.js`.
- Regenerate: app `api/payment.py` via `port_app.py`.
- Test: app `work_management/tests/test_missing_work_in_check.py`

**Interfaces:**
- Consumes: `find`, `stamp_excuses`, `unstamp_excuses` (Tasks 2-3), called as `frappe.call("work_management.missing_work.find", farms=[...], from_date=..., to_date=...)`.
- Produces:
  - **`WMI_CLASS["missing_work"] = ("block", "farm", "Present, no work recorded")`** and **`WMI_CLASS["added_late"] = ("ack", "HR", "Worker added to a crew late for this check")`**.
  - **In `wmi_issues(c, farm, keys)`:**
    - When `not c.is_top_up`, add one `missing_work` issue per unexcused missing day. The key is `employee + "|" + day`, `doc` is empty, and the farm is the row's farm.
    - Add one `added_late` issue per actuals row whose crew row has `added_for_check == c.name`. The key is the actuals row name, so the existing acknowledgement fingerprint applies.
  - **`chk_farm_approve`:**
    - The existing block-issue refusal already covers it. Append "Clear them in Actuals → Missing work." to the error when any open issue is `missing_work`.
    - After stamping actuals, call `stamp_excuses(pc.name, af, pc.period_from, pc.period_to)`.
  - **`chk_send_back` and `chk_cancel`:** call `unstamp_excuses(pc.name)` next to `wmpc_unstamp(pc)`.
  - **`chk_detail`:** add `out["excused"] = [{farm, reason, marked_by, n}]`, grouped from excuses in the check's dates for the check's farms.
  - **`work-payment.js`:**
    - Each `missing_work` issue group shows a link "Open Missing work" to `/work-actuals?tab=missing&farm=<farm>&from=<period_from>&to=<period_to>`.
    - The HR view lists `excused` as "No work given: N days" with a per-reason breakdown. It is non-blocking.

- [ ] **Step 1:** Write the failing tests (string tests in the style of `test_absent_pay_blocks_farm_approval.py`):
  - `test_issue_classes`
  - `test_top_up_skips_missing_work`: within `wmi_issues`, the `missing_work` block sits under `if not c.is_top_up`.
  - `test_farm_approve_stamps_excuses`
  - `test_send_back_and_cancel_unstamp_excuses`
  - `test_detail_returns_excused`
  - `test_js_links_to_missing_tab` (the string `tab=missing`)
  - `test_added_late_issue_reads_crew_flag`
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement in the mirror, run `python3 port_app.py`, and copy the JS.
- [ ] **Step 4:** Run the full suite, including `test_mirror_compiles_in_the_sandbox`, `test_mirror_defines_its_names` and `check_ported`. Expected: PASS.
- [ ] **Step 5:** Commit in both repos: `feat: payroll check blocks a farm with missing work days`.

### Task 5: Adding a worker late inside an open check (mirror `wm_assigner`)

**Files:**
- Modify: mirror `server_scripts/wm_assigner.py`, action `a_add_crew` (generated ~1247-1415).
- Regenerate: app `api/assigner.py`.
- Test: app `work_management/tests/test_add_crew_late_for_check.py`

**Interfaces:**
- Consumes: `open_check(farm, day)` (Task 3), via `frappe.call`.
- Produces: `a_add_crew` accepts two optional params.
  - **`until` (date):** when given, the new crew row is saved with status "Left" and `left_date = until`. This puts the worker on the crew for `start_date..until` only.
  - **`for_check` (check name):** when given, the GM backdate rule is skipped if all of these hold:
    - `open_check(farm, start_date)` returns that check, and `until` (required in this case) is ≤ the check's `period_to`;
    - the caller is the farm's FM (per `wmg_farm_err` passing and holding `FARM_APPROVER_ROLE[farm]`) or the GM;
    - a non-empty `backdate_reason` is given.
  - In that case it sets `added_for_check = for_check` on the crew row and adds an assignment comment: "Added late for payroll check <check> by <user>: <reason>". Every other validation (one-worker-one-day, Active employee, assignment Assigned, farm) still runs.

- [ ] **Step 1:** Write the failing tests:
  - `test_until_sets_left_date`
  - `test_for_check_needs_open_check_and_reason`
  - `test_for_check_only_fm_or_gm`
  - `test_backdate_rule_still_applies_without_for_check`: `wmg_backdate_err` is still called on the normal path.
  - `test_comment_logged`
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement, then run `port_app.py`.
- [ ] **Step 4:** Run the full suite. Expected: PASS.
- [ ] **Step 5:** Commit in both repos: `feat: add a worker to a crew late inside an open payroll check`.

### Task 6: Missing work tab (mirror `web_pages/work-actuals.js`)

**Files:**
- Modify: mirror `web_pages/work-actuals.js` (+ `.html` if panels are declared there), then copy to app `public/js/work-actuals.js` (+ `www/work-actuals.html`).
- Test: app `work_management/tests/test_missing_work_tab.py`

**Interfaces:**
- Consumes:
  - `wm_missing_work` `mw_list`/`mw_excuse`/`mw_unexcuse` (Task 3);
  - `wm_assigner` `a_add_crew` with `until`/`for_check` (Task 5);
  - the existing Enter Actuals flow.
- Produces:
  - **The tab:** `["missing","Missing work"]`, added in `buildTabs()` after Approvals and shown when `mw_list` returns any farm. Panel `p-missing`, added to the `showTab` list.
  - **Deep link:**
    - `?tab=missing&farm=&from=&to=` opens the tab prefilled.
    - `?assignment=<name>&date=<YYYY-MM-DD>&emp=<id>` opens Enter Actuals for that assignment at the week containing `date`, with that worker's cell focused.
    - Read both through the existing `URLSearchParams` handling (~line 49).
  - **Layout per the spec sketch:**
    - Group by day, then by crew (task · block · TL), with a "Not on any crew" group last.
    - Each row: name (ID), scan in–out, and the buttons Enter work / Add to assignment… / No work….
    - Header: "N days need work or a reason · X on a crew · Y not on any crew".
    - Bulk "Mark selected: No work…".
    - Excused rows are greyed out with their reason and an Undo button while unstamped.
  - **Add to assignment…:**
    - A picker of the same farm's Assigned assignments covering the day (from `mw_list` rows' farm via `a_approved_planners`-style listing; use the existing assigner endpoint that lists active assignments for a farm/date).
    - Calls `a_add_crew` with `start_date = until = day`. When `open_check` covers the day and the day is more than 7 days old, it also passes `for_check` and a required reason prompt.
    - On success it jumps to Enter work.

- [ ] **Step 1:** Write the failing tests:
  - `test_tab_registered` (both arrays)
  - `test_calls_exist`: the strings `mw_list`, `mw_excuse`, `mw_unexcuse`, `a_add_crew`, `for_check`
  - `test_deep_link_params`: `tab`, `assignment`, `date`, `emp` are read
  - `test_js_identical_to_mirror` (the existing byte-identical test may already cover it)
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement. Escape every server string with the file's existing `esc()`.
- [ ] **Step 4:** Run the full suite. Expected: PASS.
- [ ] **Step 5:** Commit in both repos: `feat: Missing work tab in Actuals`.

### Task 7: Daily reminder

**Files:**
- Modify: app `work_management/missing_work.py`, `work_management/hooks.py`
- Test: app `work_management/tests/test_missing_work_reminder.py`

**Interfaces:**
- Consumes: `find` (Task 2).
- Produces:
  - **`leader_for(team_leader: str, master_plan: str, day: str, stand_ins: list[dict]) -> str`**: pure. It returns the stand-in whose row has `team_leader == team_leader` and `from_date <= day <= to_date`, else `team_leader`.
  - **`recipients(rows, users_with_email: dict, fms_by_farm: dict, notify: list[str]) -> dict[email, dict]`**: pure. It maps each recipient to `{"rows": [...], "all_farms": bool}`:
    - on-crew rows go to the resolved leader, when that leader is a key of `users_with_email`;
    - every row also goes to its farm's FM(s), from the Stage Approver rows with a farm, the same source as the approval reminders;
    - every row goes to each `notify` address, with `all_farms: True`.
  - **`send_reminders() -> int`**:
    - Returns 0 at once unless `missing_work_reminder` is on.
    - Covers yesterday back to 7 days ago, and every farm in Settings.
    - Sends one email per recipient from `"Kaitet Work Management <notifications@karenroses.com>"`, with `add_css=False` and the subject "Missing work: N workers with no actuals". Recipients with nothing get no email.
    - The `all_farms` email opens with a per-farm count table.
    - The body links to `/work-actuals?tab=missing&farm=…&from=…&to=…`.
  - **hooks.py:** `scheduler_events["cron"] = {"30 7 * * *": ["work_management.missing_work.send_reminders"]}`.

- [ ] **Step 1:** Write the failing tests:
  - `test_stand_in_wins_on_its_dates`
  - `test_leader_without_login_falls_to_fm`
  - `test_notify_gets_all_farms`
  - `test_no_rows_no_email`
  - `test_gated_on_setting` (the source contains `missing_work_reminder` within the first 400 characters of `send_reminders`)
  - `test_hook_registered`
  - `test_sender`
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the full suite. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: daily missing-work reminder`.

### Task 8: Guide, end to end, merge

**Files:**
- Modify: the user guide source the suite builds (`docs/Work_Management_User_Guide.pdf` via `scripts/build_manual.py`): a "Missing work" section.
- Modify: the spec's "Daily reminder" section, to note the fixed 07:30 cron.

- [ ] **Step 1:** Add the guide section and run the suite, which regenerates the PDF. Expected: PASS.
- [ ] **Step 2:** End to end on webstore.localhost (:8003, live slice; `bench --site webstore.localhost migrate` first). Do these as a farm-manager user, not Administrator, as the "verify as the real user" rule requires:
  - open Missing work for Endebess over the slice's dates;
  - excuse 2 days;
  - enter work for 1 on-crew day, and see it drop off the list;
  - create a payroll check over those dates, and confirm Endebess approval is refused with the Missing work hint;
  - add a no-crew worker late with `for_check`, enter their work, and see `added_late` on the check;
  - clear the rest, approve, and confirm the excuses are stamped and that Undo is refused;
  - send back, and confirm they are unstamped;
  - with `missing_work_reminder` on and the notify list set to a test address, run `bench --site webstore.localhost execute work_management.missing_work.send_reminders` and read the queued Email Queue rows.
- [ ] **Step 3:** Merge `feature/missing-work` into master in both repos, with a fast-forward or a merge commit. Then push the app to `upande_work_management` master. The user deploys.
- [ ] **Step 4:** Commit and report the go-live steps from the spec's Rollout section:
  1. Deploy, then migrate.
  2. HR creates the 21 Oct – 20 Nov check.
  3. Set `missing_work_notify` = koskey@lokitelaorchards.com, hro@endebesscoffee.com, and switch the reminder on.
