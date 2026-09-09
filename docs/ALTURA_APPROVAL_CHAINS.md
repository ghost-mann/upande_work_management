# Altura: configuring the four approval chains

*Prepared 2026-09-08. A runbook, not a script — every step below is done in
Work Management Settings on the Altura site. Nothing here needs a deployment of
its own once the app upgrade has landed.*

## Read this first

**Two prerequisites, and the first one blocks everything.**

1. **The app upgrade must be on Altura before any of this exists to configure.**
   Live's Work Management schema predates `Work Management Approval Stage` and
   `Work Management Stage Approver` — the two tables this whole runbook edits.
   Until the upgrade lands there is nothing to open. Check
   *Work Management Settings → Approvals* shows two grids before starting.

2. **Drain the queues before switching a step off.** Settings refuses a
   configuration that would strand a document:

   > *{step} cannot be switched off while {n} {is/are} waiting for it*

   The four steps this runbook turns off are `Assigner: HR Head`,
   `Assigner: GM`, `Actuals: HR Head` and `Actuals: GM`. Any assignment or
   actuals document sitting in `Pending HR Head` or `Pending GM` must be
   approved or rejected through first. This is correct behaviour — the refusal
   is protecting work in flight — so plan the change for a moment when those
   queues are empty rather than trying to force it.

**One known cosmetic defect.** The Master Plan chain below asks the step keyed
`masterplan_gm` to be taken by HR. It works — the permission check reads the
step's *configured role* — but one hardcoded refusal message still says
*"Only the general manager can approve a master plan."* Fixing that string
requires a change to a generated `api/` module and is deferred to the mirror
session (see the deferred-work list in the sprint report). Everything else
renames cleanly via `stage_label`.

---

## The target chains

| Document | Raises | Then | Then |
|---|---|---|---|
| Master Plan | Olger | Phillip | HR |
| Planner | Olger | Phillip | HR |
| Assigner | Daniel | Phillip | — |
| Actuals | Olger | Phillip | — |

Two facts about the mechanism, because they explain every choice below:

- **Order is the rows' own order.** `configured_stages()` sorts the Approval
  Stages grid by row position, so a chain's shape is configuration. None of the
  four targets needs a reorder, though — see below.
- **Submit steps cannot be switched off.** They carry `required`, so "who
  raises" is set by the *role on the submit step*, not by turning anything off.

---

## 1. Master Plan — Olger → Phillip → HR

No reorder and no step switched off. The shipped order is already
Submit → Consultant → GM, which *is* raise → Phillip → HR once the roles move.

| Stage row | On | Role | Rename `stage_label` to |
|---|---|---|---|
| `masterplan_submit` | on (forced) | **Olger's role** | — |
| `masterplan_consultant` | on | **Phillip's role** | `Master Plan: Phillip` *(or leave)* |
| `masterplan_gm` | on | **HOD HR** | **`Master Plan: HR`** |

Renaming `masterplan_gm`'s label matters more here than elsewhere: leaving it
reading "GM" while HR takes it is the kind of mismatch that gets reported as a
bug. The underlying key stays `masterplan_gm` — that is what the screens and
every existing document reference, and it must not change.

## 2. Planner — Olger → Phillip → HR

This is the chain that needed code. The Planner shipped with **one** approval
step; a second, `planner_hr_approval`, was added to the catalogue in this sprint
and **ships switched off**, so no existing site's chain changed. Altura switches
it on.

| Stage row | On | Role | Rename `stage_label` to |
|---|---|---|---|
| `planner_submit` | on (forced) | **Olger's role** | — |
| `planner_farm_approval` | on | **Phillip's role** | — |
| `planner_hr_approval` | **switch ON** | **HOD HR** | — |

With it on, `Planner: Farm Approval` leads to `Pending HR Approval` instead of
straight to `Approved`, and HR's approval is what finishes the chain. The
`Pending HR Approval` Workflow State record is created automatically when the
workflows regenerate.

The planner **web screen** takes it too. Its Approvals tab is keyed off the
configured chain rather than off `planner_farm_approval`: a request waiting in
`Pending HR Approval` is offered to holders of the step's role with an **HR
Approve** button, a Step column appears saying which step each request waits in,
and the farm-scoped step keeps its farm scoping while the HR step -- which is
not farm-scoped -- does not inherit it. Somebody holding neither role is told
which roles the chain runs on rather than shown an empty list.

With the step **off** the screen is byte-for-byte the experience it was: one
approval, one button reading Approve, no Step column.

*(This was deferred when the chains were written, on the grounds that the screen
needed a generated `api/` module. On the `altura` branch `api/` is source --
see `docs/ALTURA_FORK.md` -- so it is done here rather than in a mirror
session.)*

## 3. Assigner — Daniel → Phillip only

| Stage row | On | Role |
|---|---|---|
| `assigner_submit` | on (forced) | **Daniel's role** |
| `assigner_farm_manager` | on | **Phillip's role** |
| `assigner_hr_head` | **switch OFF** | — |
| `assigner_gm` | **switch OFF** | — |

Farm Manager approval then goes straight to `Assigned`.

## 4. Actuals — Olger → Phillip only

| Stage row | On | Role |
|---|---|---|
| `actuals_submit` | on (forced) | **Olger's role** |
| `actuals_farm_manager` | on | **Phillip's role** |
| `actuals_hr_head` | **switch OFF** | — |
| `actuals_gm` | **switch OFF** | — |

Farm Manager approval then goes straight to `CONFIRMED`.

> Note that Olger both **enters** actuals and **raises** master plans and
> planner requests here. The payment audit's `self_approved` check flags actuals
> where the person who entered the quantities also gave the approval — with
> Phillip approving, that check stays quiet, which is the point of it.

---

## Stage Approvers rows to create

One row per person per step. The row stores the stage's **label**, optionally a
farm, the user, and optionally a role override. Saving grants each listed person
the role their stage runs on; removing a row revokes what it granted, unless
another row still grants it.

Leaving **Farm** empty means the person acts on every farm. Only
`planner_farm_approval`, `assigner_farm_manager` and `actuals_farm_manager` are
farm-scoped; on those, either give every farm its own row or leave the step with
no rows at all so its own role covers them all. **Settings refuses to save a
farm-scoped step that names approvers for some farms but not others** — the
error names the farms that would be left with nobody.

| Stage label | User | Farm | Confirmed? |
|---|---|---|---|
| `Master Plan: Submit` | `nyabisi20@gmail.com` | — | ⚠️ Olger's address is a personal gmail — **confirm** |
| `Master Plan: Phillip` *(consultant)* | `‹phillip@alturablooms.ke›` | — | ❌ **no Phillip user exists — needed** |
| `Master Plan: HR` *(gm)* | `‹hr@alturablooms.ke›` | — | ❌ **HR user unidentified — needed** |
| `Planner: Submit` | `nyabisi20@gmail.com` | — | ⚠️ confirm |
| `Planner: Farm Approval` | `‹phillip@…›` | leave empty, or one row per farm | ❌ needed |
| `Planner: HR Approval` | `‹hr@…›` | — | ❌ needed |
| `Assigner: Submit` | `daniel@alturablooms.ke` | — | ✅ exists (Daniel Mwangi Muchiri) |
| `Assigner: Farm Manager` | `‹phillip@…›` | leave empty, or one row per farm | ❌ needed |
| `Actuals: Submit` | `nyabisi20@gmail.com` | — | ⚠️ confirm |
| `Actuals: Farm Manager` | `‹phillip@…›` | leave empty, or one row per farm | ❌ needed |
| `Payment: Accounts` | *(unchanged)* | — | — |

**Still needed before this can be applied:** Phillip's email and full name; the
HR approver's email; and confirmation that `nyabisi20@gmail.com` is the right
account for Olger rather than an `@alturablooms.ke` address.

---

## Capabilities are separate, and easy to forget

The approval stages decide **who approves**. A second table decides **who may
act at all**, and a chain configured perfectly will still look broken if these
are wrong:

| Capability | Grant to |
|---|---|
| `edit_master_plan` | Olger's role |
| `enter_work` | Olger's role (assignments and actuals data entry) |
| `set_rates` | whoever owns rates at Altura |
| `send_payment` | Accounts |
| `handle_payments` | Accounts, HR |

`enter_work` grants no approval of any kind, and `edit_master_plan` does not
grant approving one — that is what the stages above are for.

---

## After saving

- The five workflows regenerate from these two tables, on save and on every
  `bench migrate`.
- Approvers get the ordinary Frappe experience: action buttons on the document,
  the awaiting-approval inbox, and the notifications.
- **Verify:** open *Work Management Settings → Approvals*, confirm the Planner
  now lists two enabled approval steps, and walk one throwaway planner request
  from Draft to Approved to see it stop at HR.
- **Reordering caveat:** if anyone ever drags a *shipped* step to a new
  position, `seed_stages()` re-emits shipped rows in catalogue order on the next
  `bench migrate` and the reorder is silently lost. None of the four chains
  above needs a reorder, so this does not bite here — but do not rely on
  dragging shipped rows to express a chain.
