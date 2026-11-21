# Activity Portions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split a master plan activity into team-leader portions (leader + blocks + share of budget), hard-capped per portion, with the overall team leader kept on the line.

**Architecture:** Three new child tables on `Work Management Master Plan` (portions, portion blocks, change log) keyed to the line by `task` (one line per task per plan). A new `set_portions` action in `wm_masterplan` (modelled on `set_leaders`) writes them at any stage, enforcing Σ ≤ line, one leader per block and, after approval, "not below used" plus a log. `wm_planner` save takes a `portion` and caps against it. Rules are unit-tested pure functions in `work_management/portions.py`, inlined in the sandbox scripts ("keep in step").

**Tech Stack:** Frappe v16 app `work_management`; mirror `kaitet-work-management/server_scripts` (RestrictedPython: no `def`, no `_` names), ported by `port_app.py`; vanilla JS screens (mirror `web_pages/*.js` byte-identical to app `public/js`).

**Spec:** `docs/superpowers/specs/2026-11-21-activity-portions-design.md`

## Global Constraints

- Mirror first, then `python3 port_app.py <wm_x>` and copy `web_pages/*.js` → `public/js/`. Never hand-edit `api/*.py`.
- Sandbox: no `def`, no names starting with `_`, no `.format()`; use `"%.2f" %`.
- Tests: `PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest discover -s work_management/tests -t .` (no site).
- Commits authored ghost-mann, no co-author line. Branch `feature/activity-portions` in both repos.
- An activity with no portion rows behaves exactly as today.
- TOLERANCE = 0.005 for money and quantity comparisons.

## Review Focus

1. A request edited after its activity was split, with no portion picked → refused with "pick a portion", not silently left on the line.
2. `set_leaders` re-stamping requests: must use the **portion** leader for requests that carry a portion, not the line leader.
3. Line rate changing on a plan re-save → portion costs re-derived from the new rate (qty × rate), and Σ check re-run at submit.
4. Removing a line or a portion that has requests against it → refused, and the portion rows of a removed line (with no usage) are dropped.
5. Two portions naming the same block, including via a section expanded on the screen → refused, naming the block.

---

### Task 1: Pure rules — `work_management/portions.py`

**Files:** Create `work_management/portions.py`, `work_management/tests/test_portions.py`

**Interfaces — Produces:**
- `portion_cost(qty, rate) -> float` = round(qty × rate, 2)
- `portion_errors(line, portions, used=None, legacy=None, valid_leaders=None) -> list[str]`
  - `line`: `{task, label, work_qty, cost}`; `portions`: list of `{portion_key, team_leader, work_qty, cost, blocks:[...]}`; `used`: `{key: {q, c}}`; `legacy`: `{q, c}`; `valid_leaders`: set or None (skip check).
  - Errors (one sentence each): missing leader; no blocks; leader not on list; block in two portions (names block and both leaders); Σ qty or Σ cost + legacy over line (names figures); portion below used (names portion leader, used, new).
- `portion_headroom(portion, used) -> {remaining_qty, remaining_cost, exhausted}`
- `unallocated(line, portions, legacy=None) -> {qty, cost}`
- `portion_changes(old, new) -> list[{kind, portion_key, old_value, new_value}]` kinds `budget` / `leader` / `blocks` / `added` / `removed`.

- [ ] Write tests: clean split → `[]`; Σ qty over by 1 → one error containing "over"; block "B1" in two portions → error naming "B1"; portion cut below used 50 → error naming 50; legacy q 30 reduces room; `unallocated` returns the gap; `portion_changes` reports leader swap and qty change; deleting a used portion → error "has requests".
- [ ] Run, see fail; implement; run, see pass; commit.

### Task 2: Doctypes and fields

**Files:** Create doctypes under `work_management/work_management/doctype/`:
- `work_management_activity_portion` (istable): `portion_key` Data reqd, `task` Link Task reqd, `team_leader` Data reqd, `label` Data, `work_qty` Float, `cost` Currency, `man_days` Float, `days` Int, `planned_qty` Float ro, `planned_cost` Currency ro, `remaining_qty` Float ro, `remaining_cost` Currency ro; in_list_view: task, team_leader, work_qty, cost.
- `work_management_activity_portion_block` (istable): `portion_key` Data reqd, `block` Link Warehouse reqd.
- `work_management_portion_change` (istable): `kind` Select (budget/leader/blocks/added/removed), `task` Link Task, `portion_key` Data, `old_value` Data, `new_value` Data, `note` Small Text, `changed_by` Link User, `changed_on` Datetime.
Modify `work_management_master_plan.json`: add Tab/Section "Portions" with tables `portions`, `portion_blocks`, `portion_changes` (allow_on_submit not needed; doc is not submittable). Modify `work_management_planner.json`: add `portion` Data (read_only, after `team_leader`), with allow_on_submit 1.
- [ ] Add a test in `test_portions.py` reading the JSONs: the three tables exist on the master plan with the right options; planner has `portion`.
- [ ] Run tests; `bench --site webstore.localhost migrate`; confirm tables exist; commit.

### Task 3: `set_portions` + `get` + gates in `wm_masterplan`

**Files:** mirror `server_scripts/wm_masterplan.py` (then port).

- `get`: add `out["portions"]`, `out["portion_blocks"]` (grouped into portions as `blocks`), `out["portion_changes"]`, `out["can_set_portions"]` = CAN_EDIT and state != Rejected, or CAN_GM; and per portion `planned_qty/cost` (requests with that portion), plus per split line `legacy_qty/cost` (its task's requests in period with empty portion) and `unallocated`.
- New action `set_portions(name, task, portions=JSON)` (POST, in `WMG_WRITES` with ""): permissions as above; line must exist and not be Rejected; for each portion: key kept or new (`frappe.generate_hash(length=8)`); cost = `portion_cost(qty, line.rate)`; man_days = line.man_days × qty / line.work_qty (0 when line qty 0); days as sent (default line.days). Validate with the inlined `portion_errors` (valid leaders = farm's active list ∪ leaders already on this plan); used/legacy only computed when state is Approved (before approval nothing is consumed, but compute anyway—same SQL, harmless). Replace that task's rows in `portions` / `portion_blocks`; when state is Approved append `portion_changes` rows from inlined `portion_changes`. Then re-stamp requests of this task that carry a changed-leader portion **only when the request is Draft** (spec). Save with `ignore_permissions`, commit, return `portions` back.
- `save`: after rebuilding lines, drop portion/portion_block rows whose task is no longer a line (refuse if any has requests — reuse the post-approval cut check, which already blocks removing a used line); re-derive each portion's `cost` from the line's new rate.
- Gate `MP_PORTIONS_OVER_SQL` (module constant): tasks where Σ portion qty > line qty + TOL or Σ cost > line cost + TOL, ignoring Rejected lines. Refuse in `submit_for_review`, `send_to_gm`, `gm_approve`, both `plans_bulk` ops, and hold auto-advance in `decide_line`/`decide_bulk` (`out["held_for_portions"]`), message: "Some activities are split into portions that add up to more than the activity: <tasks>. Open the plan and re-split them."
- `set_leaders`: (a) stand-in "leads no activity" accepts portion leaders; (b) re-stamp: for requests with a portion, owner = that portion's leader.
- [ ] Source tests (`test_portions_wiring.py`): mirror defines `set_portions`; `WMG_WRITES` has it; each gate action references `MP_PORTIONS_OVER_SQL`; `set_leaders` re-stamp reads `portion`.
- [ ] Port, run full suite, commit both repos.

### Task 4: Planner — tasks list, save cap, request listing

**Files:** mirror `server_scripts/wm_planner.py`.

- `tasks`: per task add `portions: [{key, label, team_leader, acting_leader, acting_name, blocks:[{block,label}], work_qty, cost, remaining_qty, remaining_cost, exhausted, mine}]` and `unallocated_qty/cost`; for a split task `mine` = any portion acting leader is me.
- `save`: read `portion`. After the line cap passes, if the plan has portions for the task: no portion → "<task> is split between team leaders. Pick whose portion this work belongs to."; unknown key → error; any block not in that portion's blocks → "Block X is not in <leader>'s portion of <task>."; portion cap (Σ requests with this portion, excluding self, non-Rejected): over qty/cost → error naming leader, left, asked. Leader = portion leader resolved through stand-ins (same inline loop). Set `d.portion`. Unsplit: `d.portion = None`.
- Request list/get outputs include `portion`.
- [ ] Source tests: save reads `portion`, refuses unsplit-with-portion absent message; port; suite; commit.

### Task 5: Screens (`web_pages/work-planner.js`)

- Master plan view: under each line, a "Portions" sub-row: chips per portion (leader · blocks · qty/cost · used), Unallocated, and when `can_set_portions` a "Split / edit portions" button opening an inline editor (rows: leader select from `leader_options`, label, qty → shows cost and mandays, blocks multi-select from the farm's blocks with sections offered as "add all"), Save → `set_portions`. Approved plans show the change log below.
- Raise request: when the chosen task has `portions`, show a required **Portion** select (`leader — blocks — X left`); choosing it narrows the block picker to its blocks and shows its remaining; send `portion` to `save`.
- [ ] `node --check`; copy to app; source test that the screen calls `set_portions` and sends `portion`; commit.

### Task 6: Dashboard + KPIs (`wm_dashboard.py`, `work-management-dashboard.js`)

- `tl_kpis` master-plan block: for split lines, credit each portion's leader with the portion's budget (planned via requests with that portion); the line leader gets an `accountable` row per activity (whole-line figures) flagged `overall: 1`, shown separately in the scorecard ("Accountable for").
- [ ] Source test; port; suite; commit.

### Task 7: End-to-end on webstore.localhost

- migrate; as Administrator via console: pick an approved plan, split a line into two portions with distinct blocks; raise requests: no portion → refused; wrong block → refused; over portion → refused; within → saved with portion leader; Σ over via set_portions → refused; post-approval change → change rows logged; gate: force Σ over in DB on a Draft plan → submit refused.
- Push branch `feature/activity-portions` in the app repo.
