# Farm scoping belongs to Frappe's RBAC

*2026-08-31*

> **Supersedes** `2026-08-31-who-approves-design.md`, which argued about whether
> Settings should name roles or people. That was the wrong layer. Frappe already
> holds the answer to "which farms may this person touch", the answer is actively
> maintained, and this app ignores it — which is a data-visibility gap, not a
> design preference.

## The change in one sentence

Work Management reads Frappe's User Permissions to decide which farms a person
may see and act on, instead of maintaining a parallel notion of farm scoping that
governs approvals only and reads not at all.

## The leak, first, because it is the part with consequences

A user restricted to **Saboti only** by a Frappe User Permission, holding
`Farm Manager`, on `kaitet.local`:

| read path | farms returned |
|---|---|
| `frappe.get_list("Farm")` | `Saboti` |
| `frappe.get_list("Work Management Planner")` | `Saboti` — 54 rows |
| `config.get_config()["farms"]` | **all 16** |
| `wm_planner` action `meta` | **all 16** |
| `wm_dashboard` action `pipeline` | rows for **Endebess, Lokitela, Saboti, Vale** |

Frappe correctly restricts them to their 54 Saboti rows. The app's dashboard
hands them all four farms: Endebess's 135 planner rows, Vale's 201, Lokitela's
58.

**Why.** The five screens read through raw SQL — 95 raw queries in
`wm_dashboard`, 83 in `wm_payment`, 38 in `wm_actuals`. `frappe.db.sql` consults
no permissions whatsoever. So every Farm User Permission on the site has no
effect on any screen, and never has.

**Scope of the claim, stated precisely.** Role checks *are* enforced for actions
(approve, submit), and `my_requests` filters by `requested_by`. What leaks is the
**farm dimension on reads** — the pickers and the dashboard. Verified on
`kaitet.local` with a probe user, not on a live login: the code path is identical,
but it should be confirmed once with a real restricted account on staging before
being quoted as production fact. `activity_table` returned nothing in the probe
because that site has no master plans, so it is untested rather than clean.

## The source of truth already exists, and is maintained

On staging:

- **680 User Permissions**, of which **127 restrict Farm**
- across **124 distinct users** — 122 to exactly one farm, one to two, one to three
- **334 of 458 enabled users have no Farm restriction**, so they see every farm,
  which is Frappe's own semantics and the behaviour to preserve
- oldest created **2026-08-21**, newest **2026-08-31 11:57** — *today*

These are not leftovers from another app's onboarding. Somebody is maintaining
them now. Which means the organisation is expressing farm scoping deliberately,
in Frappe's own mechanism, and Work Management is ignoring it.

## Why the app has a parallel mechanism

Not carelessness, and worth recording so it is not "fixed" back. The chain used
to live in `fixtures/workflow.json` with Kaitet's farm names spelled into
transition conditions. Rebuilding it as a generated chain kept the farm
dimension where it already was — in transition conditions — because that is what
was being replaced. Nobody asked whether Frappe already had the answer.

What the app built instead:

- one workflow transition per farm, with `condition: doc.farm == "Saboti"`
- a farm → role map in `config._farm_approver_role` for the screens
- per-farm role names — which is where `Farm Manager Valle` came from, its
  misspelling kept because renaming a role people hold is risky

All of it guards *approval actions*. None of it guards *reads*.

## Design

**One new answer, in one place.** `api/config.py` gains:

    def permitted_farms(user=None):
        """Farms this user may act on. Empty set means every farm.

        Read from Frappe's User Permissions, which is where the organisation
        already records it -- 124 users restricted on staging. A user with no
        Farm permission is unrestricted, which is Frappe's own semantics and
        what 334 of 458 users rely on.
        """

built on `frappe.permissions.get_user_permissions(user)`
(`frappe/permissions.py:345`). It returns names, not a query fragment, so it is
pure enough to test and cheap enough to call once per request.

`get_config()` then narrows `cfg["farms"]` by it — the same choke point
`farms_in_use` already narrows, so the pickers on all five screens follow with no
per-screen work. That closes the picker half of the leak in one edit.

**The reads are the work.** 103 raw queries reference a farm:

| script | farm-referencing raw queries |
|---|---|
| `wm_dashboard` | 44 of 95 |
| `wm_payment` | 29 of 83 |
| `wm_masterplan` | 12 of 24 |
| `wm_planner` | 8 of 12 |
| `wm_actuals` | 6 of 38 |
| `wm_assigner` | 4 of 20 |

Each needs the same predicate, and the same discipline that the plan-attribution
work needed: **a check that every query taking the parameter is passed it**,
because the identical query appears at several indentations and pattern
replacement silently misses copies. That check caught three misses last time and
belongs here as a test from the start.

**Workflow transitions name the role only.** No `doc.farm == "X"` conditions.
Frappe enforces the farm dimension through the User Permission, on every path —
list views, reports, the API, and the desk — not only on the transition this app
happens to generate.

**Work Management writes nothing.** No roles, no User Permissions. It reads both.

## What this deletes

- per-farm transition generation: one transition per stage, not one per farm
- per-farm role names: one `Farm Manager`, scoped per person by User Permission,
  instead of `Farm Manager Saboti` / `Valle` / `Lokitela` / `Endebess`
- `config._farm_approver_role` — the farm → role map has nothing left to answer
- the stranded-farm validation: a farm is not "covered by an approver row", it is
  covered by whoever holds the role and is permitted the farm
- `sync_roles()`, `_desired_grants()`, `managed_roles()`, `approver_users()` — and
  the granting is not merely a boundary violation, it is ineffective: Frappe
  replaces a user's roles with their Role Profile's set on every save, and 420 of
  458 users have a profile
- the `user` column on Stage Approver, whose only reader was the granting
- the whole named-users design of the superseded spec

Settings keeps two things: which steps are on, and which role takes each.

## Rollout, which is the risky part

Enforcing a permission that has been ignored **changes what 124 people see**, and
some of them may have been relying on the leak to do their jobs. Fixing it
carelessly would look like an outage.

1. **Measure before enforcing.** Ship `permitted_farms()` and a read-only report:
   for each user with a Farm restriction, which farms they are permitted and which
   farms they have actually touched in the last 90 days. Anyone who has acted
   outside their permission is either mis-permissioned or the permission is wrong,
   and that must be settled by a person, not by a deploy.
2. **Enforce the pickers first.** One edit in `get_config()`, immediately visible,
   trivially revertible.
3. **Enforce the reads behind a setting**, default off, so a site turns it on when
   its permissions have been reconciled. Off means today's behaviour exactly.
4. **Remove the setting** once every site has it on, so the app does not carry a
   permanent switch for a bug.

Step 1 is not optional. Turning enforcement on without it converts a silent
visibility gap into a loud access problem, and blames the fix.

## What this does not solve

- **The stage catalogue is still code.** Steps can be switched off, not added, and
  a row added by hand is deleted by the next migrate. Separate, and the larger
  portability problem.
- **The compiled-in job titles.** Installing the app still creates `Farm Manager`,
  `General Manager`, `HOD HR`, `HR Clerk` and `Production Section Head` on any
  site. Cheap to fix, separate.
- **Raw SQL stays raw.** This adds a farm predicate; it does not make the screens
  permission-aware in general. A future doctype-level restriction would be missed
  the same way. Worth naming rather than implying otherwise.

## Risks

| risk | disposition |
|---|---|
| Enforcement removes access somebody depends on | step 1 measures it before step 3 enables it; the setting defaults off |
| A query is missed and still leaks | the parameter-consistency test, plus a probe-user test asserting each action returns only permitted farms |
| The 127 permissions are themselves wrong | step 1's report surfaces exactly this, as a question for a person |
| Managers lose the estate-wide view | they have no Farm permission and so are unrestricted — 334 of 458 users. Verify a GM is among them before enabling |
| Live runs Server Scripts, not the app | the mirror changes too, and `check_ported.py` keeps the two in step. Nothing is pushed to live until the reconciliation in step 1 is done |
| `permitted_farms()` called per query | resolved once per request and passed down, not re-read 103 times |

## Open questions

1. **Is a GM or a System Manager among the 124 restricted users?** If so, enabling
   enforcement narrows an estate-wide view and step 1 must catch it.
2. **Who maintains the 127 permissions, and against what process?** The app is
   about to depend on them being right.
3. **Should the pickers narrow even for unrestricted users**, to the farms in
   `farms_in_use`? They already do; this design must not undo that.
