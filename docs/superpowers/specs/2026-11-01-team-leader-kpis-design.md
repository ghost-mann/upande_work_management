# Team leaders, quality scores and team leader KPIs

*2026-11-01 · requested by Kaitet over WhatsApp*

## Why

Kaitet wants to hold each team leader to four numbers:

| KPI | Their words | How it is measured here |
|---|---|---|
| Completion | "actuals achieved versus the tasks planned in a period" | earned man-days ÷ planned man-days, on the weekly plans the leader ran; and progress against the master plan activities they own |
| Efficiency | "planned resources versus actual resources spent" | earned man-days ÷ worker-days recorded; cost: planned cost of the work done ÷ what it cost |
| Backlog | "total volume of unfinished work" | what is left of the master plan activities they own, in man-days and KES |
| Quality / defect rate | "frequency of errors, rework raised" | the Farm Manager's 1 Good / 2 Fair / 3 Rework score, shown as a Good · Fair · Rework split |

That needs two things the system did not have: a person attached to each
activity, and a quality judgement on each piece of work.

## Decisions (the client's / the user's)

- **The Farm Manager names a team leader per activity on the master plan.**
  Team leaders log in and run their activities end to end — weekly plan,
  crew, actuals.
- **Clerks and supervisors keep full access.** They can still plan and enter
  on a team leader's behalf; the work counts to the activity's team leader.
- **Stand-ins are dated and entered on the master plan.** "X stands in for Y
  from … to …". The work done in those dates counts to **the stand-in** —
  whoever ran the work answers for it. When the dates end the activities
  return to Y on their own.
- **Quality is a required dropdown at the Farm Manager's approval of
  actuals:** 1 Good, 2 Fair, 3 Rework.
- **Rework flags only.** The approval and the pay go through as normal; the
  redo is planned as new work, by hand.
- **Quality on the dashboard is the full Good / Fair / Rework split**, not a
  single rework rate or an average.
- **Completion and efficiency are shown against both** the weekly plans and
  the master plan.
- **Dashboard:** a league table for Farm Managers / HR head / GM, clicking a
  row opens that leader's scorecard; a team leader sees only their own card.

## What was built

### Data

| Doctype | Field | Notes |
|---|---|---|
| Master Plan Activity | `team_leader` (User) | survives `save`'s rebuild of every row |
| Master Plan | `stand_ins` → **Work Management Team Leader Stand In** (child) | team_leader, stand_in, from_date, to_date, note, set_by, set_on |
| Planner | `team_leader` (User, read only) | who ran this week: stamped at submit |
| Actuals | `team_leader` (fetched from the planner), `quality_score`, `quality_note`, `fm_approved_by`, `fm_approval_date` | the last two were already written by `act_fm_approve` inside a `try/except` — the fields never existed, so who approved was never recorded |

### Server (mirror `server_scripts/` → `port_app.py` → `api/`)

- `wm_masterplan`
  - `get` returns `team_leader` per row, `stand_ins`, `leader_options`
    (active employees of the plan's farm who have a login, then anyone
    already named), `can_set_leaders`.
  - `save` carries `team_leader` per row, falling back to the snapshot.
  - **`set_leaders`** (new): `CAN_EDIT` roles, any state but Rejected. Sets
    the leaders and replaces the stand-ins, validates them, then **re-stamps
    the weekly plans** of this master plan whose work is not yet past the
    Farm Manager (no score, not at HR/GM/CONFIRMED). Approved work keeps the
    name it was approved under.
- `wm_planner`
  - `tasks` returns `team_leader`, `acting_leader` (stand-in resolved on the
    request's first day), `acting_name`, `mine`.
  - `submit` stamps `Planner.team_leader` = the activity's leader, or their
    stand-in on `from_date`.
  - `my_requests` also lists plans the user leads.
- `wm_actuals`
  - `act_fm_approve` requires `quality_score` (1/2/3); Rework requires a
    note. Writes score, note, approver, date and a comment.
  - `act_pending` / `act_my` return team leader and quality; `act_my` also
    lists actuals the user leads.
- `wm_dashboard`
  - **`tl_kpis`** (new): league table, or with `team_leader` a scorecard
    (weekly series, weekly plans run, owned master plan activities).

The arithmetic and the stand-in rule are stated once, unit-tested, in
`work_management/team_leaders.py` (`resolve_leader`, `stand_in_errors`,
`weekly_kpis`, `master_plan_kpis`, `quality_split`). The server scripts
cannot `def`, so they inline it — keep them in step.

### Screens

- **Planner → Master plan → open a plan:** Team leader column (dropdown for
  `CAN_EDIT`), a Stand-ins panel, "Save team leaders".
- **Planner → New request:** each activity names who leads it; a leader gets
  "Only activities I lead", on by default.
- **Actuals → Approvals → Farm Manager:** Approve opens Quality + Note +
  Approve/Cancel in the row. My Actuals shows the score.
- **Dashboard:** "Team leaders" section after Master plans.

## Calls made while building (check these)

1. **Who is a team leader** is simply anyone named on an activity — no new
   role. The app ships no roles (`test_no_shipped_roles`); a leader needs the
   planning / assigning / entry roles they already need to use those
   screens, given through their Role Profile.
2. **Server does not refuse** a team leader raising a plan for someone
   else's activity; the picker defaults them to their own. Clerks needed the
   open path anyway.
3. **Completion is in man-days, not quantity.** A leader's activities are in
   hectares, crates, hours — quantities don't add. For one activity it is
   still actual ÷ planned quantity.
4. **Efficiency uses earned man-days** (actual qty ÷ daily target) over
   worker-days recorded, so doing half the work with half the people is not
   100%. On the current data it reads ~100% almost everywhere, because clerks
   record each worker at the daily target; it becomes informative only where
   real output is recorded.
5. **Master plan progress is weighted by budget cost** — `man_days` is
   optional on a plan, `cost` is not. Backlog man-days use the line's own
   man-days ÷ quantity, so lines without man-days add 0 md (still counted in
   KES).
6. **Master plan progress and backlog belong to the activity's owner**;
   weekly figures and quality to whoever ran the week.
7. **A stand-in is resolved on the weekly plan's first day.** A plan that
   straddles the start of a cover goes wholly to whoever held it on day one.
8. **Counted actuals** are those submitted (Pending Farm Manager onwards, not
   Rejected/Draft); weekly plans not Rejected/Draft, by `from_date` in range.
9. **History is not back-filled.** Plans and actuals before go-live carry no
   team leader or score and show as "not scored"; `set_leaders` re-stamps
   only work not yet past the Farm Manager.
10. The Desk workflow can still move an actuals record past the Farm Manager
    without a score; the screens never do.

## Not done

- No automatic rework task; no notification to the team leader on a Rework
  score (the note is on the record and the scorecard).
- User guide / manual not yet updated.
- Mirror `doctypes/*.json` not refreshed (they mirror the legacy live site).
