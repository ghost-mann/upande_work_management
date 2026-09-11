# Altura: configuring the approval chains

*Rewritten 2026-09-11 for the chain the client confirmed. This supersedes the
2026-09-08 draft, which was built from a Phillip/HR reading that has since been
corrected — the names, the order and which steps are off have all moved, so read
this rather than remembering that.*

A runbook, not a script: every step below is done in Work Management Settings on
the Altura site. Nothing here needs a deployment of its own once the app upgrade
has landed. **No part of this has been executed on any site.**

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

   The steps this runbook turns off are `Planner: HR Approval` (already off),
   `Assigner: HR Head`, `Assigner: GM` and `Actuals: GM`. Any assignment or
   actuals document sitting in `Pending HR Head` or `Pending GM` must be
   approved or rejected through first. This is correct behaviour — the refusal
   is protecting work in flight — so plan the change for a moment when those
   queues are empty rather than trying to force it.

   With bulk approval now on every approvals tab, draining a queue is one pass:
   tick the header checkbox, press **Approve selected (N)**, and read the result
   summary. Anything that refuses is listed by name with its own reason.

**The cosmetic defect noted in the 2026-09-08 draft is fixed.** The master plan
refusals name the configured step's role now, so a chain where somebody other
than a general manager takes `masterplan_gm` reads correctly.

---

## The four people

| Person | Does | Email |
|---|---|---|
| **Olger** | raises master plans and planner requests; approves actuals first | ⬜ *to confirm on Altura* |
| **Daniel** | raises assignments; enters actuals | ⬜ *to confirm on Altura* |
| **Philip** | approves planner requests, assignments, and actuals finally | ⬜ *to confirm on Altura* |
| **Yvonne (HRM)** | payment | ⬜ *to confirm on Altura* |

> **The four emails are the one thing this runbook cannot supply.** The
> 2026-09-08 draft carried `nyabisi20@gmail.com` for Olger (a personal gmail,
> never confirmed) and `daniel@alturablooms.ke` for Daniel. Confirm all four
> against Altura's User list before creating any Stage Approver row — a row
> naming a user who does not exist will not save, and a row naming the *wrong*
> user grants that person an approval role.

Each person needs a **role** as well as a user. This app ships no roles on
purpose (see `test_no_shipped_roles`): a fresh install has every step sitting
with System Manager until somebody maps it. Use Altura's existing roles where
they exist and create only what is missing.

---

## The chains

### 1. Planner — Olger raises → Philip approves

| Stage row | On | Role |
|---|---|---|
| `planner_submit` | on (forced) | **Olger's role** |
| `planner_farm_approval` | on | **Philip's role** |
| `planner_hr_approval` | **off** (ships off) | — |

`planner_hr_approval` is the step added in `f3981db`. It ships switched off and
stays off here: this chain is two steps, not three. It is left in place rather
than deleted so a later decision to add an HR sign-off is a toggle.

`planner_farm_approval` is **farm-scoped** — either give every farm its own
Stage Approver row or leave the step with no rows at all so its own role covers
them all. Settings refuses a farm-scoped step that names approvers for some
farms but not others, and the error names the farms that would be left with
nobody.

### 2. Assigner — Daniel raises → Philip approves

| Stage row | On | Role |
|---|---|---|
| `assigner_submit` | on (forced) | **Daniel's role** |
| `assigner_farm_manager` | on | **Philip's role** |
| `assigner_hr_head` | **switch OFF** | — |
| `assigner_gm` | **switch OFF** | — |

Two steps become one approval. Drain `Pending HR Head` and `Pending GM` first.

### 3. Actuals — Daniel enters → Olger approves → Philip approves final

| Stage row | On | Role |
|---|---|---|
| `actuals_submit` | on (forced) | **Daniel's role** |
| `actuals_farm_manager` | on | **Olger's role** |
| `actuals_hr_head` | on | **Philip's role** |
| `actuals_gm` | **switch OFF** | — |

This is the one chain with two approvals, and the only one where Olger both
*enters nothing* and *approves first*. Note the label mismatch: the step keyed
`actuals_hr_head` is taken by Philip, who is not an HR head. Rename it with
`stage_label` — see below — so the queue chip on the Actuals screen reads
sensibly.

`actuals_farm_manager` is farm-scoped; the same all-or-nothing rule as the
planner's applies.

### 4. Payment — Yvonne (HRM)

Which setting Yvonne needs depends on which payment path Altura runs:

- **Payroll feed mode** (`payment_mode = Payroll feed`): there is no accounts
  release step. Yvonne needs the capability that lets her run the weekly feed —
  grant her role `send_payment` and `handle_payments` in *Who may do what*. The
  `payment_accounts` stage is not used on this path.
- **Accounts release mode** (the default): `payment_accounts` is the stage, and
  Yvonne's role goes on it.

**Decide the mode before configuring this one**, because the two are mutually
exclusive by construction and the controls for the other path are hidden and
refused.

### 5. Master Plan — not in the client's list

The client's action points do not mention master plans. The 2026-09-08 draft
assumed Olger → Philip → HR; **that assumption is withdrawn rather than
carried forward.** The current mapping notes are kept here for reference:

| Stage row | On | Role (draft, unconfirmed) |
|---|---|---|
| `masterplan_submit` | on (forced) | Olger's role |
| `masterplan_consultant` | on | Philip's role |
| `masterplan_gm` | on | HR's role |

> ⬜ **Ask before applying any of this.** A master plan is the budget every
> weekly request draws against, so who approves one is a bigger decision than
> who approves a week's work. Until it is confirmed, leaving these three at
> their current values is the safe state.

---

## Label renames

The step *keys* are fixed; the labels are not. Rename via `stage_label` so the
screens read the way Altura talks:

| Key | Ships as | Suggest |
|---|---|---|
| `planner_farm_approval` | Planner: Farm Approval | Planner: Philip |
| `assigner_farm_manager` | Assigner: Farm Manager | Assigner: Philip |
| `actuals_farm_manager` | Actuals: Farm Manager | Actuals: Olger |
| `actuals_hr_head` | Actuals: HR Head | Actuals: Philip (final) |

The Stage Approvers picker stores a **label**, so renaming a step changes what
that picker offers — rename first, then create the approver rows, or the rows
will name labels that no longer exist.

---

## Capabilities are separate, and easy to forget

The approval stages decide **who approves**. A second table decides **who may
act at all**, and a chain configured perfectly will still look broken if these
are wrong:

| Capability | Grant to |
|---|---|
| `edit_master_plan` | Olger's role |
| `enter_work` | Daniel's role (assignments and actuals data entry) |
| `set_rates` | whoever owns rates at Altura |
| `send_payment` | Yvonne's role |
| `handle_payments` | Yvonne's role |

`enter_work` grants no approval of any kind, and `edit_master_plan` does not
grant approving one — that is what the stages above are for.

---

## Reporting access

The **Worker Task Day** report grants itself to every role the configured chain
names for an approval step, on each `bench migrate` — so once the chains above
are set, Philip's and Olger's roles can open it without a separate step. The
report ships to HR User, HR Manager and System Manager, and nothing is ever
removed. See `work_management/report_access.py`.

The report carries a **Daily summary** grouping and a chart, so the client's
"daily summary, exported via excel or shown as graphs" is that one report rather
than three things to maintain.

---

## After saving

- The five workflows regenerate from these two tables, on save and on every
  `bench migrate`.
- Approvers get the ordinary Frappe experience: action buttons on the document,
  the awaiting-approval inbox, and the notifications.
- **Verify:** open *Work Management Settings → Approvals*, confirm each chain
  shows the steps above with the right On flags, and walk one throwaway request
  from Draft to Approved to see it stop where it should.
- **Reordering caveat:** if anyone ever drags a *shipped* step to a new
  position, `seed_stages()` re-emits shipped rows in catalogue order on the next
  `bench migrate` and the reorder is silently lost. None of the chains above
  needs a reorder, so this does not bite here — but do not rely on dragging
  shipped rows to express a chain.
