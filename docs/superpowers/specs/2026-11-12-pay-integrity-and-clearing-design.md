# Pay integrity: validations across the app, and clearing every issue in the payroll check

Date: 2026-11-12. Asked for by james@ after the payroll-check work
(`2026-11-12-payroll-check-and-duplicate-guard-design.md`, branch `feature/payroll-check`).

The user asked for a quality check of the whole app "as it's in use to pay workers", and for
an in-depth duplicates view plus discrepancies in the payroll check, so that "one should
be able to clear out all issues from this section before sending to payroll". They chose
to design everything before building anything.

This document builds on the payroll-check design. Where the two disagree, this one wins.

## Why: what the review found

Four independent read-only reviews were run on 2026-11-12: plans and assignments,
actuals, payment and payroll, and a data audit of that day's live data loaded locally.

### In the data (live as of 2026-11-12)

| Finding | Size | KES |
|---|---|---|
| Same worker, same day, paid on two records, all within the same payment document | 446 days | 171,520 paid |
| Duplicates not yet paid | 408 days | 141,695 queued |
| Rows marked paid with a `payment_ref`, but no line in that payment covers them (the stamp bug; probably underpaid) | 155 rows, 75 payments | 53,406 |
| Quantity more than 2× the daily target (e.g. 88 against a target of 8, paid 4,257) | 17 rows, 6 paid | ~71,000 above target |
| Paid or confirmed on an Absent day, or with no scan and no Present attendance (from 7 Sep) | 119 rows | ~29,500 paid |
| Work dated after the employee's relieving date | 49 rows | 16,000 (unpaid) |
| Confirmed with no FM or HR approver recorded (since 1 Oct) | 161 records | 2.56M |
| The same person took both the HR and GM steps | 529 records | 1.98M |
| Self-approval (the person who entered a record also approved it) | 6 records | 148,077 |
| Assignment created more than 7 days after it started | 229 | 1.45M confirmed |
| Two live payments for one worker over overlapping periods | 42 pairs, 11 over the same days | — |
| Amount ≠ quantity × rate (more than 5 KES) | 22 rows | 130,375 |

All approval stages are switched on in live Settings. The GM-only records therefore came
through a path that does not record the earlier steps: the desk workflow buttons, an early
close, or the step being taken on the desk.

The audit SQL is kept in the session scratchpad; the builder re-derives it from the
invariants in §4.

### In the code: about 40 gaps, in five groups

**1. Who can act**
- No role or farm check on:
  - the rate tools (`rates.py`: apply_wage, recalc, classify, sync_*, backfill, revert_periods)
  - about 15 payment writes (withdraw, purge_queue, edit_day(s), fix_*, recalc_wages, round_amounts, release_inactive, fix_orphan_refs)
  - `wm_payroll` (migrate_state, backfill_fields) and `wm_payroll_recompute`
  - `act_submit` (no enter_work check, and the farm is not checked against the assignment's farm)
  - edit-in-place (`edit_doc`)
  - `a_substitute`
  - `a_reject`
- `a_add_crew` and `a_release` accept a farm manager of any farm.
- Every endpoint accepts GET, which skips the CSRF check.

**2. Amount sanity**
- No per-cell quantity cap.
- The plan-target cap ignores records waiting for the farm manager, and approval never re-checks it.
- A plan is priced at today's Task rate, not the rate in force on its dates.
- Desk and REST saves never recompute `amount`.
- A Task rate edited on the desk has no gate and no sanity check.

**3. Approval integrity**
- Nothing stops self-approval, or one person taking two steps.
- `edit_doc` can change amounts after approval without resetting the approvals.
- Early close confirms Draft and Rejected records.
- With steps switched off, a record can reach CONFIRMED at docstatus 0.
- The desk path does not record approvers.

**4. Dates and people**
- Work can be dated in the future.
- A worker's status, relieving date and joining date are not checked.
- Release, left and substitute dates are not validated.
- `a_submit` accepts a plan that is not Approved, or is Closed.
- The new backdate guard is skipped when any `assignment` value is passed.
- A plan's to_date can be earlier than its from_date.
- A crew can be rewritten while the assignment is at Pending HR or Pending GM, without the FM seeing it.

**5. Payment safety**
- The repair tools change rows that are already in a sent payment, so those days are paid twice.
- There is no lock on concurrent sends.
- Cancel and purge free rows before (or without) cancelling the Additional Salary.
- Slip submit:
  - can mark a Cancelled run Paid
  - never compares the slip amount with the Additional Salary or the rows
- Company, Suspended status and joining date are not checked when sending.
- A worker whose type changed is silently dropped.
- A top-up re-send can drop rows.

## Goals

1. **No path in the app can pay a worker-day that is wrong without someone deciding so on
   the record.** "Wrong" means duplicated, mistyped, unapproved, on a day the worker was
   not there, or after they left.
2. **Every issue in a set of dates is found and cleared inside the payroll check before
   those dates go to payroll.** Each issue is either fixed, or acknowledged by the right
   person with a reason.
3. **Every write is done by someone allowed to do it, on a farm they are allowed to act
   on, and is logged.**
4. **The money already wrong is put in front of management as a list to decide on.** The
   system changes none of it automatically.

## Non-goals

- Recovering overpaid money automatically (decided earlier: record only).
- Redesigning the approval chain. The stages and roles stay as configured in Settings.
- Rewriting the screens beyond what the clearing section needs.

## Anti-goals

- **A wall of warnings that people learn to click through.** A blocking issue is fixed,
  not dismissed. An acknowledgeable issue needs a named person and a reason, and the
  acknowledgement shows in the audit log.
- **Deploying the lock-down without seeding roles**, so that real users are locked out on
  payroll day.
- **Changing paid history.** Rows already paid are never zeroed, re-priced or unstamped by
  a tool.

## Decisions so far (the user's)

- **One worker, one day, one task.** There is no splitting. A move between assignments
  keeps the old days on the old assignment. (From the payroll-check design.)
- **Payroll check flow:** HR picks the dates → each FM approves their own farm → HR → GM →
  HR sends. A check covers all farms. Late work goes in a top-up check.
- **Duplicates: suggest the copy recorded first** (the earliest assignment created, then
  the earliest actuals entered). Backdated copies are flagged and never suggested. An
  already-paid copy is always kept.
- **The duplicate view shows as much as possible for judgment:**
  - per copy: activity, block, assignment dates, who created it and when, the worker's
    window on the crew, who entered the actuals and when, every approver, the team leader,
    quantity, hours, rate, amount, and payment state
  - the worker's attendance and scans that day
  - the days around the duplicate
- **Design everything before building.**

## 1. The clearing section of the payroll check

The check's detail screen gains an **Issues** area. It replaces the separate "Duplicate
days" and "Unfinished records" lists with one list, grouped by kind. A farm manager sees
their own farm's issues; HR and the GM see all of them. Each kind is one of:

- **Block**: must be fixed before that farm (or HR, for issues that cross farms) can approve.
- **Acknowledge**: the named role confirms it with a reason; the acknowledgement is logged.
- **Info**: shown with a count, never blocks.

| Issue kind (code) | Class | Who clears it | How it is cleared |
|---|---|---|---|
| Duplicate day (`dup_day`) | Block | FM (same farm) / HR (across farms) | Keep one copy and zero the rest (§2) |
| Unfinished record (`unfinished`): Draft / Rejected / Pending with work in the dates | Block | FM | Finish and approve it, remind the clerk, or delete a rejected record (logged) |
| Quantity above 3× the daily target (`qty_outlier_hard`) | Block | FM | Correct the quantity (re-approval, §3.3) |
| Amount ≠ quantity × rate (`rate_mismatch`) | Block | HR | Recompute the amount (logged), or correct the rate |
| Work dated after the relieving date (`left_but_earning`) | Block | HR | Zero the row (logged) |
| Work outside the worker's window on the crew (`off_crew`) | Block | FM | Zero the row, or correct the crew dates |
| Quantity 2–3× the daily target (`qty_outlier`) | Acknowledge | FM | Reason |
| Paid on an Absent day (`absent_paid`) | Acknowledge | FM | Reason, or zero the row |
| No scan and no Present attendance (`ghost_days`) | Acknowledge | FM | Reason, or zero the row |
<!-- ghost_days stays on for every farm: scan coverage of confirmed work-days 1 Oct–10 Nov is Endebess 98.1%, Lokitela 99.9%, Saboti 100%, Vale 99.8% (checked 2026-11-12), so it will not flood the FMs. -->
| Approved leave or off day worked (`leave_paid`, `off_paid`) | Acknowledge | FM | Reason, or zero the row |
| Record with a skipped approval step, or one person on two steps (`approval_gap`) | Acknowledge | GM | Reason |
| Self-approved record (`self_approved`) | Acknowledge | GM, who must not be the self-approver | Reason |
| Backdated assignment, more than 7 days (`backdated`) | Acknowledge | GM | Reason |
| Entered more than 14 days after the work (`late_entry`) | Acknowledge | FM | Reason |
| Two farms in one day (`multi_farm_day`) | Info | — | Covered by the duplicate rule when both copies are payable |
| Long day / short day / hours ≠ quantity | Info | — | Shown |

Rules:

- **Detection reuses the existing `pay_discrepancies` logic** (the `disc_*` categories and
  their Settings switches), run over the check's dates. The new kinds are added beside them.
  - A Settings switch that turns a kind off turns it off here too.
  - A **Block** kind cannot be switched to anything weaker than Acknowledge. That is
    builder's call: a site can soften a block, never silence it.
- **An acknowledgement is stored per issue and row** in the existing Fix log. Its new kind
  is `acknowledged`, with the issue code, who, when and the reason. A row acknowledged once
  stays acknowledged if the check is sent back, unless the row itself changes; then the
  acknowledgement is dropped.
- **Approval gates.** A stage is blocked only by issues that stage, or an earlier one, can
  clear. (Builder's call, settled after review.)
  - Farm approval is refused while the farm has an open FM-cleared Block issue or an
    un-acknowledged FM issue.
  - HR approval is refused while any FM issue is open, or any HR-cleared issue
    (`rate_mismatch`, `left_but_earning`, cross-farm duplicates) is open.
  - The GM step needs every GM issue (`approval_gap`, `self_approved`, `backdated`)
    acknowledged.
  - HR and the GM may clear their own issues while the check is still at Farm Review, so
    work runs in parallel.
- **A counts strip** across the top shows, per farm and per kind: open, cleared, and KES
  at stake.
- **Every fix and acknowledgement goes to the Fix log**, so the check's audit history is
  complete.

## 2. The duplicate view, in depth

As agreed with the user, plus the builder's additions marked (B).

**Groups.** Duplicates are grouped by the pair (or set) of assignments behind them, for
example "WMA-828630 and WMA-413193: 23 workers × 4 days". (B)
- One decision applies to the whole group: keep the copies on assignment X. A single
  worker-day can still be opened and decided on its own.
- **Why:** the live pattern is whole crews on two assignments (Endebess, September: 382
  days from one overlap).

**Opening one worker-day** shows:
- **The worker:** number, designation, employment type, farm.
- **That day:** attendance status, the first and last scan, and the device or farm of the
  scan where Checkin carries it. (B)
- **Recorded vs possible:** hours and quantity recorded against the length of the day.
  KES recorded against one day's pay.
- **One card per copy:**
  - activity and block
  - the assignment: its dates, who created it and when, and a ⚑ if it was backdated
  - the worker's start and left dates on that crew
  - the actuals record: who entered it and when, and a ⚑ if entered late
  - every approver, with a ⚑ for self-approval or a skipped step
  - team leader
  - quantity, hours, rate, amount
  - payment state: paid / in run X / free
  - the effect on the plan of zeroing this copy, e.g. "plan delivered 960 of 1,000 →
    952" (B)
  - whether the activity is paid by output or by the day (B)
- **A strip of the worker's days** around the date, showing which record holds each day.

**The suggestion is the copy recorded first.**
- Rank by assignment creation time, then actuals creation time.
- A copy whose assignment was backdated more than `max_backdate_days` is never suggested
  while another copy exists.
- A paid copy is always kept.
- A copy in an unpaid run blocks until HR withdraws that run.

**Deciding:**
- "Keep this one", on any copy.
- A reason from a list (entered twice by mistake / backdated assignment / worker moved
  mid-day / other) plus a note.
- The other copies are zeroed and logged; the log keeps the original quantity and amount.

## 3. Validations in the app

### 3.1 Who can act (lock-down)

- **One capability check at the top of every endpoint that writes,** from Settings
  `capabilities` (which already exist: edit_master_plan, set_rates, send_payment,
  enter_work, handle_payments). New capabilities:
  - **`repair_payments`**: purge_queue, fix_*, recalc_wages, round_amounts,
    fix_orphan_refs, release_inactive, and the `wm_payroll` / `wm_payroll_recompute` writes.
    Default: System Manager plus HOD HR. The GM approves and does not repair.
    (Builder's call, settled after review.)
  - **`edit_pending_actuals`**: edit-in-place by the approver of the current step only.
- **Farm scope on every write.** The farm is taken from the record (assignment, actuals,
  row, or the employee's farm), never from a request parameter, and must be in the
  caller's FARMS.
  - Fixes `a_add_crew`, `a_release`, `a_substitute` (both copies), `act_submit`,
    `pay_worker_edit_day(s)`, and the sends.
- **POST only for writes.**
  - The `wm_*` endpoints refuse a writing action unless `frappe.request.method == "POST"`.
  - Reads stay GET.
  - The screens already POST their writes. The builder verifies every `call(..., true)`.
- **Rates.**
  - Every `rates.py` action that writes with `dry_run=0` requires `set_rates`.
  - `Task.custom_rate` edited on the desk requires `set_rates`, and rate × daily target
    must be within ±2% of a wage tier unless a reason is given.
  - HR Manager loses desk write on Work Task Rate.
- **`a_reject` is gated** like the approve steps.
- **`wm_payroll migrate_state`** is System Manager only. It never targets Paid or
  Cancelled, and never touches a payment that has an Additional Salary.

### 3.2 Amount sanity

- **Per-cell quantity cap** against the plan's `daily_target`:
  - above 2×: saved, flagged on the row
    (`qty_flag`), and shown as `qty_outlier` in the check
  - above 3×: refused
  - for hour-measured tasks: refused above 24
  - **Builder's call:** the thresholds are Settings fields, default 2 and 3.
- **No future work.** `work_date > today` is refused at save.
- **The plan-target cap counts Pending Farm Manager**, and is re-run at FM, HR and GM
  approval and at early close.
- **Desk and REST saves recompute.** The validate hook re-derives each row's `amount` from
  quantity × rate × count_in_payroll, refuses negative quantities and dates outside the
  record, and recomputes the parent totals. It also applies the B2 window rule and the
  payroll-check lock, which closes the known gap.
- **Rate by date.**
  - A new plan is priced from the Work Task Rate period that covers its `from_date`.
  - A plan that straddles a rate change is refused, with a message to split it.
  - A plan whose UOM differs from its master-plan line is refused.
  - Existing plans are not re-priced.

### 3.3 Approval integrity

- **No self-approval.** No step may be taken by the person who entered the record, or by
  the person who took the previous step. This covers planner, assigner and actuals
  approvals and the payroll check (HR ≠ GM, already built).
  - **Stand-ins (user's decision).** Settings holds a named stand-in list per step: FM per
    farm, HR, GM. When the usual approver entered the record or took the previous step, a
    listed stand-in takes the step. The rule itself stays hard. The user names the people
    at go-live.
  - Break-glass: a System Manager may still override, with a logged reason. The override
    is raised as `approval_gap` in the check.
- **Edit-in-place.**
  - Only by the holder of the current step (and the farm, at the FM step).
  - Refused unless `edit_doc`'s assignment equals `assignment`.
  - If the amount changes after any approval, the record goes back to Pending Farm
    Manager, and the old and new totals are logged.
- **Early close** never revives Rejected records. It confirms a Draft only when the GM
  ticks it, and each confirmed record passes the guard, the cap and the attendance gate.
- **The step that ends the chain finalises**, whichever step that is: docstatus 1, the
  fulfilment roll-up, and auto-release, as the GM step does today. Settings refuses a
  chain with every approval step off.
- **The desk path records approvers.** A `Work Management Actuals` `on_update` hook writes
  `fm/hr/gm_approved_by` and the timestamp when the workflow state changes through the
  desk, and applies the self-approval rule there too.

### 3.4 Dates and people

- **Every path that puts a worker on work** requires Employee status Active. **Recording
  work** requires work_date ≤ relieving_date, whatever the current status. Together with
  the following, both require:
  - work_date between `date_of_joining` and `relieving_date`
  - farm = the plan's farm
  - the task-worker match
  - the attendance gate (with a logged override)
- **The backdate guard** runs on every new or resubmitted assignment, whatever
  `assignment` value is passed. Edits to an assignment already pending are exempt only when
  its dates are unchanged.
- **Release, left and substitute dates** must satisfy: worker's start ≤ left_date ≤
  min(today, to_date), left_date ≥ the last recorded work date, and replacement start >
  outgoing left_date.
- **`a_submit`** requires the plan to be Approved, not Closed, with no other live
  assignment, and on a farm in FARMS.
- **Plans** refuse to_date < from_date, and backdating beyond `max_backdate_days`
  (GM with a reason).
- **Crew edits while the assignment is pending:**
  - only by the approver of the current step
  - any crew change sends the assignment back to Pending Farm Manager
  - always validated against `d.planner_request`

### 3.5 Payment safety

- **Repair tools** (`pay_fix_duplicates`, `pay_recalc_wages`, `pay_round_amounts`,
  `pay_worker_edit_day(s)`) skip rows with a `payment_ref` or a `payroll_check`, and write
  to the Fix log. `pay_fix_duplicates` is retired in favour of the check.
- **Legacy `pay_submit`** is retired: refused with a pointer to the Pay workers tab.
- **Concurrent sends.**
  - A per-employee lock while a send runs.
  - Rows are stamped with
    `UPDATE … SET payment_ref = %s WHERE name IN … AND IFNULL(payment_ref,'') = ''`.
  - If the affected count differs from the rows selected, the send rolls back.
- **Cancel, purge and orphan repair** cancel the Additional Salary first, then free the
  rows, in one savepoint. They refuse while a Salary Detail (draft or submitted) holds the
  Additional Salary.
- **Slip submit:**
  - moves only Unpaid → Paid
  - compares the slip's Task Pay line with the Additional Salary amount and with
    `SUM(rows.amount)` for the run, and logs a mismatch to an error log (the run stays
    Unpaid and HR is shown it) instead of stamping paid
- **Sends** require `company == DEFAULT_COMPANY` and every work_date between joining and
  relieving.
  - Status is NOT required to be Active: a leaver's valid days before their relieving date
    must still be paid. (Builder's call, settled after review.)
  - Status Suspended blocks a send. Status Left or Inactive is allowed for days on or
    before the relieving date.
- **A change of employment type** never silently drops rows. Rows the current type would
  exclude are listed in `skipped` with the reason.
- **A top-up re-send** asserts that the re-sent rows include every released row, or rolls
  back.

## 4. Data clean-up (prepared, not applied)

A one-off report, `work_management.pay_integrity_report.run()`. It is read-only: it builds
an xlsx and writes nothing. Its sheets:

1. **Marked paid, not paid:** the 155 rows, with their payment, its lines, and the amount
   probably owed.
2. **Paid twice:** the 446 days, with both payments (also back-filled into the Fix log).
3. **Overlapping payments:** the 42 pairs, and the 11 over the same days.
4. **Quantity outliers paid.**
5. **Paid on Absent / no-scan days.**
6. **After relieving date.**
7. **Approval gaps:** GM-only, the same person on HR and GM, and self-approved; per
   record, with KES.
8. **Backdated assignments** with confirmed KES.

Management decides each sheet. Applying any correction (for example un-stamping the 155
rows so they can be paid) is a separate, explicit request.

## 5. Order of work and go-live

**Timing (user's decision): lock-down first, before the 20 Nov payroll.** These ship with
the payroll check before that payroll:
- the role, farm and POST lock-down (§3.1)
- the quantity cap and the no-future-work rule (§3.2)
- the repair-tool exclusion of sent and checked rows (§3.5)

Everything else ships after the 20 Nov payroll, in the order below.

The build goes in this order, so each piece ships safely:

1. **Lock-down (§3.1), seeding capabilities first.**
   - A patch adds the new capabilities to Settings with the roles live uses today
     (`repair_payments`: HOD HR and System Manager).
   - Checked 2026-11-12: none of live's 249 enabled Server Scripts calls a `wm_*`
     endpoint, so POST-only breaks no script. The weekly digests only read.
   - Before deploy, a report lists every live user who would lose an action they used in
     the last 60 days (from Version and Comment logs, where available).
2. Amount sanity (§3.2) and dates and people (§3.4).
3. Approval integrity (§3.3), including the desk hook.
4. Payment safety (§3.5).
5. The clearing section (§1) and the duplicate view (§2).
6. The clean-up report (§4), which can be run any time.

Testing:
- unit tests per rule
- end-to-end on webstore.localhost with the fresh live slice, acting as the real users
  (clerk, FM per farm, HR hro@, GM koskey@ / peter@)
- re-running the data audit's invariants after the fixes, to show they hold for new
  entries

## Left to the builder

- Field and doctype names: `qty_flag`, the acknowledgement kind in the Fix log, any new
  Settings fields.
- How detection code is shared between `pay_discrepancies` and the check.
- The layout of the Issues area within the existing Payment screen patterns.
- Whether the desk hook lives in `duplicate_guard.py` (renamed) or a new module.
