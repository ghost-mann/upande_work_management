# One table of grants, and a separate one for the chain's shape

*2026-09-03*

> **Amends** `2026-08-31-rbac-farm-scoping-design.md`. That spec's leak fix and
> its User Permission work stand unchanged and are already shipped. What this
> document changes is one of its conclusions: that farm scoping for *approval*
> should be read from Frappe's User Permissions. Measurement says those
> permissions express visibility, are wider than approval authority on every
> person who has actually approved anything, and cannot serve as the boundary
> without widening it. Approval authority gets a record of its own.

## The change in one sentence

`Approval Stages` and `Capabilities` become one table of grants —
`(action, role, farm)` — because "may approve a plan for Lokitela" and "may set
rates for Lokitela" are the same sentence; and what is left of `Approval Stages`,
which steps are on, becomes a table about the chain's shape with no roles in it.

## Why, starting with what is wrong today

The app answers "who may do what" with three tables and two unrelated
mechanisms.

| table | shape | can express a farm? |
|---|---|---|
| Approval Stages | 14 rows, one per stage: stage → role, plus On | no |
| Stage Approvers | stage → farm → **person** → role override | yes, per person |
| Capabilities | 5 rows: capability → role | **no** |

Three of the 14 stages are farm-scoped. The farm dimension reaches them only
through Stage Approvers, and it does so by **spelling the farm into a role's
name**: `Farm Manager Lokitela`, `Farm Manager Endebess`, `Farm Manager Valle` —
the last misspelled, and unrenameable because people hold it. `kaitet.local`
carries ten such roles.

Capabilities cannot express a farm at all. "Set task rates" is all sixteen farms
or none. A farm cannot be given authority over its own rates, and there is no
row shape in which to say so.

### The measured part, because it is the part with consequences

**The approval role is far too broad.** `Planner: Farm Approval`,
`Assigner: Farm Manager` and `Actuals: Farm Manager` are all configured to plain
`Farm Manager`. On `kaitet.local`:

- **129 enabled users hold `Farm Manager`**; **97 of them have no Farm User
  Permission**
- **40 Role Profiles hand it out** — to Intake QC, Procurement approvers, CFU
  technicians, Harvest Managers, HR, Upande Team
- only **4 of 16 farms** have a Stage Approver row, so the other twelve already
  fall back to plain `Farm Manager` for approvals

On this site that role means *"works at a farm"*, not *"manages a farm"*. So the
per-farm roles were doing two jobs, not one: encoding the farm dimension **and**
narrowing an over-broad role. Only the first has a replacement in the RBAC spec.

**Nine people have ever approved a Planner.** One hundred and twenty-nine may.

**The two mechanisms disagree, and Frappe's is the wider one.** For each of those
nine approvers, what their per-farm role says against what their User Permissions
allow:

| person | role name says | User Permissions say |
|---|---|---|
| bramuel@lokitelaorchards.com | Lokitela | Lokitela, **Saboti**, **Vale** |
| ogola@lokitelaorchards.com | Saboti | **Lokitela**, Saboti, **Vale** |
| kibett@lokitelaorchards.com | Valle | **Endebess, Lokitela, Saboti, Vale** |
| guchu@endebesscoffee.com | Endebess | Endebess, **Vale** |
| tarus@endebesscoffee.com | Endebess | Endebess, **Vale** |
| pkatule@lokitelaorchards.com | Lokitela | **none — so all 16** |
| austin@upande.com | *no per-farm role* | none |
| gibertcheptinde@endebesscoffee.com | *no per-farm role* | none |
| godfreykisaka@endebesscoffee.com | *no per-farm role* | none |

Every measurable person **gains** farms in the translation. Six of six. The three
with neither mechanism approve through the System Manager / GM bypass.

This is not carelessness by whoever maintains those permissions. A Farm User
Permission answers *"whose records may I see"*, and being able to see Vale's work
is a reasonable thing for Lokitela's manager to need. It is simply not an answer
to *"whose work may I approve"*, and nothing in Frappe is.

**The RBAC spec's audit could not have caught this.** It asked whether restricted
users had worked a farm they are *not* permitted — 0 of 95. Where permissions are
wider than authority, that question passes vacuously. It measured the wrong
direction.

### Role Profiles, which decide whether any of this is reachable

390 of 454 enabled users have a Role Profile; 18 of the 19 per-farm-role holders
do. Frappe replaces a user's roles from their profile on every save, which is why
`sync_roles()` is not merely a boundary violation but ineffective.

**13 Role Profiles name a per-farm role**, including
`Farm Manager Kaitet (Valle)`, `Agriculture Production Supervisor-Approver
(Torongo)`, `Sales - Approver (Karen)` and `Maintenance Checksheets - Approver`.
Retiring those roles is partly an edit to profiles that mix Work Management with
Sales, Procurement and Maintenance. Those are the organisation's records. This
app lists them and touches none of them.

## Design

### Two tables, answering two different questions

**Approval Steps** — the chain's shape. One row per stage: the stage, its
document type, and `On`. **No role column.**

Switching a step off relinks the chain so the step before it approves straight
through to the next one. That is a property of the chain, not of anybody's
authority, and it is why `On` cannot live on a grant: a capability has no chain to
relink, so the column would be meaningless for half the rows of a merged table.
Five of the 14 stages are Submit steps and cannot be switched off.

**Grants** — who may do what, and where. One row is
`(action, role, farm)`:

| Action | Role | Farm |
|---|---|---|
| Planner: Farm Approval | Farm Supervisor | Lokitela |
| Planner: Farm Approval | Farm Supervisor | Endebess |
| Actuals: Farm Manager | Farm Supervisor | *(blank — every farm)* |
| Set task rates | General Manager | *(blank)* |
| Send a payment run | Accounts Manager | *(blank)* |
| Enter work | HR Clerk | Saboti |

`action` is drawn from one catalogue that is the union of the 14 stages and the 5
capabilities. They belong in one list because they are one question. A blank farm
means every farm, which is what all five capabilities are today and what a
non-scoped stage is.

Adding a second row with the same action grants it to another role — precisely how
`Capabilities` already behaves. This design widens that behaviour to approval
steps and adds the farm column, rather than inventing anything.

### The two scoping mechanisms compose, each doing its own job

    User Permission  ->  which farms' records may I SEE     (Frappe, everywhere)
    Grant farm       ->  which farms may I APPROVE or ACT for  (this app)

ANDed. Visibility stays entirely Frappe's, on every path — list views, reports,
the API, the desk — and the shipped `farms_respect_user_permissions` switch and
`permitted_farms()` are unchanged by this document. Authority becomes an explicit
row, because no Frappe mechanism records it and inferring it from visibility
widens six of six people.

This is the departure from the RBAC spec, stated plainly: **that spec's rule was
"maintain no parallel notion of farm scoping", and this keeps one.** The rule was
right in general and wrong for authority specifically. The distinction the spec
missed is that it treated one question where there are two.

### Generated workflows

A grant with a farm still produces a conditional transition —
`doc.farm == "Lokitela"` — but generated from a **grant row** rather than from a
role whose name happens to contain a farm. One transition per distinct
`(action, role, farm)` grant, which is what `transition_groups()` already
computes; it changes where it reads its pairs from, not what it emits.

`kaitet.local` today has 49 transitions across 5 workflows, 24 of them
farm-conditioned. The count after migration is a function of how the grants are
populated, not of this design.

### Reading a grant

**The function already exists.** `capabilities.may(key, user_roles, config=None)`
answers exactly this question for the five capabilities today, and it was written
in the shape this design needs: it takes plain arguments and a `{key: [roles]}`
dict as `get_config()` hands it to the screens, touches no Frappe API, and so
already runs in the Server Script sandbox unchanged.

It gains a farm:

    may(key, user_roles, config=None, farm=None) -> bool

and its catalogue widens from the 5 capabilities to all 19 actions. The
`config` payload widens with it, from `{key: [roles]}` to a mapping that carries
each granted role's farms; a blank farm list means every farm, so today's five
capabilities keep their exact current meaning through the migration.

`roles_for()` gains the same farm argument. The stage-role checks and
`config._stage_roles()` collapse into these two.

`ALWAYS = "System Manager"` keeps its current meaning — System Manager passes
every gate, and an action with no grant at all falls back to the shipped default
rather than to nobody, so a site part-way through configuration is never locked
out. Both behaviours are `capabilities.py`'s today and both are preserved.

That this function already exists, in a shape that already ports, is the main
reason to believe the merge is the smaller change rather than the larger one:
capabilities were built this way, and approval stages are the ones that need to
move.

## Migration from the three tables

Mechanical, and every part of it is a widening or a narrowing that has to be
seen rather than assumed:

1. **Capabilities** → grants with a blank farm. Exact, five rows, no decision.
2. **Approval Stages** → for each stage, a grant of its configured role with a
   blank farm; plus an Approval Step row carrying `On`. Exact, no decision.
3. **Stage Approvers** → **not translated automatically.** Its 27 rows on
   `kaitet.local` name 9 people across 4 farms with per-farm role overrides. A
   person's row cannot become a role grant without deciding which role, and the
   role it names is one of the ten being retired. This is the reconciliation
   below, and it is a human decision per person.
4. **The ten per-farm roles** are left in place, granted to nobody by this app,
   and listed for removal by whoever owns the 13 Role Profiles that name them.
   This app has never created them and does not delete them.

## Reconciliation, and the gate

Steps 1 and 2 are safe and shippable. Steps 3 and 4 are not, and the difference
is measured, not felt: on the nine real approvers the two existing mechanisms
disagree in six cases and are absent in three.

**`farm_approval_reconciliation.py`**, alongside the existing
`farm_permission_audit.py`, read-only, runnable per site:

    bench --site <site> execute work_management.farm_approval_reconciliation.print_report

Per person who holds a per-farm role or appears in Stage Approvers:

| column | meaning |
|---|---|
| person | user |
| role scope | farms implied by their per-farm role names |
| permission scope | farms from their Farm User Permissions |
| approved | whether they have actually approved anything, and how much |
| verdict | `agrees` / `wider` / `narrower` / `missing` / `absent` |

`wider` is the case the RBAC spec's audit could not see and is expected to
dominate. Every row that is not `agrees` is a question for a person: which farms
should this grant name?

**The gate.** The migration patch for steps 3 and 4 refuses to run while any row
is unsettled, and names the outstanding ones. Settled means a human has recorded
the intended farms — as grants. The report is the input to a decision, never the
decision.

## The narrow role, which is a prerequisite and not code

The three farm-scoped stages must be pointed at a role that means *"manages a
farm"* before the per-farm roles retire, or 97 people without a Farm User
Permission acquire approval on the four farms currently protected by name.

Choosing that role and putting the roughly 19 people in it is the organisation's
work, through the Role Profiles that already carry role assignment here. **This
app writes no roles and no User Permissions**, which is the one rule of the RBAC
spec this document keeps without qualification.

Sizing evidence: 9 people have ever approved a Planner; 19 hold a per-farm role.
The narrow role's population is that order of magnitude, not 129.

## What this deletes

- `Stage Approvers`' `Approver` and `Role override` columns, and the per-person
  design behind them
- `config._farm_approver_role()` — the `{farm: role}` map, whose only reader is
  the screens' `AP_FARMS`, which reads `may()` instead
- `approvals.approver_users()`, `_desired_grants()`, `sync_roles()`,
  `managed_roles()` — role granting, already ineffective against Role Profiles
- `config._stage_roles()`, which answered "is this user the HR head?" by
  collecting stage roles and overrides
- the stranded-farm validation: a farm is not "covered by an approver row", it is
  covered by a grant
- the `Role` column on `Approval Stages`, which moves to Grants

## Rollout

1. **Ship the reconciliation report.** Read-only. Run it on `kaitet.local` and on
   staging, whose consultant holds a Lokitela-only permission while working more
   than Lokitela.
2. **Ship the two tables and migrate steps 1–2** — capabilities and stage roles,
   both exact. Behaviour identical; `may()` answers what the old readers answered.
3. **The organisation settles the report and names the narrow role.** Not code.
4. **Migrate steps 3–4 behind the gate**, retire the per-farm generation, delete
   the list above.
5. **The mirror**, in step with the app, kept honest by `check_ported.py`. `may()`
   must be expressible in the Server Script sandbox — no imports, no `def` — which
   is why it takes plain arguments and returns a bool, the same discipline that
   made `permitted_farms()` portable.

## Risks

| risk | disposition |
|---|---|
| The migration widens approval authority | steps 1–2 are exact; 3–4 are gated on a per-person human decision |
| 97 `Farm Manager` holders become approvers | the narrow role is a prerequisite of step 4, not a follow-up |
| A parallel scoping mechanism drifts from Frappe's | they answer different questions by design, and the report is the standing instrument for comparing them |
| Deleting per-farm roles breaks 13 Role Profiles | this app does not delete them; it lists them and leaves them to their owner |
| The sandbox cannot express `may()` | it already runs there: `capabilities.may()` takes scalars and a dict and calls no Frappe API. The farm argument adds no new capability requirement |
| `On` semantics change | Approval Steps keeps the column and the relinking untouched; only roles move out |

## What this does not solve

- **The stage catalogue is still code.** Steps can be switched off, not added, and
  a hand-added row is deleted by the next migrate. Deliberately out of scope:
  folding it in doubles the size and the risk. It remains the larger portability
  problem the RBAC spec named.
- **The farm-scope bypasses.** `AP_BYPASS` and `fmbypass` — "may this person act
  outside their farm" — become a grant with a blank farm, which is the right
  shape, but three of nine current approvers rely on the bypass and are not
  covered by any grant yet. The reconciliation report's `absent` verdict is where
  they surface.
- **Raw SQL stays raw.** This changes who may act; it does not make the screens
  permission-aware in general.
- **Live is not enforcing per-person farm scoping.** Unchanged from the RBAC
  spec: live runs Server Scripts where `FARMS` is a hardcoded four-farm list.

## Open questions

1. **Which role, and does it exist?** No role on `kaitet.local` currently means
   "manages a farm" with a population near 19. It may have to be created, which
   is a Role Profile change across 13 profiles.
2. **One farm per row, or several?** One row per farm is proposed and is what the
   rest of this document assumes: it keeps the grid readable and makes each row
   map to exactly one generated transition. The cost is five rows for a
   five-farm manager, which is the case for at least three people on
   `kaitet.local`.
3. **Do the three bypass approvers keep acting through System Manager**, or do
   they get explicit blank-farm grants? The latter is more honest and makes the
   report's `absent` verdict actionable.
4. **What happens to `Farm Manager Valle`'s misspelling?** It stops being read by
   this app at step 4, but it remains a role people hold until its owner removes
   it.
