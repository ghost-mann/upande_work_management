# Who approves: one table, named people

*2026-08-31*

> **Status: SUPERSEDED by `2026-08-31-rbac-farm-scoping-design.md`.**
> This document argued about whether Settings should name roles or people. That
> was the wrong layer: Frappe's User Permissions already record which farms a
> person may touch — 127 of them on staging, across 124 users, the newest created
> the same day this was written — and the app ignores them, which is a
> data-visibility gap rather than a design preference. Kept because the reasoning
> is a useful record of a wrong turn, and because its findings about role
> granting being *ineffective* (not merely impolite) carry over unchanged.
>
> **Original status: proposed, and not endorsed.** The person who asked for this said
> plainly they are "not convinced this is the best solution". This document
> records the decision, the evidence, and — at equal length — the case against
> it, so it can be re-opened on the argument rather than re-derived from
> scratch. Read *Why this may be wrong* before implementing anything.

## The change in one sentence

Who may approve each step is named as **people, on the step**, in one validated
table — replacing three mechanisms, and removing the app's ability to grant
roles.

## Current state: three mechanisms, and the designed one is unused

| mechanism | shape | live | staging |
|---|---|---|---|
| `approval_stages` + `stage_approvers` | child tables; grants roles on save | 0 stages, 0 approvers | 15 stages, **0 approvers** |
| `consultant_users` | comma-separated emails, free text | `koskey@lokitelaorchards.com` | empty |
| `master_plan_post_approval_editors` | comma-separated emails, free text | `austin@…, koskey@…` | empty |

`consultant_users`' own field description reads *"Superseded by Stage Approvers
rows on the Planner: Weekly Consultant stage. Read-only, and removed in the next
release."* That release never came. The mirror still reads it, and it is what
live actually runs on.

The two email fields are **not** workflow transitions. Both are screen-level
membership checks in `wm_masterplan`:

    MP_LISTED_CONSULTANT = 1 if frappe.session.user.lower() in mp_cons else 0
    CAN_EDIT_APPROVED    = 1 if frappe.session.user.lower() in mp_post else 0

The catalogue already has a `Gate` kind for precisely this — *"not a workflow
transition at all. A screen-level check that reads its approvers from the same
table"* — and `planner_weekly_consultant` is one. So consolidating these is
finishing a design that was started and abandoned, not inventing one.

## The two findings that drive the decision

**1. Granting roles does not work on these sites.** `frappe/core/doctype/user/user.py`:

    # Remove invalid roles and add new ones
    self.roles = [r for r in self.roles if r.role in new_roles]
    self.append_roles(*new_roles)

A user with a Role Profile has their roles **replaced** by the profile's set on
every save — filtered to exactly what the profile lists. On staging **420 of 458
enabled users have a profile**. So any role this app grants is deleted the next
time that User document is saved, by anything: an admin editing a phone number,
an HR sync, a bulk update. It does not matter whether the app grants someone
else's role or invents its own.

This is stronger than the objection originally raised. The role-granting is not
merely a boundary violation; **it is ineffective, and it fails silently.**

**2. The email lists are the only mechanism anyone adopted.** Live runs on them.
The designed role-and-approver mechanism is empty on both sites, two years into
the app's life. Adoption is evidence about which mechanism fits how these people
work.

## Decision

1. **Name people, not roles**, for who may approve or pass a gate.
2. **Validated input, not free text.** A `Table MultiSelect` of `Link → User`,
   not a comma-separated string.
3. **One table**, on the stage row, replacing `stage_approvers`,
   `consultant_users` and `master_plan_post_approval_editors`.
4. **The app never writes to a User.** No `Has Role`, ever.
5. **Roles remain the access layer** and are documented as such: a role grants
   read/write on the doctype so a person can open the document; the user list
   decides who may act on it.

## Why this may be wrong

Taken seriously, because the request came with a stated doubt.

**Turnover becomes edits in N places.** A role is one edit: change who holds
`Farm Manager Saboti`. Named users mean finding every row naming the leaver —
across 10 approval stages, 3 of which are farm-scoped — 7 unscoped lists plus
3 × 4 farms — so ~19 cells, plus one per gate, ~21 in all. That is small today
with 4 farms. At 16 farms and a fifth chain it is not, and the
work grows with every farm added. **This is the strongest argument against, and
it is a real cost that does not appear until later.**

**It is the wrong altitude for an org chart.** "The farm manager approves farm
work" is a durable statement about the organisation. "koskey approves Saboti" is
a fact about this month. Encoding the second where the first belongs means the
configuration drifts out of date silently, and nothing in the system knows that
a stage naming a departed employee is now unapprovable.

**Roles are what the mechanism is built for.** `Workflow Transition.allowed` is
a `Link → Role`. There is no user field. Named users have to be compiled into
the transition's `condition` as Python — `frappe.session.user in [...]` — which
is a string of code assembled from user input. This app has already been bitten
by exactly that class of bug: a stale Property Setter put `"\nKentrout"` into a
Link's `options`, and every Planner save died with `DocType \nKentrout not
found`, reaching the person as nothing but a failed Save button.

**The wipe has a cheaper fix.** If granting is the only real problem, then
*stop granting* and keep naming roles — the app reads roles, the project's Role
Profiles grant them, nothing is wiped because nothing is written. That is a
much smaller change than this document proposes, and it keeps the durable
altitude. **This is the alternative that most deserves a second look.**

**Adoption may be evidence of something else.** The email fields being the only
mechanism used could mean they fit how people work — or simply that they came
first, and nobody had a reason to migrate. One of those justifies building on
them; the other does not.

## Alternatives considered

| alternative | why set aside | would revisit if |
|---|---|---|
| **Name roles, stop granting** (read roles, never write them) | keeps a role vocabulary a new company must map onto its own, and keeps the app's compiled-in job titles relevant | turnover proves frequent, or farm count grows — this becomes the better answer |
| Keep granting, but only roles the app owns | does not survive the profile wipe: a role absent from the profile is removed regardless of who created it | Frappe changes that behaviour |
| Free-text emails (as today, just consolidated) | a typo is silent: one wrong letter and a step has nobody, with nothing on screen saying why | never — validation costs nothing here |
| Frappe's native Workflow list, edited directly | `build_workflows()` overwrites all five workflows on every migrate and every Settings save; anything typed there is destroyed silently | the app stopped generating workflows, which would cost the per-farm scoping |

## What would change the decision

Stated in advance so it is testable rather than a matter of taste:

- **Approver turnover.** If a named approver changes more than about twice a
  year per stage, roles win on maintenance alone.
- **Farm count.** At 4 farms this is ~21 cells. Past roughly 10 farms on the
  farm-scoped stages, the table becomes a chore and roles win.
- **A second company's chain.** If a new deployment needs different *steps*
  rather than different people, the stage catalogue must become data first, and
  this design should be built on top of that rather than before it.

## Design

**One child doctype**, `Work Management Stage Approver`, kept under its existing
name so nothing is renamed on live where it is a custom doctype:

| field | type | notes |
|---|---|---|
| `stage_label` | Select | unchanged |
| `scope` | Link → Farm | unchanged; empty means every farm |
| `approvers` | Table MultiSelect → `Work Management Stage Approver User` | **new.** Validated users. Replaces the single `user` field |
| `role` | Link → Role | **kept**, and now optional: a stage may name a role *or* users. Named users narrow a role; a role alone behaves exactly as today |
| `user` | Link → User | **removed.** Its only reader was the role granting |

Keeping `role` matters: it is the migration path back to the rejected
alternative, and it lets a deployment choose per stage. A stage with a role and
no users behaves as it does today.

**Compilation.** For an `Approval` stage, `allowed` stays the role (or a broad
role where only users are named) and the users become a condition, `AND`-ed with
the existing farm condition:

    doc.farm == "Saboti" and frappe.session.user in ["koskey@…"]

Every address is escaped through one helper with its own test, because the
condition is code assembled from input. For a `Gate` stage there is no
transition: the same list is read at request time, replacing the two
`frappe.session.user.lower() in [...]` checks in `wm_masterplan`.

**Removed:** `sync_roles()`, `_desired_grants()`, `managed_roles()`, and
`approver_users()` — the last already dead, called by nothing.

## What this does not solve

- **Document access.** Approvers still need a role granting read/write on
  Planner, Actuals and Payment to open a document at all. This changes who may
  *act*, not who may *see*. Any claim that it removes roles entirely is false.
- **The stage catalogue is still code.** Steps can be switched off, not added,
  and a row added by hand is deleted by the next migrate. Unchanged here, and
  the larger of the two portability problems.
- **The compiled-in job titles.** Installing the app still creates `Farm
  Manager`, `General Manager`, `HOD HR`, `HR Clerk` and `Production Section
  Head` on any site, because the 15 stages default to them and a transition's
  role must exist. Worth doing separately and cheap; not in scope here.

## Migration

Nothing to unpick: `stage_approvers` is empty on both sites, so no approver data
exists anywhere.

1. `consultant_users` → the `Planner: Weekly Consultant` Gate stage's approver
   list. One value on live.
2. `master_plan_post_approval_editors` → a new Gate stage,
   `masterplan_post_approval_edit`. Two values on live.
3. Both source fields keep their values, read-only, for one release, so a
   rollback does not lose who was named.
4. An address in either field that is not a User on the site is reported, not
   dropped — it is the only record of intent.

## Risks

| risk | disposition |
|---|---|
| An escaping bug puts broken Python in a workflow condition | one escaping helper, its own tests, and a generated-workflow test that asserts every condition parses |
| A stage ends up with neither role nor users | `validate_configuration` refuses the save, as it already does for a farm with no approver |
| Turnover cost lands later, not now | recorded above with a threshold; `role` is retained per stage so a deployment can move back without a migration |
| Live's two fields are read by the mirror, not the app | the mirror changes too, and `check_ported.py` keeps app and mirror in step |
| This is built before the catalogue becomes data | if a second company needs different *steps*, do that first — noted in *What would change the decision* |

## Open questions

1. **How often do approvers actually change?** The single fact that decides
   users-versus-roles, and it is not in the code. Live's post-approval editor
   field has held two names, which hints at stability but is one data point.
2. **Is `role` per stage worth keeping**, or is a system that can be configured
   two ways worse than one that can be configured one way badly?
3. **Should this wait** for the stage catalogue to become data, given that is
   the larger portability problem and this design sits on top of it?
