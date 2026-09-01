# Switching an approval step off, and having it actually skipped

*2026-09-01*

## The change in one sentence

The five work screens work out the next approval state from the configured chain
instead of naming it in their own code, so the **On** checkbox that already exists
against every approval step stops being a trap and starts being a setting.

## What already works, so nothing is rebuilt

Most of the mechanism is in place, and this is worth stating precisely because the
request reads like "make it configurable" when the accurate version is "make the
screens honour the configuration that exists".

Settings carries an **Approval Stages** table -- one row per step, each with a
stage key, the state it waits in, its action, a Role, an **On** checkbox and an
order. `kaitet.local` has sixteen rows, and their roles are already the site's
own (HOD HR, Production Section Head, Accounts Manager) rather than the shipped
`System Manager` defaults.

`plan_workflow()` (`approvals.py:461`) already does the right thing:

    chain = [stage for stage in chain_for(document_type) if is_enabled(stage, rows)]
    ...
    next_state = chain[index + 1].state if index + 1 < len(chain) else terminal_state

So a disabled step is dropped and the step before it is joined to the step after
it. A step can also be *added* through Settings: `kaitet.local` has a
`Planner: Finance` row that exists in no Python file, and the generated workflow
honours it -- `Pending Approval -> Pending Finance -> Approved`.

Nine steps are switchable today. The Submit steps and `Payment: Accounts` carry
`required=True` and `is_enabled()` returns True for those regardless.

## The gap, which is the whole of the work

The desk workflow is not where the work happens. Five web screens are, and they
have the chain written into them as literal text -- **189 mentions of 5 state
names across 6 scripts**:

| script | mentions | distinct states |
|---|---|---|
| `wm_dashboard` | 57 | 4 |
| `wm_actuals` | 48 | 3 |
| `wm_assigner` | 35 | 3 |
| `wm_masterplan` | 32 | 2 |
| `wm_payment` | 9 | 3 |
| `wm_planner` | 8 | 3 |

The five, by weight: `Pending GM` 65, `Pending HR Head` 51,
`Pending Farm Manager` 44, `Pending Consultant` 17, `Pending Approval` 12.

Two kinds of mention, and they need different treatment. The five screens
*advance* the chain, so their approve actions and their guards must follow it.
`wm_dashboard` never advances anything -- its 57 mentions are all read filters
and stage counts, so it needs `LIVE_STATES` and nothing else. That is the larger
half of the count and the easier half of the work.

The shape of it, from `wm_assigner.py`:

    elif action == "a_fm_approve":
        ...
        frappe.db.set_value("Work Management Assigner", nm,
            "workflow_state", "Pending HR Head", update_modified=False)
    elif action == "a_hr_approve":
        if cur_ws != "Pending HR Head":
            ...

So switching off **Assigner: HR Head** today produces this:

| | result |
|---|---|
| generated workflow | `FM Approve -> Pending GM`. Correct. |
| the assigner screen | still writes `Pending HR Head` |

and `Pending HR Head` is no longer a state in the regenerated workflow, because
`plan_workflow` only adds states for enabled stages. The document lands somewhere
with no transition out. **The checkbox is real and using it would break the
pipeline rather than shorten it.**

In-flight exposure is small: 22 documents are mid-approval on staging (15
planners at `Pending Approval`, 7 actuals at `Pending Farm Manager`), and none on
live's master plans, assigners or payments.

## Design

### Three derived facts, computed once

Each screen computes these at module top from the same stage rows the workflow
generator reads:

| name | meaning |
|---|---|
| `STATE_OF[step]` | the state this step waits in |
| `NEXT[step]` | the state of the next **enabled** step, or the terminal state |
| `LIVE_STATES` | every in-flight state, for list filters |

This is what makes the change tractable. It is not 189 independent edits: it is
three values plus mechanical substitution, and the three come from one place.

`NEXT` is the same computation `plan_workflow` already performs, so it is lifted
into a shared helper and both callers use it -- the workflow generator and the
screens cannot then disagree, which is exactly the failure this fixes.

### The approve actions stop naming states

    elif action == "a_fm_approve":
        if not ENABLED["assigner_farm_manager"]:
            out["error"] = "..."
        elif cur_ws != STATE_OF["assigner_farm_manager"]:
            ...
        else:
            frappe.db.set_value(..., NEXT["assigner_farm_manager"], ...)

Each action guards on its own step being enabled, so a screen cannot reach a step
the chain has dropped. The role checks (`is_hr_head` and friends) are unchanged;
they simply are not reached for a disabled step.

### Reads use a superset, writes use the chain

`LIVE_STATES` is the configured in-flight states **plus** any state actually
present in the data. Without the second half, a document approved under an older
chain disappears from lists and dashboards the moment a step is switched off --
turning a configuration change into apparent data loss. Writes follow the
configured chain only.

This is asymmetric on purpose and is the one part of the design not driven by a
choice the user made; it is recorded here so it can be argued with.

### Settings refuses an unsafe switch

Switching off a step with documents waiting in its state is refused on save,
naming the step and the count:

    Assigner: HR Head cannot be switched off while 4 documents are waiting for
    it. Approve or reject them first, or leave the step on.

Nothing is moved automatically and no approval is silently bypassed. The cost is
that a busy step must be cleared before it can be switched off, which was the
accepted trade.

### Where the chain comes from, in each world

**The app** (staging, and any v16 site): `get_config()` gains the three derived
values from the `approval_stages` rows. `port_app.py` already strips the mirror's
module-top constants and rebuilds them from `get_config()` -- the same mechanism
that gives every ported module its `FARMS` -- so the app side needs no new
plumbing beyond the config keys.

**The mirror** (live): live has **none** of the configuration tables. No
`Work Management Approval Stage`, no `Work Management Stage Approver`, no
`WM Farm`. So the mirror computes the three facts from that table *if it exists*
and otherwise falls back to the chain it runs today, hardcoded exactly as now.

**Live therefore behaves identically until somebody creates the table there.**
That is the same approach taken for `asg_show_today_presence`, and it is the
property that makes this safe to push: the change cannot alter live's pipeline on
the day it lands.

Enabling it on live is a separate, deliberate step, out of scope here: create the
child doctype and the `approval_stages` field as Custom Fields, seed them from
live's current chain so day one changes nothing, then the switches work there
too. It must not be bundled with this work -- one of these two changes altering
live's approval chain is enough risk at a time.

### The two dead consultant controls, removed

Both are removed. Neither is read by anything -- verified at zero references
across the app, the mirror scripts and the web pages:

- `require_consultant_approval`, a checkbox in Settings labelled *"Require
  consultant approval for future-week plans"*, default **on**. It promises a rule
  that does not exist, and somebody will tick it and expect an effect.
- `planner_weekly_consultant`, a stage of kind `Gate`. `chain_for()` filters
  Gates out of the workflow (`approvals.py:272`), and nothing else reads the kind,
  so a Gate stage is inert. The `Gate` option is removed from the `kind` Select
  along with it, and the row sitting on `kaitet.local` is removed by a patch.

What is kept, untouched, is the consultant control that works: `consultant_state`
on each **Master Plan Activity**, so a consultant approves individual activities
and the planner only offers tasks whose activity is `OK`. Also kept is
`Master Plan: Consultant`, a real workflow step, which stays switchable.

## Not in scope

- **No new steps.** No HR Head or GM on the Planner, no FM on the Master Plan.
  The nine steps that exist become switchable; the matrix is not filled in. Doing
  this work first makes that a smaller follow-on, because the screens will already
  be driven by the chain rather than by fixed state names -- what remains is a
  generic approve action per screen in place of the three named ones.
- **Enabling the switches on live**, per the previous section.
- **The farm dimension.** Per-farm transitions and the stranded-farm check are
  untouched here; they are the subject of
  `2026-08-31-rbac-farm-scoping-design.md`.

## Testing

The derived maps are pure, so they carry the weight:

- a chain with a middle step off -- the step before joins the step after
- two consecutive steps off
- the **last** optional step off -- the step before chains to the terminal state
- every optional step off -- Submit chains straight to terminal
- a required step is never off, whatever the row says
- `LIVE_STATES` includes a historical state present in data but absent from the
  configured chain

Then:

- the Settings validation, with and without documents waiting in the step
- **a source-level test that no pipeline state literal survives in the approve and
  guard paths**, in the style of the test asserting every query using `%(plan)s`
  is passed it -- that one caught three misses where the same query appeared at
  four indentations, and this substitution has the same hazard at sixty times the
  scale
- a test that the mirror's fallback chain matches the shipped catalogue, so the
  two cannot drift while live is running on the fallback

Driven on `kaitet.local` end to end: switch off `Assigner: HR Head`, confirm the
screen's FM approve lands a document in `Pending GM` and that the desk workflow
agrees, then switch it back on and confirm the chain is restored.

## Risks

| risk | disposition |
|---|---|
| A substitution is missed and a screen still writes a literal state | the source-level test above; it is the known failure mode of this exact kind of change in this codebase |
| Historical documents vanish from lists | `LIVE_STATES` is a superset, with a test |
| Live's pipeline changes on deploy | it cannot: live has no stage table, so the mirror runs its fallback until one is created there |
| A step is switched off under waiting documents | refused on save, naming the count |
| The screens and the workflow generator disagree about the next state | both call the same helper; that they were two implementations is the present bug |
| `NEXT` computed per request adds a query | one read of a child table, resolved once at module top, as `FARMS` already is |

## Open questions

1. **Should a disabled step's role keep its screen buttons for other purposes?**
   `stage_role()` is also read by `hr_head_roles` in `get_config()`, which the
   screens use for things other than the transition. Switching a step off should
   probably not revoke that role's other abilities, but it is worth confirming
   against the screens once the work starts.
2. **`Payment: Accounts` is `required=True`.** Nothing in the request asks to
   switch payment approval off, so this stays -- but it is the one step whose
   requiredness is a policy choice rather than a structural necessity, unlike the
   Submit steps.

---

## Built — 2026-09-01

Three refinements to the design above, each because building it showed the spec
was reaching for something more expensive than the problem needed.

**The read filters were left alone.** The spec said reads need a superset that
includes switched-off steps' states. They already are one: the filters name every
state the shipped chain has, so switching a step off leaves its state listed and
matching nothing. Converting a hundred and fifty SQL sites would have been risk
without behaviour. What makes that safe is a test asserting the filters remain a
superset of the configured states -- add a step with a new state and it fails,
naming the filters that need it. `wm_dashboard` was dropped from the work
entirely on the same reasoning: all 57 of its mentions are read filters.

**`pipeline_states()` returns groups, not a list.** The screens' filters mean
different things -- waiting, active, editable -- and handing them one flat list of
every state would have silently widened `IN (...)` to include drafts and rejects.
That is how a "live work" list starts showing abandoned drafts.

**The mirror's fallback is a literal, not a read of the table.** The spec had it
read the Approval Stage table where one exists. That would mean resolving "what
comes after this step" a second time inside the sandbox, with no imports and no
`def` -- two implementations of the rule this change exists to unify. So live gets
a literal of the chain it runs today and its behaviour cannot change; giving live
the switches means handing it the table and the app's config, still a separate job.

`wm_payment` was also left out: its only step is `Payment: Accounts`, which is
required and can never be switched off.

**Verified on `kaitet.local`, against real documents:**

| | result |
|---|---|
| HR Head on | FM approve to `Pending HR Head` |
| switch off with 1 waiting | refused: *"cannot be switched off while 1 document is waiting for it"* |
| HR Head off | FM approve to `Pending GM` |
| the HR action, off | *"The HR Head step is switched off for this project."* |

The screen and the generated workflow agree in every configuration, across all
four chains, independently -- Master Plan, Planner, Assigner and Actuals each
reshape without touching the others. 689 tests pass; the port reports all ten
modules matching.

**One bug caught in the building**, of the same shape as the outage the day
before: a script failed partway and left `wm_planner` referencing `STAGE_NEXT`
without defining it -- a NameError that would have appeared only on live. The
mirror integrity test now covers these constants, confirmed by deleting the fix
and watching it fail.

**Still open**, unchanged: giving live the table so its switches work, and the
full role matrix (HR Head on the Planner, FM on the Master Plan). The second is
now much cheaper than it was, because the screens are driven by the chain rather
than by fixed state names -- what remains is a generic approve action per screen
in place of the three named ones.
