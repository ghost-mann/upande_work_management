# Payroll check and duplicate-day guard

Date: 2026-11-12. Asked for by james@ after workers on Kaitet live were found to be
assigned to, and paid for, the same day more than once.

## Why

The figures below come from live (kaitet-group.upande.com) on 2026-11-12. They are
payable rows (amount > 0, count_in_payroll = 1) on non-rejected actuals.

| | Worker-days | Excess KES |
|---|---|---|
| Same worker, same task, same date, on two or more actuals | 618 | 235,827 |
| Same worker, different tasks, same date, each at full pay | 344 | 119,872 |
| Already paid twice | 446 | 171,520 |
| Open period (21 Oct onward), unpaid | 70 days, 62 workers | 27,098 |

Endebess has 790 of the 962 duplicate days. The duplicates are still being created: for
example, robert barasa (401151) was paid on both TASK-00213 and TASK-00176 on 2, 3 and
4 Nov.

**How the duplicates get past the current guard.** `allow_split_day` is OFF on live, so the
double-allocation guard in `assigner.py` (around line 529) is active. It has three holes:

1. **It only counts a worker as busy while marked `Active` on the other assignment.** Since
   1 Oct, 238 of the duplicate rows had the worker marked `Left` on the other assignment.
   When a worker is released from assignment A, their actuals on A stay. They are then put
   on assignment B over the same dates, and those days are paid a second time.
2. **Assignments can be backdated with no limit.** For example, WMA-863710 was created on
   23 Oct but covers 28 Sep–11 Oct, the same window as WMA-412796, by the same clerk.
3. **Neither the actuals screen nor any approval checks the worker's other actuals for the
   same date.**

Separately, nothing stands between HR reviewing the Payment screen and HR sending to
payroll. No farm manager or GM confirms the period being paid.

There is also a known bug from the 2026-11-02 audit, still unfixed:
`_stamp_actuals_paid_for_payment` (`api/payment.py` ~3634) stamps `paid=1` and
`payment_ref` on every confirmed unpaid row an employee has in the payment period, not
only on the rows that payment carried. Actuals approved after a run is built are
therefore marked Paid without the worker being paid.

## Goals

1. Stop new double payments where they are entered, with a hard rule.
2. Give management one place to find and fix the duplicates already in the system before
   they are paid.
3. Allow no payment to payroll until a set of dates has been audited farm by farm and
   approved by HR and the GM.
4. Keep a permanent audit record of what was found, what was fixed, and what was already
   paid twice.

## Non-goals

- Recovering money already overpaid. Rows paid twice are **recorded in the audit history
  only**; management decides outside the system (user's decision).
- Changing how per-record actuals approval (FM → HR → GM) works. It stays as it is for
  now and may be trimmed later, once the payroll check is proven.
- Changing wages, rates, or how amounts are calculated.

## Anti-goals (things that would make this a failure even if it works)

- A rule that a clerk can click past. The duplicate rule has no override.
- Freezing payroll on deploy day with no way through.
- A second screen everyone has to learn. The check lives on the Payment screen people
  already use.

## Decisions (the user's)

### 1. One worker, one day, one task

- A worker may have **one payable actuals row per calendar date**, across every task,
  assignment, and farm. There is no splitting of a day between tasks.
- `allow_split_day` stays off and is removed from the Settings form, so nobody can turn
  it back on. The split-day code stays in the codebase but is never used.

### 2. When a worker moves between assignments, the old assignment keeps the days already worked

- The cut-over date is the first day the worker is on the new assignment B.
- Assignment A keeps every day before the cut-over date. Releasing the worker on A sets
  `left_date` to the day before cut-over. After that, A's actuals cannot record the worker
  on or after the cut-over date.
- Assignment B cannot reach back. Its actuals cannot record the worker on any date while
  they were still on A, even when B's `from_date` is earlier.
- When a duplicate is found in existing data, the copy to keep is the one on the
  assignment the worker was on first. The copy on the newer assignment is the one
  zeroed. (This is the builder's reading of the user's rule. "First" means the
  assignment whose worker row started earlier; on a tie, the assignment created
  earlier.)

### 3. The payroll check replaces the weekly sign-off

Payment runs cover whatever dates HR chooses, so the gate is tied to those dates, not to
calendar weeks. The flow follows the Payment screen people already use:

1. **HR picks the dates** on the Payment screen, as now, and presses **Create payroll
   check** instead of sending.
2. **The system builds the check:** every worker-day in those dates, with problems
   flagged:
   - duplicate days
   - records still in Draft, Rejected, or Pending
   - the attendance and leave clashes the screen already detects (`pay_discrepancies` /
     `pay_absent_conflicts`)
3. **Each Farm Manager audits their own farm's part of the check,** fixes what is flagged,
   and approves their farm.
4. **HR** does the cross-farm pass (clashes between farms, anything left) and approves.
5. **The GM** approves.
6. **HR sends to payroll.** The Send button works only on a GM-approved check, and only
   for exactly the workers and days in it.

- Any reviewer may **send the check back** with a reason.
- The duplicate list and the payroll check are the same thing (user: "fold them together").
  There is no separate audit page.

### 3a. Scope and late entries (user's answers after review)

- **One check covers all farms** for its dates. HR doesn't pick farms. Only one
  non-cancelled check may exist over any given date; C2 compares dates only.
- **Late entries for dates already Sent are allowed**, and are flagged as *late*. They
  are not payable until HR creates a **top-up check** that covers exactly those late
  rows (same dates, `is_top_up = 1`, frozen to the late rows only). It goes through
  FM → HR → GM like any other check before it is sent. C2 exempts top-up checks from the
  overlap rule, but a row can belong to only one check, ever.

### 4. The unreleased week sign-off build (branch `feature/farm-team-leaders`, uncommitted)

| Part | Fate |
|---|---|
| Week sign-off screen, `Work Management Week Signoff` doctype, `week_signoff_required` switch, `SIGNED_ONLY` SQL in `wm_payment` | **Dropped**, replaced by the payroll check |
| Draft and rejected clean-up (notify clerk, complete it myself, delete rejected into `Work Management Deleted Actuals`) | **Moved** into the FM's part of the payroll check |
| Per-farm History tab (employee, activity, calendar, CSV) | **Kept** as built |
| Farm team leaders | **Unaffected**, ships on its own |

### 5. Already-paid duplicates

These are recorded in the audit history with the worker, date, both records, the amount
paid twice, and the payment runs involved. The system takes no recovery action.

## The rules to enforce (complete list)

Codes are for the plan and the tests.

**At assignment (`wm_assigner`)**

- **A1.** A worker counts as busy on an assignment from their start on it up to their
  `left_date` (inclusive), whatever their current status. A `Left` worker still blocks the
  dates they were on.
- **A2.** An assignment's worker dates may not overlap that worker's dates on any other
  live assignment (Pending FM / Pending HR / Pending GM / Assigned), on any farm. This is
  refused, with no Settings switch.
- **A3.** Adding a worker to an existing assignment, extending its dates, or re-activating
  a Left worker runs A1–A2 again. Every path that changes worker rows or dates must hit
  the same check, not just the first save.
- **A4.** Backdating: an assignment, or a worker added to one, may not start more than
  `max_backdate_days` (new Setting, builder's call, default 7) before today, unless a GM or
  System Manager makes the change themselves and enters a reason, which is logged on the
  assignment. A clerk is refused and told to ask the GM. There is no pending-override
  state. (Builder's call.)

**At actuals (`wm_actuals`: save, submit, and each of FM / HR / GM approve)**

- **B1.** For each worker row with amount > 0 or quantity > 0 (a zeroed row has both at 0
  and is ignored), no other row for the same
  employee and `work_date` may exist on any actuals that is not Rejected, regardless of
  task, farm, or paid status. Refused, and the message names the other actuals,
  task, and farm.
- **B2.** The worker must be on this actuals' assignment on that date (between their start
  and `left_date`). This enforces decision 2.
- **B3.** B1–B2 are re-run at every approval step, because a record that was clean when
  saved can clash with one approved later.
- **B4.** The duplicate check ignores Rejected and deleted actuals. It includes Draft and
  Pending, so a draft blocks a second entry for the same day; the clerk must fix or
  delete the draft first.

**At payroll (`wm_payment`)**

- **C1.** No payment run (`pay_submit`, `pay_worker_submit`, `pay_bulk_submit`) can be sent
  unless it falls inside a GM-approved payroll check and covers only the worker-days that
  check froze.
- **C2.** A payroll check cannot be created over dates that overlap another non-cancelled,
  non-top-up check. A worker-day row can be frozen into one check only, ever, so a day
  can never be paid by two checks.
- **C3.** Approval is blocked at each stage while the check still holds an open duplicate
  or an unfinished record (Draft / Rejected / Pending) in its scope. An FM is blocked only
  by their own farm's items. HR and the GM are blocked by any item.
- **C4.** Fix the stamping bug: `_stamp_actuals_paid_for_payment` stamps only the
  `Work Actuals Employee` rows that the payment's lines actually carried. The run must
  record which rows it carried; see builder's calls.
- **C5.** While a check is in `Farm Review`, the normal per-record approvals (FM / HR / GM
  approve and reject) carry on, so Pending records can be cleared. Creating or editing
  actuals inside the check's dates is allowed only through the check's Problems panel.
  Once a farm is FM-approved, that farm's rows inside the dates are fully locked: no
  create, edit, approve, or reject. A late change means sending the check back, which
  unlocks the dates and returns the check to the FM stage. (Builder's call, settled
  after review.)

## The payroll check

**Doctype `Work Management Payroll Check`** (name is the builder's call)

- **Header:** `period_from`, `period_to`, `created_by`, `status`, totals (worker-days,
  amount, duplicates found, duplicates fixed, amount zeroed), `sent_back_reason`.
- **Child table, one row per farm in scope:** farm, FM status (Pending / Approved),
  approved_by, approved_at, and that farm's counts.
- **Frozen worker-days:** the set of `Work Actuals Employee` rows the check covers,
  stored on the check or in a child table. This is what C1 and C4 match against.
- **Statuses:** `Farm Review` → `HR Review` → `GM Review` → `Approved` → `Sent`, plus
  `Sent Back` and `Cancelled`.
  - It moves to `HR Review` when every farm in scope is FM-approved.
  - Sent Back returns it to `Farm Review` with every farm reset to Pending. The builder
    may reset only the farm concerned when the reason names one farm.

**The fix log, `Work Management Payroll Check Fix`** (one row per fix)

- **Fields:** check, employee, work_date, kept row and its actuals, zeroed row and its
  actuals, amount zeroed, who, when, reason, kind (duplicate / draft completed / rejected
  deleted / attendance).
- **Already-paid duplicates** found in or before the check's dates are written here with
  kind `paid twice`. They are recorded only, never zeroed.

**On the Payment screen**

- **HR:** a date picker, as now, then **Create payroll check**. The existing pay-week and
  `allow_day_range` rules decide which date spans are allowed.
- **Opening a check:**
  - the worker review sheet the screen already has, filtered to the check's rows
  - a **Problems** panel: duplicates (both rows side by side, the keeper pre-marked by
    decision 2, **Zero the other**, and a **Fix all on this farm** bulk action), drafts,
    rejected records, and attendance clashes
- **Who sees what:**
  - **FM:** their own farm, with Approve my farm and Send back.
  - **HR / GM:** every farm, with Approve and Send back. HR sees **Send to payroll** once
    the check is Approved.
- **Audit history tab:** every check, its fix log, and the paid-twice list with totals by
  farm and period. FMs see their own farm; HR, GM, and System Manager see all farms.

**Notifications** (builder's call on wording): email the FMs in scope when a check is
created; email HR when all farms have approved; email the GM at GM Review; email HR at
Approved; and email everyone earlier in the chain when it is sent back.

**Zeroing a duplicate** (builder's call, settled after review): set the zeroed row's
`actual_quantity` and `amount` to 0 and clear its review stamps, as `pay_fix_duplicates`
already does. The row is kept, so the record and its history stay intact. Quantity is
zeroed too, because a duplicated day also double-counts delivery against the plan. The
fix log keeps the original quantity and amount.

**Cross-farm duplicates** (builder's call): when the two copies are on different farms,
the item belongs to HR, not to either FM. It does not block either FM's approval, but it
does block HR approval.

## Clean-up of existing data

- **Before this period's payroll:** the first check, 21 Oct–20 Nov, surfaces the 70 open
  duplicate days. They are fixed through the check, so every fix is logged.
- **History:** a one-off script writes every past paid-twice day (446 days / 171,520 KES as
  of 2026-11-12) into the fix log as `paid twice`, so the audit history starts complete.
  It changes nothing else.
- **Rows paid once but duplicated by an unpaid copy** (the unpaid copy is in a past
  period): zero the unpaid copy, and log it.

## Testing

- **Unit tests** for every rule code (A1–A4, B1–B4, C1–C5) in the existing site-less
  suite, written in the mirror first and then run through `port_app.py`.
- **End-to-end on the local bench** (`webstore.localhost`, served on :8003):
  1. Refresh the live slice (`e2e/wm_live/extract.py` + `load.py --reset`) so it includes
     the October and November duplicates.
  2. Act as the real users (clerk, FM per farm, HR `hro@`, GM `koskey@`, password `admin`
     on the slice):
     - try to create each kind of duplicate and see it refused
     - create a check for 21 Oct–20 Nov
     - each FM fixes and approves
     - HR approves
     - GM approves
     - send to payroll
  3. Confirm only the frozen rows are stamped Paid (C4).
  4. Send back and confirm the dates unlock.
  5. Compare the duplicate counts against the live figures above.

## Go-live order (builder's call)

1. Deploy the rules (A, B) and the stamping fix (C4). These are safe on their own.
2. Run the history back-fill script.
3. Deploy the payroll check, with the C1 gate behind a Settings switch
   `payroll_check_required`, default OFF.
4. Run the first check for 21 Oct–20 Nov with HR, the FMs, and the GM.
5. Then switch the gate on. After that, no payroll goes out without a check.

## Left to the builder

- Exact doctype and field names, and how frozen rows are stored (child table vs. JSON).
- Whether existing helpers (`pay_fix_duplicates`, `pay_discrepancies`) are reused or
  replaced. `pay_fix_duplicates` keeps the earliest-created copy and skips paid groups.
  Its keeper rule must change to decision 2 (first assignment).
- Screen layout within the Payment page, following its existing patterns.
- How the week sign-off code is removed from the uncommitted branch, and whether the
  dropped doctypes are deleted or simply never shipped (they were never on live).
