# Activity portions: one accountable leader, budget split by team leader and block

Date: 2026-11-21 · Requested by james@ (Kaitet, work_management) · Status: draft for approval

## Why

On the farms, many activities are run by several team leaders across several blocks, but a
master plan line carries one `team_leader`. Nobody can be held to their part of the activity:
the money, mandays and blocks are not tied to a person. The fix is to keep one overall
accountable leader per activity and split the activity's budget into **portions**, each owned
by one team leader with their own blocks, never exceeding the activity's approved budget.

## Goals

- Every activity on a master plan keeps one **overall team leader** (the existing
  `Work Management Master Plan Activity.team_leader`, still mandatory).
- An activity can be split into **portions**. A portion = team leader + their blocks + their
  share of quantity, mandays, days and money.
- **Hard cap per portion:** weekly planner requests raised against a portion can't exceed
  that portion's remaining quantity or money. *(user decision)*
- Portions together can never exceed the activity's approved quantity and cost. *(user decision)*
- The **FM splits** activities while drafting the master plan, and the **GM approves the plan
  with its splits**. After approval the FM may move budget between portions without
  re-approval, and every move is logged. *(user decision)*
- The overall team leader has **oversight and an activity-level scorecard**: every portion's
  progress, spend and quality in one view, and KPIs for the whole activity on top of any
  portion they lead. There is **no new approval step**; the chain stays as it is. *(user decision)*
- Portion team leaders' KPIs count only their own portion's work.

## Non-goals

- No change to the assignment → actuals → payment → payroll chain. It already works per
  weekly request, and each request will belong to one portion.
- No new approver role and no approval step for the overall team leader.
- The activity's total budget is not changed by moving money between portions. Changing the
  total still goes through the existing master plan edit/approval rules.

## Anti-goals (would be a failure even if it "works")

- Portions that sum above the activity budget, by any path: save, budget move, post-approval
  edit or legacy requests.
- Two team leaders on the same block within one activity, which brings back shared accountability.
- Breaking plans already approved on live, or the requests and actuals already raised against them.

## Constraints (from the existing system)

- A master plan allows **one line per task** ("appears twice. One line per activity.").
  Within a plan, the task identifies the activity line.
- Frappe can't nest a child table in a child table, so portions and their blocks are
  sibling tables on the master plan, keyed to the line.
- Business logic lives in the mirror `kaitet-work-management/server_scripts/wm_*.py` (Server
  Script sandbox: no `def`, no names starting `_`), ported to `work_management/api/` by
  `port_app.py`. Unit-tested pure helpers live in `work_management/master_plan.py` and
  `team_leaders.py`, with inlined copies in the scripts ("keep in step").
- The planner cap today (`wm_planner` save, `check_plan_allowed`) sums
  `Work Management Planner.quantity/total_cost` by **task + farm + period**. `headroom` in
  `wm_masterplan` does the same and persists `planned_*` / `remaining_*` on the line.
- Team leader keys are login-or-Employee-ID (Data fields). Stand-ins are dated per leader on the
  master plan, and the planner stamps `team_leader` at raise time (stand-in wins on `from_date`).

## Approaches considered

- **A. Portions as tables inside the master plan (chosen by the user).** The split is saved,
  versioned and approved together with the plan, the same way stand-ins already are.
  Cost: portions link to their line by a key rather than true nesting.
- **B. Portion as its own document type.** Cleaner structure and its own history, but plan
  approval would have to validate and lock a set of separate documents, and the drafting screen
  would have to save several records at once, so the plan and its portions can drift apart.
- **C. Allow the same activity twice, one line per leader.** Least new structure, but the
  activity budget becomes a sum of lines rather than a fixed total, the "never past the
  activity budget" rule has to be rebuilt, and reports that treat a line as an activity would
  double-count.

## Design (approach A)

### Data

On `Work Management Master Plan`, three new child tables:

1. **`portions` → `Work Management Activity Portion`**
   - `portion_key` (Data, unique within the plan, stable across saves, e.g. a short random id
     assigned on first save; never reused)
   - `task` (Link Task: the activity line it belongs to; one line per task per plan)
   - `team_leader` (Data, same key rules and picker as the line's team leader: the farm's team-leader list)
   - `work_qty` (Float), `cost` (Currency) — the portion's budget
   - `man_days` (Float), `days` (Int) — derived from the line's rate/daily target, same
     arithmetic as the line
   - `label` (Data, optional, e.g. "Block 4–7 crew")
   - `planned_qty`, `planned_cost`, `remaining_qty`, `remaining_cost` (persisted like the line's)
2. **`portion_blocks` → `Work Management Activity Portion Block`**: `portion_key`, `block` (Link Warehouse).
3. **`portion_changes` → `Work Management Portion Change`** (log, append-only):
   `kind` (budget / leader / blocks / added / removed), `task`, `portion_key`, `old_value`,
   `new_value`, `note`, `changed_by` (User), `changed_on` (Datetime). A "move" is recorded as
   the budget changes on the portions involved. *(builder's call: the screen edits a portion's
   share directly, with Unallocated shown as the difference, rather than a from/to dialog)*

On `Work Management Planner`: new field **`portion`** (Data, the `portion_key`).

### Rules

- **Unsplit = one implicit portion.** An activity with no portion rows behaves exactly as
  today: requests cap against the line, the leader is the line's team leader, and blocks are free.
  Existing approved plans keep working untouched.
- **Split activity:**
  - Σ portion `work_qty` ≤ line `work_qty` and Σ portion `cost` ≤ line `cost`. Any remainder
    shows as **Unallocated** and can't be requested against until the FM moves it to a portion.
  - A block appears in **at most one portion per activity**.
  - The overall team leader may also lead a portion. Two portions may share a team leader
    (different blocks), e.g. someone leading two separate crews.
  - Each portion needs a team leader and at least one block.
- **Raising a weekly request on a split activity:** the request must name a portion. Its
  blocks must come from that portion's blocks, its `team_leader` is the portion's leader
  (or that leader's dated stand-in, the existing rule), and the cap checks **both**:
  the portion's remaining (Σ requests with this `master_plan` + `portion`) **and** the line's
  remaining (unchanged check). The error names the portion and its leader.
- **Budget moves after approval (FM, or GM/System Manager):** move qty/cost between portions
  or to/from Unallocated on an approved plan. A move can't take a portion below what its
  requests have already used, and can't create money (the line total is fixed). Each move
  writes a `portion_changes` row. No re-approval. The FM may also add a new portion after
  approval, funded from Unallocated or by a move. A portion with requests against it can't be deleted.
- **Before approval:** portions are edited freely in the plan draft. The existing save and
  `submit_for_review` / `send_to_gm` / `gm_approve` / `plans_bulk` / decide auto-advance
  validate the Σ ≤ line and block-uniqueness rules, the same way they now refuse a missing team leader.
- **Changing the line itself** (an existing post-approval edit path) can't cut the line below
  Σ portions; the FM must shrink portions first.
- **Consultant cuts during review** (`decide_line` "Edit work"): the cut is allowed. If it
  leaves Σ portions above the line, the line is flagged "portions don't add up", and
  `send_to_gm` / `gm_approve` / `plans_bulk` / decide auto-advance refuse until the FM
  re-splits, the same pattern as a missing team leader. *(builder's call)*
- **Changing a portion's leader or blocks after approval** *(user decision)*: the FM (or
  GM/System Manager) may change a portion's team leader or move a block to another portion
  of the same activity, with no re-approval. Each change is logged in `portion_changes` (add
  `kind` = budget / leader / block, with `old_value` / `new_value`). Requests already raised
  keep the leader and blocks they had, so past KPIs stay with whoever ran the work. Only new
  requests follow the change. This differs from `set_leaders` today, which re-stamps requests
  still awaiting FM approval: for portions, re-stamp only requests still in Draft. The
  block-uniqueness rule still holds after a move.
- **What "used" means for a portion:** exactly what the line cap counts today (Σ `quantity` /
  `total_cost` of the portion's non-Rejected requests in the plan period), so portion, line
  and planner figures always agree. If the line cap later starts giving back closed-short
  balances, portions follow the same rule. *(builder's call)*
- **Blocks only:** a portion holds leaf blocks (`is_group=0` Warehouses, the planner's list).
  Choosing a `Work Management Section` in the picker adds its blocks. *(builder's call)*

### Requests raised before a split (legacy)

If an activity is split after requests were already raised against it, those requests have no
`portion`. They keep counting against the line, and the split must leave room for them:
Σ portion budgets + unportioned usage ≤ line budget. The screen shows them as
"Earlier requests (no portion)". A request still editable (Draft, Pending Approval or Rejected)
when its activity is split must pick a portion the next time it is saved. Until then it sits in
that group, so the group only shrinks. *(builder's call)*

### Screens

- **Master plan:** each activity line gets a "Split" control that expands into its portions
  (leader picker, blocks picker limited to the farm's blocks/sections, qty → mandays/days/cost
  shown), an Unallocated figure, and a warning when the portions don't add up. The overall
  team leader column is unchanged. On approved plans, a "Move budget" action opens a
  from/to/amount dialog and a history list from `portion_changes`.
- **Planner (raise request):** after the task, a **Portion** dropdown (`leader — blocks — X left`)
  appears for split activities. The block picker narrows to that portion's blocks, and the
  remaining figure shown is the portion's.
- **Dashboard / headroom:** per activity, show the overall team leader, then each portion with
  budget, planned, delivered (confirmed actuals via request → portion), remaining and quality.
- **KPIs (`tl_kpis`):** weekly KPIs already follow the request's `team_leader`, so no change.
  Plan-level completion compares a portion leader against **their portion's** budget, and
  for unsplit lines against the line, as today. The overall team leader gets an
  **activity-level row** for each activity they're accountable for: the whole activity's completion,
  efficiency and quality, shown separately from their own portion figures so nothing counts twice.

## Left to the builder

- Exact screen layout and wording, and where the split editor sits on the master plan page.
- `portion_key` generation scheme (must be stable and unique within the plan).
- Whether portion `cost` is entered or derived from `work_qty × rate` (it must match the line's
  arithmetic; the line's rate is fixed).
- Migration: none required beyond the new doctypes and fields; legacy rows have empty `portion`.
- Tests: pure helpers in `master_plan.py` (portion headroom, Σ check, move validation) with
  sandbox-inlined copies, plus the mirror's existing exec-a-block tests.

## Calls made without asking (please check)

- Unsplit activities behave exactly as today (one implicit portion).
- One team leader per block within an activity. The same person may lead two portions.
- Money can sit Unallocated, and nothing can be requested from it.
- GM/System Manager can also move budget, alongside the FM.
- Requests raised before a split stay on the line and reduce what the portions can hold.
- A move can't take a portion below what it has already used.
- A consultant cut below the portions flags the line and blocks sending to the GM until the FM re-splits.
- "Used" for a portion = the same count as the line cap today.
- Editable requests pick a portion on their next save after a split.
- Portions hold blocks; picking a section adds its blocks.
