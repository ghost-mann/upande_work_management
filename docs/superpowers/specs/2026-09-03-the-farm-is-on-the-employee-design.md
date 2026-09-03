# The farm is on the Employee

*2026-09-03*

> **Supersedes** `2026-09-03-one-table-of-grants-design.md`, written earlier the
> same day, which proposed merging the tables and giving grants a farm column.
> That document's useful residue is its evidence for rejecting two of the four
> places a farm can live; its own proposal is more machinery than this problem
> needs. **Amends** `2026-08-31-rbac-farm-scoping-design.md`: its leak fix and
> User Permission work stand and are shipped; its conclusion that *approval*
> scoping should come from User Permissions does not.

## The change in one sentence

Approval stages and capabilities are granted to roles and nothing else — no
farms, no people, no per-farm role names — and the farm a person may act for is
read from their own Employee record, where the organisation already maintains it
for 2,350 of 2,352 active employees.

## The one missing word

Frappe lets you say *"this role may approve this document"*. It gives you no way
to say *"…but only for Lokitela"*. A role is global. Every awkward thing in this
app's approval configuration is a workaround for that single missing word.

There are exactly four places the word "Lokitela" can live. Three were tried or
proposed; the fourth is where it already is.

**1. In the role's name.** What the site does today: ten roles called
`Farm Manager Lokitela`, `Farm Manager Endebess`, `Farm Manager Valle` — the last
misspelled and unrenameable because people hold it. It works, and it costs a role
per farm, 13 Role Profiles naming them, and a `{farm: role}` map in
`config._farm_approver_role` that exists only to parse them back apart.

**2. In Frappe's User Permissions.** Proposed by the RBAC spec. Measured and
rejected: on all nine people who have ever approved a Planner the two mechanisms
disagree, and Frappe's is wider **every time** — `bramuel`'s role says Lokitela
and his permissions say Lokitela, Saboti and Vale; `kibett`'s role says Valle and
his permissions say all four; `pkatule` has no permission at all, which in Frappe
means all sixteen. A Farm User Permission answers *"whose records may I see"*,
which is a fair thing for a Lokitela manager to need across Vale. It is not an
answer to *"whose work may I approve"*.

**3. In a column in a table in this app.** The superseded grants design. It
works, and it means a row per person per farm to populate, a reconciliation
report, a gate, and a new table.

**4. On the person's Employee record.** Where it already is.

## The evidence for the fourth

`Employee.custom_farm`, labelled **Unit/Division**, a Link to `Farm`. HRMS owns
`Employee`; `hooks.py` already requires `hrms`; and `install.CORE_CUSTOM_FIELDS`
already declares this field, identically to `upande_kaitet`, so nothing new is
depended upon.

**2,350 of 2,352 active employees have it set.** HR maintains it as part of
ordinary employee administration.

Checked against every one of the 19 enabled people holding a per-farm role:

| verdict | count |
|---|---|
| Employee's farm **matches the role name exactly** | **15** |
| differs — `kibett`: role says `Valle`, Employee says `Vale` | 1 |
| Employee record exists but carries no farm — `hkiprop` | 1 |
| no active Employee record — `guchu`, `nduryaphilip66` | 2 |

Sixteen of nineteen agree, and the single "difference" is the misspelling: the
Employee record holds the **correct** spelling of Vale. The workaround has been
wrong about a farm's name for as long as it has existed, and the data it should
have been reading was right.

**No person holds two per-farm roles**, so one farm per person is not a
simplification imposed by this design — it is what the site already says.

**No two active Employee records share a `user_id`**, so the lookup is
unambiguous.

## Design

### Two tables, both `thing → role`

**Approval Stages** — one row per stage: the stage, its document type, `On`, and
the role that takes it. Unchanged in shape, minus nothing. Five of the 14 stages
are Submit steps and cannot be switched off; three are farm-scoped.

**Capabilities** — one row per capability per role. Unchanged entirely.

Neither table gains a farm column, and no third table exists. Adding a second row
with the same action grants it to another role, which is how `Capabilities`
already behaves.

### One rule, for both

> Whoever holds the role may do the thing, for the farm they work at.

Farm-scoped stages and capabilities compare the document's farm against the
person's; unscoped ones do not compare at all. Which of the 14 stages are scoped
stays a property of the stage in `approvals.CATALOGUE`, as today.

### The lookup

    def acting_farm(user=None):
        """The farm this person works at, from their Employee record, or None.

        None means no farm-scoped authority -- see the fail-closed rule.
        """

One `frappe.db.get_value` against `Employee` by `user_id` and `status="Active"`.
No imports, no Frappe API beyond `db.get_value`, so it ports to the Server Script
sandbox by the same discipline that made `permitted_farms()` portable.

### The workflow condition, which is where this pays off

A farm-scoped stage generates **one** transition, whose condition is:

    doc.farm == frappe.db.get_value(
        "Employee", {"user_id": frappe.session.user, "status": "Active"},
        "custom_farm")

Frappe's `get_workflow_safe_globals()` (`frappe/model/workflow.py:81`) hands a
transition condition exactly `frappe.db.get_value`, `frappe.db.get_list` and
`frappe.session` — so this is expressible with no extension to Frappe and no
per-farm generation.

Verified against the real evaluator on `kaitet.local`:

| session user | `doc.farm` | result |
|---|---|---|
| pkatule@lokitelaorchards.com | Lokitela | `True` |
| pkatule@lokitelaorchards.com | Endebess | `False` |
| kibett@lokitelaorchards.com | Vale | `True` |
| austin@upande.com *(no Employee)* | Lokitela | `False` |

`kaitet.local` has 49 transitions today, 24 of them farm-conditioned. After this,
**three** conditions — one per farm-scoped stage — and the farm-conditioned count
stops being a function of how many farms exist.

### The fail-closed rule

A person with no active Employee record, or one carrying no farm, gets **no
farm-scoped authority at all**. Not "every farm".

This is the opposite of Frappe's User Permission default, deliberately: absent
data must not read as universal authority, which is precisely the trap that
sank place 2. Estate-wide authority is then something a site says explicitly, by
granting an unscoped role — and three of the nine current approvers already work
that way, through System Manager.

## Migration

There is almost nothing to migrate, which is the point.

1. **Capabilities** — untouched.
2. **Approval Stages** — untouched. The three farm-scoped stages keep whatever
   role they name.
3. **Stage Approvers** — the table is retired. Its 27 rows on `kaitet.local` carry
   nothing this design reads: the person is irrelevant, the farm now comes from
   the Employee record, and the per-farm role override is the mechanism being
   removed. Nothing is translated, so nothing has to be reconciled.
4. **The ten per-farm roles** — left in place, read by nothing, granted by nobody.
   This app never created them and does not delete them. The 13 Role Profiles
   naming them keep working; retiring them is their owner's decision, whenever.

No reconciliation gate. No prerequisite. No human decision per person. The three
data gaps below are the whole of the outstanding work, and they are HR records.

## The three data gaps

Nameable, and fixable by whoever maintains Employee records:

| person | gap | effect until fixed |
|---|---|---|
| `guchu@endebesscoffee.com` | no active Employee record | loses Endebess approval |
| `nduryaphilip66@gmail.com` | no active Employee record | loses Torongo approval |
| `hkiprop@karenroses.com` | Employee record has no farm | loses Karen approval |

`guchu` has approved Planners, so this one is not theoretical. A report names
these before anything is enabled.

## Rollout

1. **Ship the report.** Read-only: every holder of a farm-scoped stage's role,
   their Employee farm, and the verdict. Run on `kaitet.local` and staging.
2. **Fix the three records.** HR, not code.
3. **Ship `acting_farm()` and the new condition**, regenerate the workflows, and
   replace the screens' `AP_FARMS` with it.
4. **Delete the list below.**
5. **The mirror in step with the app**, kept honest by `check_ported.py`.

Steps 1–2 are safe and independent. Step 3 is the behaviour change and is small
enough to revert by regenerating the workflows.

## What this deletes

- the `Stage Approvers` table, and the per-person design behind it
- `config._farm_approver_role()` — the `{farm: role}` map
- `approvals.approver_users()`, `_desired_grants()`, `sync_roles()`,
  `managed_roles()` — role granting, ineffective against Role Profiles anyway
- `config._stage_roles()`
- per-farm transition generation in `transition_groups()`
- the stranded-farm validation — a farm is not "covered by an approver row"
- the whole of the superseded grants design, before it is built

## Risks

| risk | disposition |
|---|---|
| Approval scope now follows HR data | correct by intent: moving someone's Unit/Division moves the farm they act for. Stated so it is chosen, not discovered |
| A missing Employee record silently removes authority | fail-closed is deliberate; step 1's report names every case before step 3 |
| One farm per person is too narrow | no person holds two per-farm roles today, so it matches the site. A genuine multi-farm approver needs an unscoped role, as the GM already has |
| Two Employee records for one user | none share a `user_id` on `kaitet.local`; the report asserts it, and `get_value` would otherwise be arbitrary |
| The condition is evaluated per transition check | one indexed `get_value` on a doc the user is already opening. Measure if a screen slows, do not pre-optimise |
| `Post Harvest` and other non-planning units | 25 `Farm Manager` holders sit on `Post Harvest`. If it is not a farm this app plans against, `farms_in_use` already excludes it and their authority is empty — verify in step 1 |

## What this does not solve, and one thing it does not improve

- **`Farm Manager` is still too broad a role.** 129 enabled users hold it and 40
  Role Profiles hand it out — to Intake QC, Procurement approvers, CFU
  technicians, HR. This design bounds each of them to one farm instead of twelve,
  which is a narrowing: 56 of the 129 have no active Employee record and so lose
  farm-scoped approval entirely. But 19 remain on Kapkolia and 25 on Post
  Harvest, and "everyone at this farm who holds Farm Manager may approve its
  work" may still be wider than intended. **Pointing the three farm-scoped stages
  at a narrower role is now an independent improvement rather than a
  prerequisite** — the farm dimension no longer depends on it.
- **The stage catalogue is still code.** Steps can be switched off, not added.
  The larger portability problem, unchanged.
- **Raw SQL stays raw**, and **live still does not enforce per-person farm
  scoping** on reads — both unchanged from the RBAC spec.

## Open questions

1. **Is `Post Harvest` a farm this app plans against?** It carries the largest
   concentration of `Farm Manager` holders and may be a processing unit rather
   than a planning farm.
2. **Do the three bypass approvers get explicit unscoped roles**, or keep working
   through System Manager? The latter works; the former is legible.
3. **Should `acting_farm()` fall back to `Employee.custom_farm` on an inactive
   record?** Proposed: no. An inactive employee approving anything is a separate
   problem.
4. **Does staging agree?** The 16-of-19 agreement is `kaitet.local`'s. Staging's
   consultant holds a Lokitela-only permission while working more than Lokitela,
   so its Employee data must be checked before step 3 there.
