# Missing work: present task workers with no actuals

Date: 2026-11-23 · Requested by james@ · Status: draft for approval

## Why

Team leaders and clerks sometimes forget to record actuals for a task worker
who came to work. The worker is then simply not paid for that day, and
nobody is told. The payroll check only finds problems with actuals that exist
(absent but paid, quantity too high, and so on). Nothing finds actuals that
are **missing**. The monthly attendance sheet on the dashboard shows these
days as "present, no work", and that is where james@ noticed them.

The payroll check for **21 Oct – 20 Nov 2026** is about to run. On live, that
period has **566 task-worker days with a scan and no actuals** (counted
2026-11-23, holidays excluded):

| Farm | Scan days | No actuals | On an assignment crew that day | Not on any crew |
|---|---|---|---|---|
| Endebess | 6,172 | 431 | 50 | 381 |
| Vale | 1,311 | 112 | 67 | 45 |
| Lokitela | 1,929 | 22 | 19 | 3 |
| Saboti | 266 | 1 | 0 | 1 |

There are two different cases:
- **On a crew, no actuals.** This is a forgotten entry.
- **Not on any crew.** The worker was never assigned. Either they worked on
  something that was never put on an assignment, or they came in and were
  not given work.

## Goals

- Every task-worker day with presence ends in exactly one of two states:
  **work recorded** (actuals), or **"no work given"** with a reason.
- Farms find and clear these days themselves, day to day, from a new
  **Missing work** tab in the Actuals screen.
- A farm cannot approve its part of a payroll check while it still has
  unresolved days inside the check's dates.
- Team leaders get a morning email listing yesterday's missing workers, so
  the backlog does not build up again.

## Non-goals

- No automatic pay. Nothing is paid unless someone records the work (the
  user rejected a default day rate).
- No change to how actuals are entered, approved or paid once they exist.
  Fixes go through the normal Enter Actuals grid and its rules: the
  one-worker-one-day guard, the quantity caps, and the approval chain.
- Salaried / non-task workers are out of scope.

## Anti-goals (this fails if)

- Farms clear the list by typing in fake work. That is why "no work given"
  exists: an honest idle day must be easy to record.
- "No work given" becomes a silent way to hide days. Every reason is logged
  with who gave it, and HR sees the list in the check.
- It blocks the payroll check on days nobody can fix, such as an approved
  leave day, a holiday, or a worker who left.

## Decisions made with the user

1. **What clears a day:** either enter the work, or mark the day "no work
   given" with a reason. Must-enter and default-pay were both rejected.
2. **Old days with no assignment:** while a payroll check is open, the
   farm's own farm manager, or the GM, can add the worker to an assignment
   for any day inside the check's dates, without the GM's 7-day backdate
   approval. This is logged on the assignment, and the check shows it to
   HR/GM as "added late".
3. **Approach:** A (a Missing work tab in Actuals plus a block in the payroll
   check) together with C (a daily reminder email). B (fixing inside the
   check only) was rejected because nobody would see a missed worker until
   payroll.

## Approaches considered

- **A. A Missing work tab in Actuals, plus a block in the payroll check
  (chosen).** Farms clear days continuously. Fixes reuse actuals entry, so
  pay follows the same rules. The check enforces it at the end.
- **B. Inside the payroll check only.** This is less to build, but the
  problem surfaces only at payroll time, which is the pile-up james@ wants
  to avoid.
- **C. A daily reminder email (chosen, alongside A).** It prevents the
  backlog but does not enforce anything on its own.

## Definitions

A **missing day** is a (worker, date) pair where all of the following hold:
- The worker is a **task worker** by the same payable rule the dashboard
  uses (the Work Management Settings payable employment types, designations
  and categories, else `employment_type = 'Task Worker'`).
- The worker was employed at the farm on that date (status Active, or left
  after that date). The farm is the employee's `custom_farm`, which is the
  same as on the attendance sheet.
- There is **presence**: an Employee Checkin that day, or a submitted
  Attendance with status Present or Half Day.
- The day is **not excused by the calendar**: it is not a Holiday on the
  employee's holiday list, and it is not covered by an approved Leave
  Application.
- **No actuals:** there is no Work Actuals Employee row for that
  employee and work_date in a Work Management Actuals with docstatus < 2.
  A Draft or Rejected-but-not-deleted record counts as "entered". The
  existing check already handles those as "unfinished".
- **No "no work" record** exists for that worker and date (see below).

Each missing day is shown with its **crew context**: the active assignment(s)
the worker was on that date, worked out the same way as the
`people_board`/assigner date rule (`we.start_date`, `left_date`,
`a.from_date`/`a.to_date`, workflow state not Draft/Rejected). If there is
none, the day is "not on any crew".

## Data

New DocType **Work Missing Day Excuse** (non-submittable; the builder may
pick a better name). One row per employee per date:
- `employee` (Link Employee), `employee_name`, `farm`, `work_date`
  (unique together with employee)
- `reason` (Select): Sent home – no work · Rain / weather · Sick / left
  early · Scanned but not working (visitor, collecting pay, mistake) ·
  Other
- `note` (Small Text; required when the reason is Other)
- `assignment` (Link, optional: the crew they were on, for context)
- `marked_by`, `marked_at`
- `payroll_check` (Data): stamped when the farm approves a check, so a
  reason cannot be changed afterwards. It is cleared on send-back and
  cancel, the same way `Work Actuals Employee.payroll_check` is.

Permissions: read for WM roles. Writes go only through the API below.

## Missing work tab (Actuals screen)

A new tab, **Missing work**, after Approvals. Who sees it: anyone who may
record work on at least one farm, which is the `enter_work` grant or a farm
manager of that farm. The farm list is scoped as on the other tabs.

```
Missing work   Farm [Endebess ▾]  From [21 Oct]  To [20 Nov]   [Apply]
112 days need work or a reason · 67 on a crew · 45 not on any crew

Tue 04 Nov
  BBC CONTROL SPOTS · Blk 7 · TL Gilbert C.          [Enter work for 3]
     ☐ Kiprop J. (END-0412)   scan 06:52–15:10   [Enter work] [No work…]
     ☐ Wanjiru M. (END-0388)  scan 07:01–14:58   [Enter work] [No work…]
  Not on any crew
     ☐ Otieno P. (END-0501)   scan 06:40–16:02   [Add to assignment…] [No work…]
[Mark selected: No work… ]
```

- **Enter work:** opens Enter Actuals for that assignment, at the week
  containing the date, with the worker's cell for that day focused. Nothing
  new is built here: the grid, its guards and its approvals apply.
  "Enter work for N" does the same for every missing worker on that crew
  that day.
- **Add to assignment…:** this is for days not on any crew. Pick an
  assignment of the same farm that covers the date. The worker is added to
  its crew from that date to that date (or a short range the user picks).
  The user then lands in Enter work as above.
  - Without an open check this follows the normal backdate rule: older than
    7 days needs the GM.
  - **Inside an open payroll check's dates** (status Farm Review, farm not
    yet approved), the farm's farm manager or the GM may do it with no GM
    backdate approval. A comment is logged on the assignment ("Added late
    for payroll check WMPC-…, by …, reason …"), and the check gets an
    "added late" row for HR/GM (acknowledge-type issue, owner HR).
- **No work…:** pick a reason and an optional note, for one day or for the
  selected days. This creates excuse rows.
  - Who may do it: anyone who may record work on that farm. A clerk's
    excuse is visible to the FM and HR. *(Builder's call; it matches who may
    enter the work.)*
  - Undo is allowed until the farm approves a check covering that date.
- Days drop off the list as soon as actuals or an excuse exist. The
  default range is the open check's dates if there is one, else the last
  14 days.

## Payroll check

- **New issue code `missing_work`**, class **block**, owner **farm**, title
  "Present, no work recorded". It is computed in `wmi_issues` per farm over
  the check's dates, one issue per (worker, day). Its key is
  `employee|date`.
- `chk_farm_approve` already refuses while there are open block issues, so
  the gate needs no new wiring. The error message should name the count and
  point to the Missing work tab.
- The check screen shows these issues with a link that opens the Missing
  work tab, prefilled with the farm and the check's dates. There are no
  inline fixes in the check.
- **Excuses in the check:** HR and GM see an informational list, "No work
  given: N days", grouped by reason and by who marked them. It does not
  block.
- **On farm approval,** the farm's excuse rows in the check's dates get
  stamped with `payroll_check`.
  - On send-back or cancel they are unstamped, as `wmpc_unstamp` does for
    actuals.
  - A stamped excuse cannot be undone.
- **Top-up checks:** the same rule applies over the top-up's dates.

## Daily reminder (C)

- **When:** a scheduler job in the app, daily at **07:30** Africa/Nairobi,
  covering **yesterday** (and any older missing days in the last 7 days,
  so a missed morning still gets caught).
- **On-crew missing days** go to the assignment's **team leader**, who is
  the planner's `team_leader` when that is a login user with an email.
  - The farm manager(s) of the farm are always copied.
  - Team leaders who are employees without a login (see the per-farm TL
    list) are skipped, and the FM gets their part.
- **Not-on-any-crew days** go to the farm manager(s) only.
- **GM and HR** (requested by james@, 2026-11-23) get **one all-farms
  summary** each morning. It is not a copy of every team leader's email.
  - Contents: the counts per farm, then every missing worker grouped by
    farm, day and crew, including the not-on-any-crew days.
  - Recipients come from a new Settings field, `missing_work_notify`
    (a list of emails). It is set on live to the GM
    (koskey@lokitelaorchards.com) and HR (hro@endebesscoffee.com), the same
    people the approval reminders use.
- **One email per recipient**, listing workers by day and by crew, with a
  link to the Missing work tab.
- **Nothing to report:** no email is sent.
- **Sender:** "Kaitet Work Management <notifications@karenroses.com>", as
  for the approval reminders. The Kaitet default mailbox hits Gmail's daily
  cap.
- **Settings:** an on/off Check field `missing_work_reminder` (default off,
  switched on after deploy) and the send time.

## Rollout and timing

1. **Build, test and deploy this before the 21 Oct – 20 Nov check is
   created.** A check created on the old code could be farm-approved
   without the gate, which would stamp the days.
2. Deploy, then migrate (the new DocType and the Settings fields).
3. **HR creates the 21 Oct – 20 Nov check straight after the deploy.** The
   open check is what lets FMs add old no-crew days without the GM, and the
   new block stops any farm from approving early. So creating it first is
   safe.
4. The FMs clear the Missing work tab for those dates (566 days at the
   2026-11-23 count), then approve their farm.
5. Switch the reminder on.

## Edge cases (settled by Claude; the user can override)

- **A scan, but Attendance says Absent:** not a missing day.
  - HR's attendance is the authority, and `att_absent_never` refuses
    actuals on an Absent day anyway.
  - If the Absent mark is wrong, HR corrects the attendance, and the day
    then appears in the tab.
- **Which farm owns the day:**
  - On a crew: the **assignment's farm**. That farm's tab shows the day,
    its check issue blocks that farm, and its FM or clerks may excuse it.
  - Not on any crew: the employee's `custom_farm`.
- **Top-up checks:** `missing_work` does **not** run on top-ups, as the
  existing "unfinished" check already skips them. A top-up is for specific
  late work, and leftover gaps from the main period should not block it.
- **Days inside an already Sent check:** these are shown in the tab marked
  "in a sent check" and never block. Work entered for them goes through
  the existing top-up path. Excusing them is allowed.
- **Reminder team leader:** use the existing per-date leader resolution,
  so a stand-in covering that date gets the email instead of the activity's
  own leader.

## Left to the builder

- Exact DocType and field names; where the presence and crew queries live,
  shared between the tab, `wmi_issues` and the reminder (one helper, so the
  three always agree).
- Whether "Enter work" deep-links by URL params or by in-page state.
- Performance: one farm × 31 days × ~600 workers must load in a few
  seconds. Batch the queries by date range, not per worker.
- Tests in the existing site-less suite, and the user guide PDF.
- The mirror/port_app workflow (`server_scripts/wm_*.py` →
  `api/*.py`) and the sandbox naming rule (no leading underscores).
