# Assign the day before — design (2026-11-26)

## Why
Requested by james@ for Kaitet live. Crews should know their job **before** they
arrive, so clerks finish tomorrow's assignments today. Live 27 Oct–26 Nov: of 622
assignments only 28 (5%) were made before their start day; 346 on the day, 176 one
day late, 72 two or more days late (Saboti 52/52 one day late, Endebess 137/210 late).

## Goals
- Planning ahead becomes the default: an assignment for day D is made before a
  cut-off on D-1.
- Real same-day needs (rain, absences, urgent work) still work, but every late
  assignment carries a reason the FM sees when approving.
- Each farm's late-assignment count is visible, so non-planning shows up.
- A reminder before the cut-off lists tomorrow's work with no crew yet.

## Non-goals / anti-goals
- Not a hard block. Refusing same-day work would leave real work unassigned and
  unpaid (anti-goal).
- Does not change the existing backdate limit (`max_backdate_days`, GM + reason
  beyond it). That rule stays as is and runs after this one.
- No change to approvals, pay or the payroll check.

## Approaches considered
1. Hard rule: start must be tomorrow or later; same-day only by FM/GM with reason.
   Strict, but 95% of today's practice would be refused.
2. Nudge only: 16:00 reminder + "late" KPI, nothing asked at save. Habits may not
   move (Saboti).
3. **Cut-off + reason + reminder (chosen by james@).** Free until the cut-off the
   day before; after it the clerk must give a reason; FM sees it; reminder at 16:00.

## The rule
- An assignment's start is the plan's `from_date` (new assignment) or the Add crew
  start date (workers added later).
- **Deadline** for start D = D-1 at `assign_cutoff_time` (Settings, default 18:00,
  site time zone).
- Saved after the deadline → **late**. The save asks for a late reason: a pick
  list (Replacing absent worker / Weather / Urgent work / Other) plus a note,
  note required for Other. No reason → refused with a clear message.
- **Plan approved late:** if the plan itself was approved after the deadline, the
  clerk could not have assigned earlier. The assignment is still marked late, but
  the reason is filled automatically ("Plan approved late") and nobody is asked.
- Applies to everyone who creates assignments (clerk, FM, GM).
- Stored on the assignment: `late_assignment` (Check), `late_reason` (Select),
  `late_note` (Small Text). Also added as a comment so it shows in the timeline.

## Where it shows
- FM approval tab: a "Late" badge with the reason on each late assignment.
- Late counts per team leader and per saver: the new tab on the team leader card
  (below).

## Team leader card: tabs (james@, 2026-11-26)
The dashboard card "Team leaders — completion, efficiency, backlog & quality"
(`wm-tlk`, action `tl_kpis`) gets three tabs. It keeps its farm / date / leader
filters, and team leaders still see only themselves (`can_see_all`).

1. **Performance**: today's league table and scorecard, unchanged.
2. **Late assigning** (james@ chose "both, side by side"):
   - *By team leader*: late assignments count against the team leader of the
     activity's plan. Columns: assignments, late, % late, and the main reason.
   - *By who saved*: the same counts per user who saved the assignment, clerks included.
   - Clicking a row lists its late assignments: start date, saved at, saved by,
     team leader, activity, block, reason and note.
   - "Plan approved late" is counted but shown apart from the others, because the
     clerk could not have assigned earlier. *(Claude's call)*
   - History counts too: lateness is worked out from `creation` against the
     deadline, so past assignments show as "late, no reason given" from day one.
     *(Claude's recommendation; james@ said "finish")*
3. **People** (james@ chose "on their crews in the dates"):
   - For a team leader: the workers on crews of the activities they lead, within
     the card's date range.
   - Columns per worker: activity, block, days worked in range, and today's status
     (Present / Absent / Leave / not scanned).
   - In the all-leaders view, a team leader picker comes first.

## Reminder
- Daily at `assign_reminder_time` (default 16:00): per farm, approved plans whose
  `from_date` is tomorrow and that have no assignment yet. Nothing to list → no email.
- Recipients: same rule as the free-people reminder (farm's "Assigner: Farm
  Manager" stage approvers; hro@ and koskey@ all farms; austin@ bcc). *(Claude's
  call — say if clerks should get it too.)*

## Settings (Work Management Settings)
- `assign_day_before` (Check, default **off**) — switches the whole feature.
- `assign_cutoff_time` (Time, default 18:00).
- `assign_reminder` (Check, default off) and `assign_reminder_time` (Time, 16:00).

## Build notes for the builder
- Source of truth is the mirror (`kaitet-work-management/server_scripts/wm_assigner.py`),
  ported with `port_app.py`; screen JS byte-identical to mirror `web_pages/`.
- Hook into the same save paths that call `wmg_backdate_err` (new assignment,
  Add crew, release-and-reassign start date).
- Reminder: app scheduler job gated by the Settings checks (not a live Server Script),
  so it ships with the code.
- Tests in the site-less suite: before/after cut-off, day-of, backdated, plan
  approved late, switch off.

## Go-live
Deploy + migrate → switch on `assign_day_before` and `assign_reminder` when james@
says. Can run a week with only the reminder on first if wanted.
