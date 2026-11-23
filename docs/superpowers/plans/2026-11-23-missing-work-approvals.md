# Missing Work Part 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- Enter a missing day's work directly from Missing work, as its own small actuals record.
- Put every fix (work and "no work" reasons) through farm manager → HR → GM, from a new Waiting for approval tab.
- Show To clear as a monthly attendance grid, and let A days ask HR to correct attendance.

**Architecture:**
- **`work_management/missing_work.py`** (app-only):
  - the shared loader and statuses;
  - the grid builder;
  - the reason approvals;
  - the Waiting list;
  - the attendance-request action.
- **The mirror's `wm_actuals`:**
  - gains a `missing_fix` branch in `act_submit`;
  - deletes missing-day records in `act_reject`.
- **The mirror's `wm_payment`:** reads the new statuses.
- **The screen:** the mirror's `web_pages/work-actuals.js`, copied byte-for-byte to the app.

**Tech Stack:** Frappe v16, MariaDB, the site-less unittest suite, vanilla JS, and Playwright (the bench env) for the e2e script.

**Spec:** `docs/superpowers/specs/2026-11-23-missing-work-approvals-design.md`, which includes "Later decisions". Part 1 is `docs/superpowers/specs/2026-11-23-missing-work-design.md`.

## Global Constraints

- **Branch:** keep working on `feature/missing-work` in BOTH repos (app `~/vscodeProjects/work_management`, mirror `~/vscodeProjects/kaitet-work-management`).
- **Generated code:**
  - Edit the mirror's `server_scripts/wm_*.py`, then run `python3 port_app.py`. Never edit the app's `api/*.py`.
  - Copy `web_pages/work-actuals.js` to the app's `public/js/work-actuals.js` byte-identical.
- **Sandbox:** mirror code compiles in the sandbox. No `_`-prefixed names, no imports, no `+=` on subscripts. It calls the app module via `frappe.call("work_management.missing_work.<fn>", ...)`.
- **Tests:** `cd ~/vscodeProjects/work_management && PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest discover -s work_management/tests -t .` must stay green. Restore `docs/Work_Management_User_Guide.pdf` after runs (it regenerates), except in the docs task.
- **Commits:** author `ghost-mann <iamaob8@protonmail.com>`, with NO co-author line.
- **Doctype JSON edits** bump `modified` to `2026-11-23 12:00:00.000000`.
- **Reason statuses (exact):** `Pending Farm Manager`, `Pending HR`, `Pending GM`, `Approved`, `Sent back`.
- **Fixed rules:**
  - The plan's quantity cap stays.
  - One record per worker.
  - Reasons use a strict two-person rule; work uses the existing `wmg_step_err`.
- **Local test site:** webstore.localhost (`bench --site webstore.localhost …`). The dev server is on :8003 (`bench --site webstore.localhost serve --port 8003`). Users' password is `admin`. Never send real email: e2e and smoke runs patch `frappe.sendmail` or leave the reminder off.

## Review Focus

1. **A worker with two missing days on the same assignment, entered one after the other.** The second save must create a second record. It must not resume the first one, whose stage is Pending.
2. **A reason sent back, then marked again.** The same record resets to Pending Farm Manager and clears the sent-back fields, and the grid shows it as waiting, not sent back.
3. **An Absent day that already has an open Attendance Request.** "Ask HR" must not create a second one, and the cell shows it as already asked.
4. **A farm switched to the Actuals HR step off in Settings.** Reasons skip that step: Farm Manager → GM.
5. **The grid for 600 workers × 31 days.** It runs a fixed number of queries and returns compact cells (codes, not objects) so the page stays fast.

---

### Task 1: Data fields

**Files:**
- Modify (app doctype JSON):
  - `work_management_actuals` (+`missing_work_fix` Check, read_only);
  - `work_missing_day_excuse` (+`status` Select with the 5 statuses, default `Pending Farm Manager`; +`fm_by`/`hr_by`/`gm_by` Link User; +`fm_at`/`hr_at`/`gm_at` Datetime; +`sent_back_by` Link User; +`sent_back_at` Datetime; +`sent_back_reason` Small Text, all read_only);
  - `work_management_deleted_actuals` (+`missing_employee` Data, +`missing_work_date` Date).
- Test: `work_management/tests/test_missing_work_doctypes.py` (extend).

- [ ] Write failing tests for each field (type, options, default, read_only), then run them. Expected: FAIL.
- [ ] Edit the JSONs (bump `modified`), then run the full suite. Expected: PASS.
- [ ] Commit: `feat: fields for missing-day records and reason approvals`.

### Task 2: Loader, statuses and grid (`missing_work.py`)

**Interfaces, produced:**
- **`load(farms, from_date, to_date) -> dict`** holds the batched raw sets. It is the current `find` body, split out. It adds:
  - `fix_states`: `{(emp, day): workflow_state}` for actuals rows in records with `missing_work_fix = 1`;
  - `normal_actuals`: a set of (emp, day) from non-fix records;
  - `absent`, `leave`, `holiday`, `half` sets;
  - `ar_open`: a set of (emp, day) covered by an Attendance Request with docstatus < 2;
  - `sent_back`: `{(emp, day): {by, reason}}`, from Deleted Actuals rows with `missing_employee` set.
- **`day_state(emp, day, L) -> str`**: pure. It returns one of `open`, `waiting`, `cleared`, `none`:
  - **cleared:** `normal_actuals`; or a fix state `CONFIRMED`; or an excuse `Approved`.
  - **waiting:** a fix state that is not CONFIRMED; or an excuse status starting `Pending`.
  - **open:** present and none of the above, which includes an excuse `Sent back`.
  - **none:** not present.
- **`find(...)`** keeps its signature. A row's `excuse` now carries `status`, and rows carry `state` (open/waiting). By default it returns open rows only. `include_excused=True` adds waiting rows and rows with approved reasons. Callers keep working.
- **`grid(farm, from_date, to_date) -> dict`**:
  - Returns `{days: [...], workers: [{emp, name, designation, cells: "codes", open: n}], legend}`, with one code per day:
    - `P` present, `H` half day, `A` absent, `L` leave, `O` off;
    - `?` no record, `M` missing, `W` waiting, `R` reason approved, `X` asked HR;
    - lowercase means work recorded; for example `p` is present with work.
  - Workers: every task worker whose home farm is `farm`, plus anyone on `farm`'s crews in the range. They sort by open count descending, then name.
- **Crew dicts:** also `uom` (from the planner).

**Tests** (`test_missing_work_find.py` extend, pure where possible):
- `test_day_state_rules`: one assertion per rule above.
- `test_sent_back_excuse_is_open`.
- `test_pending_fix_is_waiting_confirmed_is_cleared`.
- `test_grid_codes`: build a small `L` dict and assert the code string. Add `grid_codes(emp, days, L)` as a pure helper used by `grid`.
- `test_grid_lists_every_task_worker_and_sorts_open_first`.
- `test_load_is_batched`: the AST rule from part 1.

- [ ] RED, then GREEN, then the full suite, then commit: `feat: missing-work statuses and monthly grid data`.

### Task 3: `act_submit` missing-day branch + `act_reject` delete (mirror `wm_actuals`)

**Interfaces:**
- **`act_submit` with `missing_fix=1`:**
  - Rows must all be ONE employee. Each cell must be `open` per `frappe.call("work_management.missing_work.find", farms=[farm], from_date=d, to_date=d)`, with `crews[0].assignment == assignment`.
  - The branch skips only the "already has an actuals record in progress" refusal and the existing-record resume. It always creates a new record.
  - It skips the "submit unlocks at target" rule and moves the record to `STAGE_NEXT["actuals_submit"]`.
  - It sets `missing_work_fix = 1`.
  - The cap and every other validation run unchanged.
- **`act_reject` on a record with `missing_work_fix = 1`:**
  - It runs the same step-role checks.
  - It then calls `wmg_log_deleted` (passing `missing_employee`/`missing_work_date` from its row) and deletes the record. It returns `out["deleted"]`.

**Tests** (`test_missing_day_save.py`, string tests in the style of `test_add_crew_late_for_check.py`):
- `test_flag_read`
- `test_validates_open_day_and_crew`
- `test_one_employee_per_record`
- `test_skips_live_lock_only_for_flag`
- `test_never_resumes_existing`
- `test_goes_straight_to_first_stage`
- `test_cap_still_applies` (the "Exceeds plan target" path is not bypassed by the flag)
- `test_reject_deletes_fix_and_logs_day`

Smoke on webstore: save a fix on an assignment that has a CONFIRMED record. Expected: a new record at Pending Farm Manager.

- [ ] RED, then GREEN, then port, then the suite, then smoke, then commit both repos: `feat: enter a missing day's work as its own record`.

### Task 4: Reason approvals, Waiting list, ask HR (`missing_work.py`)

**Interfaces (new `wm_missing_work` actions):**
- **`mw_waiting(farm)`:**
  - Returns `{work: [...], reasons: [...], your_turn: n}`.
  - `work` holds records with `missing_work_fix = 1` that are not CONFIRMED: name, employee, name, day, task, qty, uom, amount, stage, entered_by, `can_act` (the viewer holds that step's role and did not enter it).
  - `reasons` holds excuses with status Pending*: name, employee, day, reason, note, stage, marked_by, `can_act`.
- **`mw_approve(names)`:**
  - Moves each reason to its next configured stage. The chain comes from the Settings Actuals stages that are switched on: FM → HR → GM, skipping any that are off. The last stage sets `Approved`.
  - Rules: farm manager step = farm role or GM; HR = HR head roles; GM = General Manager.
  - Refused when: the approver marked the reason; or, at the GM step, the approver took the HR step.
- **`mw_send_back(names, reason)`:** any current step-holder. It sets `Sent back` and the sent_back fields. A reason is required.
- **`mw_excuse`:** re-marking resets `status` to `Pending Farm Manager` (or the first configured stage) and clears the sent_back fields.
- **`mw_ask_hr(employee, day)`:**
  - Requires that the caller may record work on the farm and the day is Absent.
  - Skips the request if one is already open.
  - Otherwise it creates an On Duty Attendance Request and moves it into HR's queue. Copy the workflow-next-state query from `wm_actuals` ~1924.
- **`mw_grid(farm, from_date, to_date)`:** returns `grid(...)` plus `farm_counts`, `open_check`, `assignments`, `late_farms` and `reasons`, as `mw_list` does.

**Tests** (`test_missing_work_approvals.py`):
- the stage chain with HR off;
- no self-approval;
- HR ≠ GM;
- send back needs a reason;
- re-marking resets the status;
- no second ask-HR request;
- `mw_waiting` lists only non-final items;
- `can_act` follows the roles.
- Factor the stage logic into the pure `next_stage(status, chain)` and `may_step(stage, roles, farm, cfg)`, and test them directly.

- [ ] RED, then GREEN, then the suite, then commit: `feat: approve missing-work reasons in three steps; waiting list; ask HR`.

### Task 5: Payroll check reads the statuses (mirror `wm_payment`)

- **`missing_work` issues:** open rows as before. Waiting reasons add issues whose detail is "reason waiting for {stage}". Use `find(..., include_excused=True)` and filter state `waiting` with a Pending excuse.
- **Stamping and the excused summary:** `status = 'Approved'` only.
- **Tests** (`test_missing_work_in_check.py` extend):
  - `test_waiting_reason_still_blocks_farm`;
  - `test_only_approved_reasons_stamped_and_counted`.

- [ ] RED, then GREEN, then port, then the suite, then commit both repos: `feat: payroll check counts only fully approved fixes`.

### Task 6: Screens (mirror `web_pages/work-actuals.js`)

- **Missing work gets two sub-tabs:** **To clear** and **Waiting for approval (n)**. The count is `your_turn`.
- **To clear:**
  - Farm buttons and the summary card stay.
  - Below them is the monthly grid. Use the dashboard sheet's look: sticky worker column, day headers with the weekday, a legend, a horizontal scroll, and one cell class per code.
  - **Clicking an M cell** opens a side panel for that worker and day, with: scan times, the crew, "Enter quantity [ ] {uom} · Send for approval" (calls `act_submit` with `missing_fix=1`), "Add to a crew" (part 1), and "No work" (reason chips).
  - **Clicking an A cell** opens the panel with "They did work: ask HR to correct the attendance".
  - **W, R and X cells** show their status in the panel.
  - **Bulk:** ticking cells in tick mode leads to the reason bar (part 1).
- **Waiting for approval:**
  - Two sections, Work entered and No work given, grouped by stage, with "Your turn" first.
  - Per row: Approve and Send back (an inline reason input).
  - Per group: tick-all and "Approve ticked".
  - Work uses `act_fm_approve`/`act_hr_approve`/`act_gm_approve`/`act_reject` on `wm_actuals` (`name=`). Reasons use `mw_approve`/`mw_send_back`.
- **Tests** (`test_missing_work_tab.py` extend):
  - the sub-tabs exist;
  - the grid renders from `mw_grid`;
  - the cell click opens the panel;
  - the enter-quantity call sends `missing_fix:1`;
  - the Waiting actions call the five endpoints;
  - `esc()` is used on server strings;
  - the legend lists every code.

- [ ] RED, then GREEN, then copy the JS, then the suite, then a screenshot review at 1400px and 400px, then commit both repos: `feat: Missing work grid and Waiting for approval tab`.

### Task 7: Reminder + docs

- **The reminder:** it already uses `find()` (open only), so it needs no change. Assert that in `test_missing_work_reminder.py`.
- **The guide:** update `docs/manual_content.py` and `docs/USER_GUIDE.md` for the grid, the three-step approval and ask HR. Regenerate the PDF (via the suite) and commit it.

- [ ] Commit: `docs: Missing work part 2 in the user guide`.

### Task 8: End-to-end script and run

**Files:**
- Create: `scripts/e2e_missing_work.py`. It is run with `~/frappe-v16-bench/env/bin/python scripts/e2e_missing_work.py`. It is not part of unittest.

**What the script does:**
- Uses Playwright against http://127.0.0.1:8003, logging in as four users:
  - a clerk who has `enter_work` and is not a farm manager (look one up on webstore; if none exists, give a test user the Work Entry role and Vale permission in setup, and remove it in teardown);
  - kibett (Vale FM);
  - hro@endebesscoffee.com (HR);
  - koskey@lokitelaorchards.com (GM).
- Runs the spec's scenarios 1–7 plus ask-HR, and asserts the grid codes, the Waiting tab and the check issues after each step.
- Setup records everything it creates. Teardown deletes it: records, excuses, crew rows, comments, Attendance Requests, Deleted Actuals log rows. It prints PASS/FAIL per scenario.

- [ ] Write the script, then run it. Expected: all PASS. For each bug found: write a failing site-less test, fix, rerun the e2e, then commit.
- [ ] Final whole-branch review by a fresh reviewer, then a fix pass, then report.
