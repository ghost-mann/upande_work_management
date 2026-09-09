# The `altura` branch is a fork of the mirror pipeline

*Declared 2026-09-09, on `altura` @ `c5a481f`.*

## What is different here

On `master`, every module under `work_management/api/` is **generated**. The
authority is a separate checkout — Kaitet's mirror — which holds the Frappe
Server Scripts (`server_scripts/wm_*.py`) and the live screens
(`web_pages/*.js`); `port_app.py` renders them into this app, and
`scripts/check_ported.py` proves the rendering still matches. A fix typed into
the generated file works, reviews cleanly, and is deleted without a word by
whoever next runs the porter. That is the whole reason for the mirror workflow,
and on `master` it still holds.

**On this branch it does not.** Altura's deployment runs the packaged app. It
does not run Kaitet's Server Scripts, so there is no porter downstream of these
files and nothing to revert them. Here, `work_management/api/*.py` and
`work_management/public/js/*.js` are **hand-maintained source files** and are
edited directly.

## The rules on this branch

1. **Do not run `port_app.py` against this checkout.** It would overwrite the
   hand-maintained modules with a render of Kaitet's scripts and silently drop
   everything listed under "What diverges" below.
2. **Do not run `check_ported.py` and act on its output.** It will report drift,
   correctly, because drift is now the intended state.
3. **A merge from `master` needs manual `api/` triage.** Take `master`'s changes
   as a description of intent, not as a patch: for each touched module, decide
   by hand whether the change belongs on top of this branch's version. The
   divergence list below is the checklist for that.
4. **The mirror stays authoritative for Kaitet.** Nothing here changes how
   Kaitet is maintained. A fix that both sites want has to be made twice —
   once in the mirror for Kaitet, once here for Altura — and that cost is the
   accepted price of the fork.
5. `config.py`, `hr.py`, `permission.py`, `__init__.py`, and everything outside
   `api/` were always hand-written; they are unaffected by any of this.

## What this does to the suite

Two kinds of test enforce the mirror contract, and both now **skip on purpose**
rather than by accident. They are gated on the presence of *this file*, not on
the mirror's absence, so they skip deliberately even on a machine that has a
mirror checked out — the point is that on `altura` there is nothing for them to
prove, not that there is nothing to compare against.

| Test | What it did |
|---|---|
| `test_the_generated_files_are_not_hand_edited.py` | ran the mirror's `check_ported.py`: a fresh port must reproduce every `api/` module |
| `test_no_capability_is_stranded.py` → `TestTheAppAndMirrorScreensAgree` | `public/js/<screen>.js` byte-identical to `web_pages/<screen>.js`, for all four screens |
| `test_master_plan_resolution.py` → `test_the_app_and_mirror_copies_agree` | the same byte-compare for `work-planner.js` alone |

All three skip with:

> `altura fork: api/ and screens are source, see docs/ALTURA_FORK.md`

They are **kept, not deleted**. A future reconciliation with `master` — a
decision to fold this work back into the mirror and retire the fork — wants them
back, and deleting the file above is all it takes to re-arm them.

The remaining mirror-gated tests are untouched. They read the mirror's own
scripts to check things *about the mirror* (that its names are defined before
use, that it compiles in the restricted sandbox, that it measures rather than
counts), and they still skip only when no mirror is checked out, which is the
correct behaviour for them.

## What diverges

Every item below is a `docs/MIRROR_HANDOFF.md` item implemented **directly in
the app** on this branch. `MIRROR_HANDOFF.md` remains the item-by-item spec; the
"mirror script" column in it is the thing that no longer applies. A future
reconciliation has to port each of these back into the named mirror script by
hand.

| Handoff item | Implemented here in | Mirror script that would need it |
|---|---|---|
| 0 — task-name stragglers on two screens | `public/js/work-planner.js`, `public/js/work-management-dashboard.js` (already committed in `e935e34`) | `web_pages/work-planner.js`, `web_pages/work-management-dashboard.js` |
| 1 — §1 drawdown attribution by `master_plan` link, with the ambiguity guard and the unattributed remainder | `api/masterplan.py`, `api/planner.py`, `master_plan.py` | `wm_masterplan.py`, `wm_planner.py` |
| 2 — Phase 3 remainder: planner screen wired to the configured chain | `api/planner.py`, `api/masterplan.py`, `public/js/work-planner.js` | `wm_planner.py`, `wm_masterplan.py`, `web_pages/work-planner.js` |
| 3 — Phase 5: `custom_basic_pay` weekly feed with the off-day bonus | `api/payroll.py`, `api/payment.py`, `public/js/work-payment.js` | `wm_payroll.py`, `wm_payment.py`, `web_pages/work-payment.js` |
| 4 — Phase 5b: public-holiday double pay | `api/actuals.py`, `api/payment.py`, `public/js/work-payment.js`, `report/worker_task_day` | `wm_actuals.py`, `wm_payment.py`, `web_pages/work-payment.js` |
| 5 — Phase 6: mid-flight target raise | `api/planner.py`, `api/actuals.py`, `api/masterplan.py`, `public/js/work-planner.js` | `wm_planner.py`, `wm_actuals.py`, `wm_masterplan.py`, `web_pages/work-planner.js` |

The Settings fields, the `Employee.custom_basic_pay` custom-field fixture and
every test for the above were always app-side, mirror or no mirror, and are not
divergence.

## The sandbox constraint no longer binds — within reason

The mirror's Server Scripts run in Frappe's restricted sandbox, which allows
**no `def` and no `return`**. That is why the generated modules read as long
inline blocks, and why pure logic that wanted a function was pushed out into
`master_plan.py`, `split_day.py` and `approvals.py` for the mirror to re-inline.

Here, these are ordinary Python modules and a helper function is allowed where
it removes duplication. Two cautions:

- Keep diffs reviewable. A small extracted helper beside the code that used to
  be inlined is fine; rewriting a module into a different shape makes the
  manual merge in rule 3 impossible.
- The shared pure modules (`master_plan.py`, `split_day.py`, `approvals.py`) are
  still shared with the mirror and still have to satisfy its sandbox. Logic put
  *there* stays inline-able.
