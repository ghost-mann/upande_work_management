# Payroll Check and Duplicate-Day Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop double pay at entry (one worker, one day, one task) and gate payroll behind a
date-range Payroll Check that farm managers, then HR, then the GM approve.

**Architecture:** Logic is written in the mirror (`~/vscodeProjects/kaitet-work-management/server_scripts/wm_*.py`,
sandbox-safe: no `_` names; nested `def` allowed with a module prefix, as `wmpay_span`
does) and generated into `work_management/api/*.py` with `python3 port_app.py`.
Module-level hooks live in `app_only/wm_payment.py`. A worker row's
membership of a check is one new column, `Work Actuals Employee.payroll_check`. That
makes "a row is in one check, ever" structural, and the payment gate is one EXISTS clause
in the slots the week sign-off's `SIGNED_ONLY` already occupies.

**Tech Stack:** Frappe v16, RestrictedPython-compatible server scripts, vanilla JS screens.

**Spec:** `docs/superpowers/specs/2026-11-12-payroll-check-and-duplicate-guard-design.md`

## Global Constraints

- Mirror scripts must compile in the sandbox: no identifier starting with `_`. Nested
  helpers are prefixed `wmg_` (guard) or `wmpc_` (payroll check).
- Never hand-edit `api/*.py`. Edit the mirror, then run `port_app.py`.
  `public/js/*.js` must be byte-identical to the mirror's `web_pages/*.js`.
- The duplicate rule has no override and no Settings switch. `allow_split_day` is
  hidden and read as False.
- `payroll_check_required` defaults to 0. `max_backdate_days` defaults to 7.
- Tests run site-less: `PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest discover -s work_management/tests -t .`
- Commits: author ghost-mann, no Claude co-author line (repo convention).

## Review Focus

1. A worker released on assignment A and added to assignment B over the same dates must
   be refused unless B's start is after A's `left_date` (the 238-row live pattern).
2. Two actuals on the SAME assignment for the same worker-day: the old guard skipped
   this (`ac.assignment != %s`). B1 must not.
3. Editing your own Draft must not clash with itself. Exclude the doc being rewritten.
4. Send back must unstamp only rows not yet sent (`payment_ref` empty).
5. A late row in a Sent check's dates is payable only through a top-up check, never by
   a second normal check.

---

### Task 1: Settings, row column, check doctypes; drop week sign-off doctype

**Files:**
- Modify: `work_management/work_management/doctype/work_management_settings/work_management_settings.json`
  - replace section `section_week_signoff` / `week_signoff_required` / `week_signoff_notify` with
    `section_payroll_check`, `payroll_check_required` (Check, 0), `payroll_check_notify`
    (Small Text), and `max_backdate_days` (Int, 7)
  - set `allow_split_day` hidden
- Modify: `work_management/api/config.py`: `cfg["allow_split_day"] = False` always
- Create: doctypes `work_management_payroll_check`, `work_management_payroll_check_farm`
  (istable), `work_management_payroll_check_fix`
- Modify: mirror `doctypes/custom_fields.json` and the app's custom-field source, adding
  `Work Actuals Employee.payroll_check` (Data, read-only, indexed)
- Delete: `work_management_week_signoff` doctype dir (never shipped)

Payroll Check fields:
- `period_from`, `period_to`, `is_top_up`
- `status` (Farm Review / HR Review / GM Review / Approved / Sent / Cancelled)
- `created_by`, `hr_approved_by`/`_at`, `gm_approved_by`/`_at`
- `sent_back_reason`/`_by`/`_at`
- `worker_days`, `amount`, `dups_fixed`, `amount_zeroed`
- `farms` (Table → Payroll Check Farm: `farm`, `status` Pending/Approved, `approved_by`,
  `approved_at`)

Fix fields:
- `payroll_check`, `kind` (duplicate / paid twice / draft completed / rejected deleted)
- `employee`, `employee_name`, `work_date`, `farm`
- `kept_row`, `kept_actuals`, `zeroed_row`, `zeroed_actuals`
- `qty_before`, `amount_before`, `fixed_by`, `fixed_at`, `reason`

- [ ] Test `test_payroll_check_doctypes.py`:
  - each JSON loads
  - the status options equal the six above
  - `payroll_check` is in custom fields
  - `test_config_never_splits` asserts `get_config` source sets `allow_split_day` False
- [ ] Run, fail → implement → pass → commit.

### Task 2: Assignment guard (A1–A4) in `wm_assigner`

**Files:** mirror `server_scripts/wm_assigner.py`. Test `work_management/tests/test_one_worker_one_day.py`.

- Nested `wmg_busy(emps, dfrom, dto, exclude_asg)` → list of `{emp, asg, from, to}`.
  - A worker's window on an assignment is
    `COALESCE(we.start_date, a.from_date)` … `CASE WHEN status='Left' AND left_date THEN left_date ELSE a.to_date END`.
  - Rows count whatever their status. Assignment states: the four live ones.
- Used by `a_submit` (planner window), `a_add_crew` (start…to_date) and `a_substitute`
  (replacement start…to_date). Each refuses with no split branch.
- A4: `wmg_backdate_err(start)`.
  - If start < today − `max_backdate_days` and the caller is not GM / System Manager → error.
  - GM without a `backdate_reason` form value → error.
  - With a reason → add a comment on the assignment.
- [ ] Tests (exec the ported nested defs with a fake frappe, per `test_late_work_tops_up_its_week.py`):
  - `test_left_worker_still_blocks_their_dates` (SQL must not filter `status='Active'`)
  - `test_no_split_branch_left` (ported `assigner.py` has no `split_warning`)
  - `test_backdate_refused_for_clerk`
  - `test_backdate_allowed_for_gm_with_reason`
- [ ] Port, run, commit.

### Task 3: Actuals guard (B1–B4, C5 lock) in `wm_actuals`

**Files:** mirror `server_scripts/wm_actuals.py`. Test `test_one_worker_one_day.py` (extend).

- Nested `wmg_day_clashes(pairs, exclude_doc)`.
  - Input pairs: (emp, date).
  - Matches rows on any actuals with `workflow_state != 'Rejected' AND docstatus < 2` and
    `(actual_quantity > 0 OR amount > 0)`, excluding `parent = exclude_doc`.
  - Returns `{(emp,date): {doc, task, farm}}`.
- Nested `wmg_off_assignment(assignment, pairs)` → the pairs outside the worker's window
  on that assignment (B2).
- Nested `wmg_locked(farm, dates)` → the name of a check locking those dates.
  - A check locks when its status is in HR Review / GM Review / Approved, or it is in
    Farm Review with that farm Approved.
  - Non-top-up and top-up checks both count.
- `act_submit`:
  - replace the "DUPLICATE-DAY GUARD" block with hard B1 + B2 errors (no `att_override` path)
  - turn the "released after" warning into the B2 error
  - check C5 before writing
- `act_fm_approve`, `act_hr_approve`, `act_gm_approve` and `act_reject` re-run B1/B2/C5 on
  the doc's current rows (B3).
- Remove the `ws_meta` / `ws_week` / `ws_signoff` / `ws_reopen` actions and the `WS_DT`,
  `WS_IN_WEEK` and `WS_BLOCKING` constants. Keep `ws_notify` / `ws_delete_rejected` (the
  check calls them) and `hist_*`.
- [ ] Tests:
  - `test_clash_ignores_task_and_assignment` (the SQL has no `ac.task =` and no
    `ac.assignment !=`)
  - `test_clash_excludes_own_doc`
  - `test_zeroed_row_does_not_clash`
  - `test_approve_rechecks`
  - `test_week_signoff_actions_gone`
- [ ] Port, run, commit.

### Task 4: Payroll check actions + payment gate + stamp fix in `wm_payment`

**Files:** mirror `server_scripts/wm_payment.py`, `app_only/wm_payment.py`. Test `test_payroll_check.py`.

- Replace `WS_GATE` / `SIGNED_ONLY` with `PC_GATE` (Settings `payroll_check_required`) and:

  ```
  CHECKED_ONLY = " AND EXISTS (SELECT 1 FROM `tabWork Management Payroll Check` pc WHERE pc.name = we.payroll_check AND pc.status IN ('Approved','Sent'))"
  ```

  It goes in the same slots `SIGNED_ONLY` used.
- Keeper rule, nested `wmpc_keeper(copies)`.
  - Each copy has `{row, asg_start, asg_created, ac_created}`.
  - Sort on `(asg_start or '9999', asg_created or '9999', ac_created)` and return the first.
- Actions:
  - `chk_list` returns:
    - the checks, newest first
    - the late rows in Sent checks' dates: CONFIRMED rows with `payroll_check` empty and
      `paid = 0`
    - caller capabilities
  - `chk_create` (HR / GM / System Manager; `from`, `to`, `top_up`):
    - Refuse if a non-cancelled, non-top-up check overlaps (C2).
    - A top-up must sit inside Sent check dates and needs late rows.
    - Farms = FARMS with any actuals row or open record in range.
  - `chk_detail` returns, per farm:
    - counts
    - duplicates, each with both copies and the keeper marked
    - unfinished records (Draft / Rejected / Pending*)
    - absent / leave-paid counts (information only)
    - each farm's state
    - the fix log
  - `chk_fix_dup` (`check`, `zero_row`, `reason`), or all on a farm (`farm`, `all=1`).
    - Zeroes qty and amount, resets the review stamps, recomputes the parent totals the
      way `pay_fix_duplicates` does, and writes a Fix.
    - An FM may fix only same-farm duplicates; HR and GM may fix any.
    - Refuses if the row being zeroed is paid. It may zero the paid copy's partner only
      when that partner is unpaid.
  - `chk_farm_approve`:
    - FM of that farm, or GM / System Manager.
    - Blocked by that farm's same-farm duplicates or unfinished records (C3).
    - Stamps `payroll_check` on the farm's CONFIRMED, payable, unpaid rows in range that
      have it empty. A top-up uses the same query, restricted to late rows.
    - When the last farm approves → HR Review, and email HR.
  - `chk_hr_approve`: blocked by any duplicate or unfinished record in range → GM Review,
    and email the GM.
  - `chk_gm_approve` → Approved, and email HR.
  - `chk_send_back` (any reviewer, `reason` required):
    - Unstamps rows where `payroll_check = name AND IFNULL(payment_ref,'') = ''`.
    - Sets all farms to Pending and the status to Farm Review, logs who, when and why,
      and emails the FMs.
  - `chk_cancel` (HR / GM): same unstamp; refused once any row is sent.
- After every send action, mark checks with no unsent stamped rows as Sent
  (`wmpc_mark_sent`).
- C4: `_stamp_actuals_paid_for_payment` stamps only rows whose `parent` is a line's
  `actuals` and whose employee is that line's employee, with `work_date` within the line's
  `work_from` … `work_to` (falling back to the payment period).
- [ ] Tests:
  - `test_keeper_is_first_assignment`
  - `test_checked_only_replaces_signed_only`
  - `test_stamp_uses_line_actuals` (fake frappe: a row on another actuals is not stamped)
  - `test_send_back_unstamps_only_unsent`
  - `test_overlap_refused_except_top_up`
  - every `chk_*` action is listed in `test_every_action_the_screens_call_exists` once the
    JS calls it
- [ ] Port, run, commit.

### Task 5: Payment screen "Payroll checks" tab; Actuals screen loses the Week tab

**Files:** mirror `web_pages/work-payment.js` / `.html`, `web_pages/work-actuals.js` / `.html`; the app's `www/*.html` copies.

- New tab `checks` (first tab):
  - list of checks with status chips
  - HR's "New payroll check" (dates, top-up toggle)
  - the open check: farm strip (Pending / Approved), Problems (duplicates side by side,
    keeper marked, Zero other, Fix all on farm), unfinished records (Notify / Delete
    rejected via `wm_actuals` `ws_notify` / `ws_delete_rejected`), info counts
  - role-gated buttons: Approve my farm / HR approve / GM approve / Send back / Cancel /
    Send to payroll
  - an audit-history sub-panel: the fix log, with paid-twice totals by farm and month
- Send to payroll calls the existing `pay_bulk_submit` with the check's dates.
- Actuals: remove the Week sign-off tab; keep History.
- [ ] Existing screen tests pass: action names exist, no `window.prompt`, cache-bust,
  byte-identical JS.
- [ ] Commit.

### Task 6: Back-fill paid-twice history

**Files:** Create `work_management/payroll_check_backfill.py`: `run(dry_run: bool = True) -> dict`.

- Writes one Fix of kind `paid twice` per worker-day where two or more rows are paid.
- Idempotent: it skips any `(employee, work_date)` already logged.
- [ ] Test `test_backfill_idempotent` with a fake frappe.
- [ ] Commit.

### Task 7: End-to-end on webstore.localhost

- [ ] Refresh the live slice:
  ```
  cd ~/frappe-v16-bench/e2e/wm_live && python3 extract.py && python3 extract_warehouses.py
  cd ../../sites && ../env/bin/python ../e2e/wm_live/load.py webstore.localhost --reset
  ```
- [ ] `bench --site webstore.localhost migrate`, then serve on :8003.
- [ ] As the real users:
  - a clerk tries a cross-task duplicate (refused) and a released-then-re-added worker (refused)
  - HR creates a check for 2026-10-21 → 2026-11-20
  - each FM fixes and approves
  - HR approves, then the GM approves
  - send
  - verify only the stamped rows are Paid
  - send back a second check and verify it unlocks
- [ ] Compare the duplicate counts with the spec's live table.
