# Two master plans over one period

*2026-08-28*

## The change in one sentence

A farm may hold more than one master plan over the same days, and each planner
request records which plan it draws against instead of that being inferred from
its dates.

## Why

A farm can run separate streams of work in the same month — field operations and
a replanting or construction project — each with its own budget. Today the second
one cannot be raised at all:

> *Saboti already has a master plan covering those dates: WMMP-00042 (2026-08-01
> to 2026-08-31, Approved). A farm has one budget per period — put this work on
> WMMP-00042 instead of raising a second plan, or choose dates outside it.*

That rule is not arbitrary, and this is the important part: **nothing records
which plan a request belongs to.** `Work Management Planner` has 53 fields and
none of them names a master plan. The relationship is reconstructed at read time
from `farm` plus `from_date`/`to_date` falling inside a plan's period, and it is
only reliable because two plans cannot cover the same days.

So lifting the rule without storing the link would make the relationship
ambiguous everywhere it is used:

| reader | what it decides | what ambiguity does |
|---|---|---|
| `wm_planner` · `tasks` | which activities may be planned | `ORDER BY period_from DESC LIMIT 1` picks arbitrarily between two plans |
| `wm_planner` · caps, headroom | how much budget is left | draws down whichever plan sorted first |
| `wm_dashboard` · `mp_value` | planned vs delivered per plan | a request inside two plans is **counted against both** |
| `wm_dashboard` · `plan_completion` | how much of a plan happened | same double count |
| `wm_payment`, `wm_payroll`, `wm_rates` | period-scoped reads | resolve by period; to be audited case by case |

On live that inference currently carries **1,578 planner requests**, 1,426
assignments and 1,325 actuals against **17 master plans**.

## Decisions

1. **The link is explicit and stored.** `Work Management Planner` gains
   `master_plan`, a Link to `Work Management Master Plan`.
2. **Naming the plan is required** whenever the farm has a plan covering the
   dates. A farm with no plan is unaffected, and the requirement is what keeps
   every total unambiguous from the first request rather than most of the time.
3. **Overlap warns, it does not block.** `period_free` and the save-time check
   keep reporting a clash; the screen shows it and lets the person continue.
   Removing the check entirely would make raising the same plan twice by mistake
   indistinguishable from raising a deliberate second one.
4. **Plans carry a purpose.** Master Plan gains `plan_name` — "Field
   operations", "Replanting" — because two Saboti plans for August are otherwise
   two identical rows in the picker separated only by `WMMP-00042` and
   `WMMP-00043`.
5. **Existing requests are backfilled, not guessed.** Every one of the 1,578 has
   exactly one containing plan, precisely because overlap has been forbidden
   until now. A row with no containing plan is left null and logged.

## Non-goals

- **A "work stream" doctype.** Plans and requests could point at a shared stream
  rather than each other, which would allow reporting by stream across farms.
  That is this design plus one concept, and it does not remove the need to store
  the link on the request, so it can be layered on later if streams become a real
  organising idea. Not now.
- **Retiring the date inference.** It stays as the fallback for rows written
  before `master_plan` existed, and for any the backfill could not resolve.
- **Changing what a plan caps or how the arithmetic works.** Only *which* plan a
  request is measured against changes.

## Data model

**`Work Management Master Plan`**

| field | type | notes |
|---|---|---|
| `plan_name` | Data | The purpose. Not unique, not the name — `naming_series` still produces `WMMP-#####`. Shown beside the number wherever a plan is listed or picked. |

`title_field` moves from `farm` to a rendering of farm and purpose, so a plan
reads as "Saboti · Replanting" in link fields and lists.

**`Work Management Planner`**

| field | type | notes |
|---|---|---|
| `master_plan` | Link → Work Management Master Plan | The budget this request draws against. Not `reqd` on the doctype: rows written before this field exist, and a farm with no plan can still raise a request. The requirement is enforced in `save` where it can be conditional. |

## Which plan a request belongs to

`wm_planner`'s `save` requires `master_plan` when any plan covers the farm and
dates, and validates that the named plan is Approved, belongs to that farm, and
contains the request's dates. `tasks` takes the plan from the request rather than
looking one up; the caps and headroom draw down the named plan.

The screen already renders a chip per plan for the farm — `renderPeriodBar` — so
those chips become the selector rather than only a date shortcut, and the choice
travels with the request. That builds on the bounding behaviour added in
`3618593`: choosing a plan bounds the request's dates to its period and leaves a
range that already fits alone.

Every reader prefers the stored link and falls back to date containment only when
it is null:

    plan = request.master_plan or <the plan whose period contains the dates>

## The backfill

`work_management.patches.v1_0.link_planners_to_their_master_plan`, `[post_model_sync]`:

1. For each `Work Management Planner` with no `master_plan`, find the plans for
   its farm whose period contains its `from_date` and `to_date`.
2. Exactly one → set it with `frappe.db.set_value` (several of these doctypes are
   submitted and will not accept a save).
3. None → leave null, count it, print the total.
4. More than one → cannot occur on data written under the old rule; if it does,
   leave null and name the request and the candidate plans, because guessing
   which budget somebody's work was drawn from is exactly the error this whole
   change exists to prevent.

Idempotent: a second run finds nothing without a `master_plan` that it can
resolve.

## Blast radius

- `server_scripts/wm_planner.py` — `tasks`, `save`, caps and headroom
- `server_scripts/wm_masterplan.py` — `period_free` and the save clash become
  warnings; `plan_name` accepted and returned
- `server_scripts/wm_dashboard.py` — `mp_value` and `plan_completion` join on the
  stored link where present
- `server_scripts/wm_payment.py`, `wm_payroll.py`, `wm_rates.py` — audited for
  period-based resolution; changed only where they attribute work to a plan
- `web_pages/work-planner.js` and the app's copy — the chips become the selector
- `web_pages/work-management-dashboard.js` and the app's copy — plan labels show
  the purpose
- the two doctype JSONs, and `port_app.py` regenerating `api/*.py`

Live runs the Server Scripts, and its Work Management doctypes are custom ones,
so both new fields have to reach live as Custom Fields for the scripts to read
them. That is a deployment step, not only a code change.

## Tests

- **Pure, no site:** which plan a request resolves to given a stored link, a null
  link with one containing plan, a null link with none, and a null link with two
  (the case that must refuse rather than pick).
- **The backfill:** sets the single match; leaves null and reports when there is
  none; leaves null and names both when there are two; is idempotent.
- **`save` validation:** refuses a request naming no plan where one covers the
  dates; refuses a plan belonging to another farm; refuses a plan not containing
  the dates; accepts a farm with no plans at all.
- **Double counting:** two overlapping plans and one request; `mp_value` and
  `plan_completion` attribute it to exactly one.
- The existing suite stays green:
  `PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest discover -s work_management/tests -t . -p "test_*.py"`
- `scripts/check_ported.py` reports all 10 api modules matching a fresh port.

## Risks

| risk | disposition |
|---|---|
| A request written between deploy and backfill has a null link | the fallback still resolves it, because overlap only becomes possible once someone raises a second plan |
| Someone raises a second plan before the backfill runs | the patch reports that request rather than guessing; ordering the deploy so the patch runs first avoids it |
| Live's doctypes are custom, so the fields are Custom Fields there | they must be created on live before the scripts that read them are pushed, or the reads return nothing |
| `plan_name` is free text | it labels, it never resolves — no rule depends on its value |
| Two overlapping plans budgeting the same activity | intended and supported; it is why the link is stored rather than inferred from the task |

## Order of work

1. Tests for the resolution rule and the backfill (they fail).
2. The two doctype fields.
3. `save` validation and `tasks` in the mirror; port.
4. The backfill patch.
5. Dashboard attribution, then the remaining scripts audited one at a time.
6. The planner screen's chips as selector; the dashboard's plan labels.
7. Full suite, `check_ported.py`, then drive it on kaitet.local: two overlapping
   plans on one farm, a request against each, and both dashboard cards showing
   each request once.
