# Missing work, part 2: enter directly, and approve every fix

Date: 2026-11-23 · Requested by james@ · Builds on
`2026-11-23-missing-work-design.md` (part 1, built on branch `feature/missing-work`)

## Why

Part 1 lists task workers who came in but have no actuals, and lets the farm
enter the work through the Enter Actuals grid or give a "no work" reason. Two
problems remain:

1. **The grid is often locked.** It refuses a new record when the assignment
   already has one in approval or confirmed ("This assignment already has an
   actuals record in progress"). It also sends a record to approval only once
   the plan's target is reached. A single forgotten worker-day fits neither.
2. **Nothing checks the fixes.** james@ wants every fix verified before it
   counts: the work entered for a missing day, and every "no work" reason.

## Decisions made with the user (2026-11-23)

- **Enter directly from Missing work.** The work for a missing day is typed on
  the Missing work row. It is not entered through the grid.
- **Everything goes through three steps:** farm manager → HR → GM. This
  covers work entered for a missing day and every "no work" reason.
- **Approvers act in a new tab inside Missing work.** The tabs are
  **To clear** (part 1) and **Waiting for approval**. Each has Approve and
  Send back, for whoever's turn it is.
- **Approach A:** work for a missing day is saved through the existing actuals
  save (`act_submit`) with a missing-day flag. It becomes its own small record
  that goes through the normal actuals approvals. B (half-unlocking the grid)
  and C (a second copy of the pay rules) were rejected.

## Later decisions (2026-11-23, after the builder check)

**The To clear tab becomes a monthly grid** (requested by james@): the same
attendance-sheet layout as the dashboard's Monthly attendance.
- **Rows:** every task worker on the farm (home farm, plus anyone on the
  farm's crews in the range), for the chosen period. Workers with open days
  sort first.
- **Columns:** the days of the period.
- **Cells:** P (present), ½ (half day), A (absent, in red), L (leave),
  · (off day or holiday), ? (no record). A cell with work recorded is
  underlined. The fix states are:
  - **missing:** a red ring, clickable;
  - **waiting for approval:** amber;
  - **"no work" approved:** a grey tick;
  - **HR asked to fix attendance:** a dashed amber.
- **Clicking a missing cell** opens a panel with part 1's actions for that
  worker and day: enter the quantity and send it for approval; add to a crew
  first if needed; or give a "no work" reason.
- **Clicking an A cell** offers "They did work: ask HR to correct the
  attendance". This creates the same On Duty Attendance Request that the
  Actuals "confirmed present" flow already creates (`wm_actuals` ~1904), in
  HR's queue. Once HR approves it the day is Present, and it becomes a
  missing day that the farm can enter work for. The Absent rule stays intact.
- **Bulk "no work":** tick several missing cells, then choose one reason.
  The summary card and the farm buttons from part 1 stay above the grid.

**The plan's quantity cap stays** (james@). A missing-day save that would
take the plan past its target is refused like any save. The farm then gives
a "no work" reason, or the GM raises the plan.

**The builder's calls** (the user can override these):
- **A missing-day record rejected from the normal Approvals tab** is deleted
  and logged, exactly as Send back does. The day returns to To clear, and it
  is never stuck.
- **"No work" reasons use a strict two-person rule.** Nobody approves their
  own reason, and the same person cannot take both the HR and the GM step. No
  override.
  - **Work records keep the existing actuals rules.** `wmg_step_err` allows
    the same person, with a logged note, when no stand-in is set.
- **One record per worker.** "Enter work for all N" sends a separate
  missing-day record for each worker, so a send back affects only that
  worker.
- **Reasons saved under part 1** start as Pending Farm Manager. There is no
  backfill, because part 1 is not live.
- **The sent-back reason for work** is read from the Work Management Deleted
  Actuals log entry, and shown on the day.

## Goals

- From the To clear tab, someone who may record work on the farm can enter a
  missing day's quantity for one worker and send it for approval. This works
  in one step even when the assignment's main record is locked.
- A worker who was on no crew is added to a crew for that day (part 1). The
  same row then asks for the quantity. There is no trip to the grid.
- Every fix waits in **Waiting for approval**, grouped by stage, until all
  three steps pass. Send back returns the day to To clear, with the reason
  shown.
- The payroll check treats a missing day as cleared only when its fix is
  fully approved.

## Non-goals

- No change to the normal grid, the normal Approvals tab, or how a main
  record is approved. Missing-day records also show in the normal Approvals
  tab, because they are ordinary actuals records.
- No new pay rules. The rate, the plan's quantity cap, one worker one day one
  task, the Absent rule and the presence checks all come from `act_submit` as
  they are.

## Anti-goals (this fails if)

- A missing-day record can be created for a day that is not missing, or for a
  worker who was not on that crew that day. That would be a back door around
  the grid's lock and around the duplicate guard.
- One person can push a fix through two steps alone: entering and approving
  it, or approving it at both HR and GM.
- A sent-back fix leaves the day stuck: not in To clear, and not payable.

## Data

**Work Management Actuals**: a new Check field, `missing_work_fix` ("Entered
for a missing day"), read-only. It is set only by the missing-day save.

**Work Missing Day Excuse** (part 1) gains a workflow:
- `status` (Select): Pending Farm Manager · Pending HR · Pending GM ·
  Approved · Sent back. The default is Pending Farm Manager.
- Who approved and when, at each step: `fm_by`/`fm_at`, `hr_by`/`hr_at`,
  `gm_by`/`gm_at`.
- Who sent it back, when and why: `sent_back_by`/`sent_back_at`/
  `sent_back_reason`.
- Marking a reason again for the same worker-day (after a send back) updates
  the same record and resets it to Pending Farm Manager. This is the part 1
  behaviour plus the reset.

## Rules

**Which days count as cleared** (the shared finder, `missing_work.find`):
- **Open, so shown in To clear:**
  - there are no actuals and no reason; or
  - the reason was sent back; or
  - the only actuals are in a missing-day record that was sent back. Such a
    record is deleted on send back; see "Sending work back" below.
- **Waiting, so shown in Waiting for approval and not in To clear:**
  - the day's only actuals are in a missing-day record that is not CONFIRMED
    yet; or
  - its reason is Pending.
- **Cleared:**
  - actuals in a normal record, at any state with docstatus < 2 (unchanged
    from part 1); or
  - a CONFIRMED missing-day record; or
  - an Approved reason.

**Entering work for a missing day** (`act_submit` with `missing_fix=1`; the
rows payload carries one or more `emp~date~qty` cells for ONE assignment):
- Each cell must be a day that `find` reports as open for that worker. Its
  crew (first crew) must be this assignment. If either fails, the save is
  refused with the worker and day named.
- Every existing `act_submit` validation runs. The flag lifts only two
  things:
  - the "already has an actuals record in progress" refusal, for this new
    record only;
  - the "target must be reached before submitting" rule.
- It creates a new Work Management Actuals record holding only those cells,
  with `missing_work_fix = 1`. It moves the record straight to the first
  approval stage (`STAGE_NEXT["actuals_submit"]`), as a normal submit does.
  The submit-role check stays as it is.
- Hourly tasks: the row asks for hours. The conversion for short days stays
  exactly as the grid does it, because it is the same save.

**Approving work** uses the existing `act_fm_approve` / `act_hr_approve` /
`act_gm_approve`, with their existing role, stand-in and no-self-approval
rules.

**Sending work back** is done from the Waiting tab, with a required reason.
The missing-day record is deleted through the existing `act_delete` path,
which logs it in Work Management Deleted Actuals. The reason is added to the
day as a note, so To clear shows "Sent back by X: reason". The day becomes
open again. Deleting, rather than rejecting, means the one-worker-one-day
guard never meets a leftover rejected copy.

**Approving a reason** (new `wm_missing_work` actions `mw_approve`,
`mw_send_back`):
- The steps follow the Settings chain for Actuals, so a step that is switched
  off there is skipped here too.
- Who may take each step:
  - **Farm manager step:** that farm's farm manager role, or the GM.
  - **HR step:** an HR head role.
  - **GM step:** the GM.
  - This matches who may approve actuals at that step, stand-ins included,
    using the same Settings `approval_stand_ins` rows the actuals approvals
    use.
- Nobody approves a reason they marked.
- The same person may not take both the HR and the GM step.
- Send back needs a reason, and any step-holder may do it. Approve and Send
  back both accept many names at once (bulk).

## Screens

**Missing work → To clear** (part 1, changed):
- **On-crew row:** "Enter work" opens an inline panel with "[ qty ] {uom} on
  {task} · Send for approval". The crew rows need `uom`, which `find` returns
  from the planner. "Enter work for all N" opens one panel listing those
  workers with a quantity box each, and sends one record for the crew and day.
- **No-crew row:** "Add to a crew" (part 1) is followed by the same quantity
  panel instead of jumping to the grid.
- **No work:** unchanged, but the toast says "Sent for approval".
- **Sent-back day:** shows a "Sent back by X: reason" line.

**Missing work → Waiting for approval** (new):
- Two sections:
  - **Work entered:** worker, day, task, qty, KES, stage, entered by.
  - **No work given:** worker, day, reason, note, stage, marked by.
- Each section is grouped by stage: with the farm manager, with HR, with the
  GM. The group whose turn is the viewer's comes first and is marked
  "Your turn".
- **Per row:** Approve, and Send back (which asks for a reason inline).
- **Per group:** tick-all, plus "Approve ticked".
- Rows the viewer may not act on show their stage only.
- The tab label shows a count of the items waiting on the viewer.
- Scope: the viewer's farms, as in To clear. HR and the GM see every farm.

## Payroll check

- **`missing_work` issue (block, farm):** raised for open days, as in part 1,
  and now also for waiting reasons, with the detail "reason waiting for
  {stage}". Waiting work is already caught by the check's existing
  "unfinished" rule, because a record not yet CONFIRMED is unfinished. The
  farm cannot approve its part until every fix in its dates is fully
  approved.
- **Stamping** on farm approval: only Approved reasons are stamped, as are
  Approved reasons whose day has no actuals (part 1 rule).
- **The "No work given" summary** counts Approved reasons only.
- **HR and GM gates:** unchanged from part 1. `missing_work` does not hold
  them.

## Reminders

These are unchanged in scope. In the 07:30 email the line for a waiting day
says "waiting for approval", so it is not listed as missing. The email lists
open days only.

## Testing (the user asked for "lots of tests, end to end")

- Site-less unit and wiring tests for every rule above, in the repo's style.
- A scripted end-to-end run on webstore.localhost through real browsers,
  logging in as four real users. The script is kept in the repo as
  `scripts/e2e_missing_work.py` so it can be rerun.
  - The users:
    - a clerk: someone who records work but is not a farm manager;
    - Vale's farm manager (kibett);
    - HR (hro@);
    - the GM (koskey@).
  - Scenarios, each asserting what every screen shows afterwards:
    1. **On-crew day:** the clerk enters work → FM → HR → GM approve → the day
       is cleared and the check's issue is gone.
    2. **No-crew day:** add to a crew → the work goes through the three steps
       → cleared.
    3. **"No work" reason:** clerk → FM → HR → GM approve → cleared, counted
       in HR's summary, and stamped on farm approval.
    4. **Sent back at each step:** work sent back by HR → the record is
       deleted, the day is back in To clear with the reason → enter it
       again → approve.
    5. **Refusals:**
       - the person who entered the work cannot approve it;
       - the same person cannot take both the HR and the GM step;
       - a missing-day save for a day that is not missing is refused;
       - a save for a worker not on that crew is refused.
    6. **Locked grid:** an assignment whose main record is CONFIRMED still
       accepts a missing-day record.
    7. **Payroll check:** a farm with a waiting fix cannot approve; after
       full approval it can, and the fix's worker-day is in the check's
       totals.
  - Every run creates its own test data and removes it afterwards.

## Left to the builder

- Field placement and labels, and where the approval-role lookup lives.
  Reuse the `wm_actuals` step-role logic; do not copy role names.
- How `act_submit`'s missing-day branch is threaded through its code (it is
  long). Keep the change as small as the two lifted rules need.
- The layout of the Waiting tab within the part 1 visual style.
