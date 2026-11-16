# Pay Integrity and Clearing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every validation in the pay-integrity design, plus a payroll-check clearing section where every issue in the dates is fixed or acknowledged before payroll.

**Architecture:**
- Logic lives in the mirror (`~/vscodeProjects/kaitet-work-management/server_scripts/wm_*.py`; nested defs prefixed `wmg_` / `wmpc_` / `wmi_`) and is ported with `port_app.py`.
- App-only modules (`duplicate_guard.py`, `capabilities.py`, hooks, patches, report) are edited in the app.
- One shared write-gate per endpoint: a WRITE_ACTIONS set, a POST check, a capability check, and the farm taken from the record.

**Tech Stack:** Frappe v16, RestrictedPython-safe mirror scripts, vanilla JS screens.

**Spec:** `docs/superpowers/specs/2026-11-12-pay-integrity-and-clearing-design.md` (on top of `2026-11-12-payroll-check-and-duplicate-guard-design.md`)

## Global Constraints

- Mirror scripts: no identifier starting with `_`. `def` is allowed; prefix nested helpers.
- Never hand-edit `api/*.py`. `public/js/*.js` must equal the mirror's `web_pages/*.js`.
- **Thresholds and defaults:**
  - quantity: 2× daily target → flagged, needs a reason; 3× → refused; hour-measured tasks refused above 24 (Settings `qty_flag_multiple` = 2, `qty_refuse_multiple` = 3)
  - `max_backdate_days` = 7
  - late entry = more than 14 days after the work
- New capability `repair_payments`, default System Manager. The live seed patch adds HOD HR.
- Never zero, re-price or unstamp a row that is paid or has a `payment_ref`.
- Commits: author ghost-mann, no co-author line.
- Suite: `PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest discover -s work_management/tests -t .`

## Review Focus

1. Real users must keep every action they need: the clerk's actuals entry, the FM's add-crew on their own farm, HR sends. Over-locking on payroll day is the worst failure.
2. A leaver's days up to `relieving_date` must still be payable.
3. Stand-ins: when the FM entered a record themselves, the listed stand-in must be able to approve it.
4. Acknowledgements must not survive a change to the row they acknowledged.
5. Grouped duplicate fixes must never zero a paid or in-run copy.

---

### Task 1: Lock-down (who can act)

- **Capabilities.** `capabilities.py`: add `repair_payments` to the CATALOGUE. Add it to the CAPABILITIES literal in every mirror module.
- **Write-gate** in each mirror module (`wm_payment`, `wm_actuals`, `wm_assigner`, `wm_planner`, `wm_masterplan`, `wm_rates`, `wm_payroll`, `wm_payroll_recompute`):
  - `WMG_WRITES = {...}` names that module's writing actions.
  - Refuse if `action in WMG_WRITES and (frappe.request and frappe.request.method) != "POST"`.
- **Capability per action:**
  - `rates`: every action that writes with `dry_run=0` → `set_rates`
  - `pay_*` repair tools (`purge_queue`, `fix_*`, `recalc_wages`, `round_amounts`, `fix_orphan_refs`, `release_inactive`), `wm_payroll` writes, `wm_payroll_recompute` → `repair_payments`
  - `pay_run_withdraw`, `pay_bulk_withdraw`, `pay_worker_edit_day(s)` → `send_payment`
  - `act_submit` → `enter_work` OR an FM of the record's farm
  - `a_substitute` (both copies) and `a_reject` → the same gate as add-crew or approve
- **Farm from the record.** Each of these reads the farm from the assignment / actuals / employee and requires it in FARMS: `a_add_crew`, `a_release`, `a_substitute`, `act_submit`, `pay_worker_edit_day(s)`, and the send employee list.
- **FM role per farm.** `a_add_crew` and `a_release` use a farm-specific FM role (the fmallowed pattern), not `startswith("Farm Manager")`.
- **Desk rates.** `rates.task_on_update` refuses a `custom_rate` change without `set_rates`; rate × target must be within ±2% of a wage tier unless `custom_rate_reason` is given. Remove HR Manager write from the `work_task_rate` DocPerm.
- **`wm_payroll migrate_state`** is System Manager only, refuses Paid/Cancelled targets, and refuses payments that have an Additional Salary.
- **Patch** `v1_0/seed_repair_payments_capability`: adds rows (repair_payments → HOD HR, System Manager).
- **Tests** (`test_lockdown.py`):
  - every listed action appears in its module's WMG_WRITES
  - every module has the POST refusal
  - rates writes are gated
  - the add-crew farm check
  - the capability exists, with default System Manager
  - the patch is registered

### Task 2: Amount sanity

- **Settings fields:** `qty_flag_multiple` (Float, 2), `qty_refuse_multiple` (Float, 3).
- **New row field:** `Work Actuals Employee.qty_flag` (Small Text, read-only).
- **`act_submit`:**
  - refuse `work_date > today`
  - per cell: qty > refuse×target → error; qty > flag×target → requires `qty_reason` (form param), stored in `qty_flag`
  - hour-measured (`uom` in Hour/Hours/hrs) qty > 24 → error
- **Plan-target cap:** count `Pending Farm Manager`. Nested `wmg_cap_err(docname)` is re-run in the FM, HR and GM approvals and in early close.
- **`duplicate_guard.validate_actuals`** (desk/REST):
  - recompute each row's `amount = round(qty × rate, 2) if count_in_payroll else 0`
  - refuse negative qty, and dates outside from/to
  - recompute the parent totals
  - apply the B2 window rule and the payroll-check lock
- **New plans** (`planner.py` create) take the rate from the Work Task Rate period covering `from_date`. Refuse a plan straddling a rate change, and a UOM differing from the master-plan line.
- **Tests:**
  - future date refused
  - cap refusal / flag needs a reason
  - the cap query includes Pending Farm Manager
  - approvals call `wmg_cap_err`
  - the desk hook recomputes the amount (fake frappe)
  - the planner uses the rate period

### Task 3: Dates and people

- **Backdate guard:** computed from the plan dates on any new or Draft/Rejected submit, whatever `assignment` is passed. A pending edit is exempt only if the dates are unchanged.
- **`a_submit`:** the plan must be Approved, not Closed, have no other live assignment, and its farm must be in FARMS.
- **Putting a worker on work:** requires status Active plus the task-worker match plus the farm match, on every add path (`a_submit`, `a_add_crew`, `a_substitute`).
- **Recording work:** work_date between `date_of_joining` and `relieving_date` (inclusive), whatever the status.
- **Release / substitute dates:** start ≤ left_date ≤ min(today, to_date); left_date ≥ the last recorded work_date on that assignment; replacement start > outgoing left_date.
- **Planner:** refuse to_date < from_date, and backdating beyond max (GM with a reason).
- **Crew edit while pending:** only the current step's approver. Any change sends the assignment back to Pending Farm Manager. Validate against `d.planner_request`.
- **Tests** for each, structural plus fake-frappe where the logic is a helper.

### Task 4: Approval integrity and stand-ins

- **Stand-ins table:** child doctype `Work Management Approval Stand In` (`stage` Select: actuals_fm / actuals_hr / actuals_gm / assigner_fm / assigner_hr / assigner_gm / planner_fm / check_hr / check_gm; `farm` Link Farm, optional; `user` Link User). Settings table `approval_stand_ins`.
- **Nested `wmg_step_err(entered_by, previous_by, stage, farm)`:**
  - refuses when the session user equals `entered_by` or `previous_by`, unless they are a listed stand-in for (stage, farm) who is NOT themselves the enterer or previous approver
  - System Manager break-glass needs `override_reason`, which is logged and raised as `approval_gap`
  - applied at actuals FM/HR/GM, assigner FM/HR/GM, planner approve, and the check HR/GM steps
- **Edit-in-place:**
  - only by the current step's role holder (and the farm at the FM step)
  - `edit_doc`'s assignment must equal `assignment`
  - if the total amount changed after any approval → back to Pending Farm Manager, clearing the approvals, with a comment logging old and new totals
- **Early close:**
  - skip Rejected
  - include a Draft only if listed in `confirm_drafts`
  - run `wmg_guard_err`, `wmg_cap_err` and the attendance re-check per record
- **End of chain:** whichever step ends it sets docstatus 1 and runs the roll-up (factor the GM block into a nested `wmg_finalise(nm)`). Settings validate refuses a chain with no approval step on.
- **Desk hook:** `duplicate_guard.on_actuals_update` records `fm/hr/gm_approved_by` plus timestamps when `workflow_state` changes on the desk, and applies the self-approval rule.
- **Tests:** stand-in allowed, self refused, override needs a reason, edit-doc mismatch refused, early close skips Rejected, the finalise helper is used by the last step.

### Task 5: Payment safety

- **Repair tools:** `pay_recalc_wages`, `pay_round_amounts` and `pay_worker_edit_day(s)` skip rows with `payment_ref` or `payroll_check`, and write a Fix-log entry (kind `edited`).
- **Retired:** `pay_fix_duplicates` and `pay_submit` → an error pointing to the payroll check / Pay workers.
- **Sends:**
  - the conditional stamp `UPDATE … SET payment_ref=%s WHERE name IN %s AND IFNULL(payment_ref,'')=''`
  - if the affected rows ≠ the selected rows, `frappe.db.rollback(save_point=…)` and refuse with "someone else is sending"
  - also `GET_LOCK('wmpay-'+emp, 5)`
- **Cancel / purge / orphan repair:** cancel the Additional Salary first, then free the rows, in one savepoint. Refuse while a Salary Detail (draft or submitted) holds it.
- **`on_salary_slip_submit`:**
  - only Unpaid → Paid
  - compare the slip's Task Pay amount with the Additional Salary and with `SUM(rows)`
  - on a mismatch, log a `Work Management Payroll Check Fix` (kind `slip mismatch`) and do not stamp
- **Sends** require `company == DEFAULT_COMPANY`, not Suspended, and work_date ≤ relieving_date and ≥ date_of_joining. Rows excluded by `TW_ONLY` are listed in `skipped` with the reason.
- **Top-up re-send:** assert the re-sent rows ⊇ the released rows, or roll back.
- **Tests:** each, structural plus fake-frappe for the slip check.

### Task 6: Clearing section (backend)

- **Fix log `kind` options** gain: `acknowledged`, `edited`, `slip mismatch`. New fields: `issue` (Data), `row_hash` (Data).
- **Nested `wmi_issues(f, t, farm)`** returns a list of `{code, cls (block/ack/info), owner (farm|HR|GM), row, doc, employee, work_date, farm, amount, detail}` for the codes in spec §1. Detection SQL is ported from `pay_discrepancies`, scoped to dates.
- **Acknowledgement:** an issue is acknowledged when the Fix log holds `kind=acknowledged, issue=code, kept_row=row` with `row_hash` equal to the current hash of (qty, amount, work_date, employee).
- **Actions:**
  - `chk_issues` (counts + rows, FM-scoped)
  - `chk_ack` (code, rows[], reason; role must match the owner)
  - `chk_zero_row` (blocking kinds whose fix is zeroing: left_but_earning, off_crew, absent/ghost optional), logged
  - `chk_recompute_row` (rate_mismatch)
- **Gates:** farm approve, HR approve and GM approve refuse per spec §1 (each stage blocked only by issues it or earlier can clear). HR and GM may ack or fix during Farm Review.
- **Tests:** classification table, ack invalidated by a row change, the gates per stage.

### Task 7: Duplicate view (backend)

- **Keeper:** paid → in-run → recorded-first (assignment creation, then actuals creation), and never a backdated copy (assignment creation − from_date > max_backdate_days) while another exists.
- **`chk_dup_groups`:** groups by the sorted tuple of assignments, with workers × days.
- **`chk_dup_group_fix`:** keep the copies on assignment X, zero the rest, skipping paid and in-run copies.
- **`chk_dup_detail` (employee, date) returns:**
  - the worker
  - attendance and scans (with device)
  - each copy's full facts (assignment creator/created, window, actuals entered, approvers, team leader, qty, hours, rate, amount, payment)
  - the plan effect of zeroing each copy
  - pay basis (output/day)
  - the surrounding ±3 days
- **`chk_fix_dup`** takes `keep_row` (zero all others) as well as `zero_row`.
- **Tests:** keeper order including the real backdated case, the group fix skips paid copies, the detail keys.

### Task 8: Clearing UI

`work-payment.js`, in the check detail:
- an Issues panel with a counts strip and a section per kind
- per-row actions: Acknowledge (with reason), Zero, Recompute, Open
- duplicate groups with "Keep assignment X"
- a duplicate detail modal laid out as in the mockup
- a stand-ins note

`work-actuals.js`:
- a `qty_reason` prompt (an in-page field, not `window.prompt`) when the server answers `needs_qty_reason`
- the override_reason field for System Manager

**Tests:** the existing screen tests (action names exist, no `window.prompt`, byte-identical JS).

### Task 9: Clean-up report

- `work_management/pay_integrity_report.py` `run(out_path=None) -> path`: an xlsx with the 8 sheets from spec §4. Read-only, using openpyxl (bundled with frappe).
- **Test:** with a fake frappe, the sheets are created with headers.

### Task 10: Team-leader seed, e2e, review

- `work_management/patches/v1_0/note_team_leaders_required.py` is not needed. Instead, `scripts/seed_team_leaders.py` (a bench execute helper) loads the 4 Nov sheet list into `Work Management Team Leader` (idempotent).
- **e2e on webstore.localhost as the real users:**
  - the lock-down doesn't block normal work
  - the quantity cap
  - stand-ins
  - issues cleared to Approved
  - the group fix
  - the detail view screenshot
- A whole-branch review on the most capable model, and one fix pass.
