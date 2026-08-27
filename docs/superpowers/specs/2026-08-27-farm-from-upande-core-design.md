# Farms come from Upande Core

*2026-08-27*

## The change in one sentence

`Work Management Farm` is retired; Upande Core's `Farm` becomes the only farm
doctype Work Management knows, read-only, and the app declares upande_core a
required app.

## Why

Three separate doctypes currently claim to be "the farm":

| doctype | owner | on kaitet.local | on live (v15) |
|---|---|---|---|
| `Farm` | Upande Core (module `Upande Core`, app `upande_core`) | 16 rows | absent — live's `Farm` is module `Upande Kaitet` |
| `Work Management Farm` | this app | 14 rows | absent |
| `Farm` | Upande Kaitet | — | 15 rows, **not to be used** |

The two on kaitet.local have already drifted: core has SIMO, Greenville and
cheptiret; this app has Kabarak. Thirteen names are common.

The site's own data has already picked a side. `install.py:89,94` declares
`Employee.custom_farm` and `Warehouse.custom_farm` as `Link → Work Management
Farm`, but on the site both are live as `Link → Farm`. Since `67a940b` made the
app's field definitions authoritative, the next `bench migrate` would repoint
3,241 Employee rows and 528 Warehouse rows at a doctype that has no SIMO, no
Greenville and no cheptiret. Aligning the app with core `Farm` defuses that.

Upande Kaitet's `Farm` is off-limits by direction. Because a doctype name is
global, "read `Farm`" is only safe where `Farm` belongs to Upande Core — hence
the hard dependency rather than a name check at runtime.

## Decisions

1. **Ownership.** Core `Farm` is the single source of truth for which farms
   exist. `Work Management Farm` is deleted from the app and from sites by a
   patch.
2. **Dependency.** Hard: `required_apps = ["upande_core"]` in `hooks.py`.
   `bench install-app work_management` fails on a site without it. Farm reads
   become plain `frappe.get_all("Farm", …)` with no `exists()` guard.
3. **Core `Farm` is read-only to this app.** Work Management adds no field to
   it, writes no Property Setter against it, and never saves one of its
   documents. What WM knows about a farm and Core does not lives on WM's own
   side (below).
4. **Orphans resolve themselves.** A farm name in use that Core does not have
   is cleared from whatever referenced it, and logged. No aborted migrate, no
   half-formed record pushed into another app's doctype. On kaitet.local this is
   Kabarak: two Warehouses, no Employees, no documents of any kind.
5. **Business unit is dropped.** No `Work Management Farm` row has one set, and
   `Employee.custom_business_unit` already links people to Core's Business Unit.
   If farms should belong to business units, that is a field Upande Core adds to
   its own doctype.
6. **Mirror.** The mirror keeps its `("Work Management Farm", "Farm")` fallback
   so live is untouched; `port_app.py` rewrites it to a plain core-`Farm` read
   when generating `api/*.py`.
7. **The two `custom_farm` fields on other doctypes.** `Warehouse.custom_farm`
   is Upande Core's — it ships it, exports it as the fixture
   `Warehouse-custom_farm`, hangs `warehouse_hooks.py` off it, and `Row`,
   `Section` and `Bed` all `fetch_from` it. WM stops declaring it. WM keeps
   declaring `Employee.custom_farm`, so the box exists without upande_kaitet,
   but declares it *identically* to upande_kaitet's: label "Unit/Division",
   `Link → Farm`, `insert_after: grade`. Two apps then write the same field and
   neither can flip it.
8. **Verification on kaitet.local directly**, not a copy: `bench migrate`, then
   the five screens and Master Plan driven against the real 16 farms.
9. **Sections are out of scope.** Core's `Section` (0 rows) versus
   `Work Management Section` (16 rows) is the same overlap one level down, and
   gets its own change after this one is proven.

## Non-goals

- **Live/v15.** Nothing is pushed to `kaitet-group.upande.com` in this change.
  Live keeps its 15 farms out of its own `Farm`, and the mirror keeps the
  fallback that reads it.
- **`Work Management Section` vs core `Section`.** The same overlap exists one
  level down (core `Section`, 0 rows; `Work Management Section`, 16 rows). Out
  of scope, deliberately.
- **Anything about core `Farm` itself** — its fields, labels, field order, or
  mandatory rules. See decision 3.

## Where each piece of farm knowledge lives afterwards

| what | before | after |
|---|---|---|
| which farms exist, and their names | `Work Management Farm` | core `Farm` |
| a farm's cost project | `Work Management Farm.project` | the **farms table on Work Management Settings** (`WM Farm` child: `farm`, `project`) |
| a farm's area | `Work Management Farm.area_ha` | core `Farm.area`, overridden by `WM Farm.area_ha` where set — the shape `dashboard.py:2812-2819` already reads |
| whether a farm is out of use | `Work Management Farm.disabled` | core `Farm.disabled` where the site has that column, every farm enabled where it does not |
| which business unit a farm belongs to | `Work Management Farm.business_unit` | dropped (decision 5) |
| a farm's description | `Work Management Farm.description` | dropped — nothing read it |
| who approves for a farm | Stage Approvers on Settings | unchanged |

The cost project is not droppable: live maps `Saboti / Lokitela / Vale →
PROJ-0031` and `Endebess → PROJ-0032`, ten api modules read `farm_project`, and
`rates.py:1003` uses it to decide which Tasks the Rates tab may offer. It cannot
be derived either — `Project` has no farm field, and the projects on this site
are one-off works ("Chepsito GH 16 Replanting"), not per-farm buckets.

Its new home already exists and is the right shape: the `farms` table on
Work Management Settings (child doctype `WM Farm`, fields `farm`, `area_ha`,
`project`, `approver_role`). It is empty on kaitet.local and is currently
described as "Superseded by the Work Management Farm doctype … removed in the
next release". This change reverses that: the table stays, its description is
rewritten, its `farm` column becomes a `Link → Farm`, and `approver_role` stays
deprecated in favour of Stage Approvers.

`disabled` is read, never written. Core `Farm` does not ship one — the field on
kaitet.local is a hand-made Custom Field, `module: None`, owner
otieno@upande.com, and `upande_scp/serverscripts/spray_plan_creator/admin.py:24`
reads it behind `frappe.db.has_column("Farm", "disabled")`. WM does the same.
No row is disabled in either doctype today.

## Code changes

**`hooks.py`** — add `required_apps = ["upande_core"]`; delete the comment at
line 73 about upgrading `business_unit` to a Link once upande_core arrives, and
the hook it describes.

**`install.py`** — in `CORE_CUSTOM_FIELDS`:

- `Employee.custom_farm` (line 89) becomes `Link → Farm`, `insert_after: grade`,
  label unchanged at "Unit/Division" — byte-identical to upande_kaitet's
  declaration in `upande_kaitet/upande_kaitet/custom/employee.json`. Today the
  two disagree on both target and position, and since `67a940b` made this
  app's definitions authoritative, WM's version wins the
  next migrate: the box moves up the form and repoints 3,241 employees at a
  farm list missing SIMO, Greenville and cheptiret. Matching the declaration
  removes the conflict rather than winning it.
- `Warehouse.custom_farm` (line 94) is **deleted**. Upande Core owns that field:
  it ships it in `upande_core/upande_core/custom/warehouse.json`, exports it as
  the fixture `Warehouse-custom_farm`, hooks `warehouse_hooks.py` to it, and
  `Row`, `Section` and `Bed` `fetch_from` it. `upande_core/install.py:51-54`
  even orders the Warehouse form around it. WM only reads it.
- `Warehouse.custom_area_ha` and `Employee.custom_business_unit` stay as they
  are. Nothing is added to core `Farm`.

Delete the `business_unit` Link-upgrade machinery (lines 347-404). Adoption
needs no edit: `adopt_existing_custom_doctypes()` (line 279) works off
`shipped_doctypes()` (line 48), which reads the doctype folders, so deleting the
folder is what removes the farm from it.

**Link fields — 10 sites, `options` only, no data rewriting** (values are farm
names and already exist in core `Farm`):

- `work_management_planner.json` · `farm`
- `work_management_assigner.json` · `farm`
- `work_management_actuals.json` · `farm`
- `work_management_payment.json` · `farm`
- `work_management_master_plan.json` · `farm`
- `work_management_section.json` · `farm`
- `work_management_stage_approver.json` · `scope`
- `work_payment_line.json` · `farm`
- `work_rate_recalc_run.json` · `farm`
- `wm_farm.json` · `farm` (the Settings farms table, no longer deprecated)

**Delete** `work_management/work_management/doctype/work_management_farm/`.

**`api/config.py`** — `_farms()` returns the farm list from `Farm` with no
`exists()` guard, filtered by `disabled` only where that column exists, and
takes `farm_project` from the Settings farms table. The legacy branch at lines
120-125 stops being a fallback and becomes the only path for `farm_project`.
Update the module docstring (line 4).

**`approvals.py:509`** — farm list reads `Farm`, guard dropped.

**`taxonomy.py`** — remove the two `FIELD_LABELS` entries keyed to
`Work Management Farm` (`farm_name`, `business_unit`) and
`apply_business_unit_visibility()` entirely. The `("WM Farm", "farm")` entry
stays — that is WM's own field. WM must not write a Property Setter against core
`Farm`: it would relabel the field for every app that uses it (spray plan,
irrigation, sales). Consequence, accepted: the configurable taxonomy can still
rename WM's own `farm` labels on Planner, Assigner, Actuals, Payment, Section
and the Settings table, but the farm record's own labels belong to Upande Core.

**`desk.py:69`** — `nav_label` key becomes `Farm`.

**Desk artifacts** — `workspace/work_management_setup/…json:29` and
`workspace_sidebar/work_management.json:289` link to `Farm`.

**`seed/kaitet.py:84,87,156`** — stops creating farms. Farms are Upande Core's
to create. The seed instead fills the Settings farms table with Kaitet's own
mapping — `Saboti`, `Lokitela`, `Vale` → `PROJ-0031`, `Endebess` → `PROJ-0032`,
the four rows live runs on — for farms that exist, and reports the names it
could not find. A rebuilt Kaitet site then has a working Rates tab without
anyone retyping the mapping, and the values stay where Kaitet-specific values
already belong by design.

**Existing patches** — `migrate_farms_and_approvers`, `backfill_farms_in_use`
and `seed_sections_from_cost_centres` already return early when
`Work Management Farm` is absent, so they no-op once the doctype is gone.
`enable_business_unit_level_if_used` is deleted from `patches.txt` along with
the visibility machinery it drives.

**Settings** — `work_management_settings.json:103` describes the `farms` table
as superseded and slated for removal. Rewrite: it holds each farm's cost project
and area override; the farms themselves come from Upande Core.

## The migration patch

`work_management.patches.v1_0.move_farms_to_upande_core`, `[post_model_sync]`:

1. **Carry WM's own knowledge into the Settings table.** For each
   `Work Management Farm` with a `project` or a non-zero `area_ha`, ensure a row
   in the Settings farms table with those values. Nothing to do on kaitet.local
   — no farm has either — but live's four mapped farms arrive this way.
2. **Clear references to farms Core does not have.** For every Link field in
   `backfill_farms_in_use.SOURCES` plus `Employee.custom_farm` and
   `Warehouse.custom_farm`, blank any value absent from core `Farm`, and log
   each one with what held it (`Kabarak — Warehouse "Kabarak - KR", Warehouse
   "Kabarak silage pits (now 4 pits) - KR"`). Uses `frappe.db.set_value` so no
   document validation runs.
3. **Clear stale overrides.** The JSON ships the new `options`, so this step
   only removes what a site wrote over it — Property Setters and Custom Field
   `options` still naming the old target. `install.is_stale_link_option()`
   (line 408) already decides this; reuse it rather than writing a second rule.
4. **Delete** the `Work Management Farm` doctype and its table, plus every
   Property Setter and Custom Field naming it.

Idempotent: a second run finds no `Work Management Farm` doctype and exits at
step 1.

## Why WM must never write to a `Farm` document

Beyond decision 3 being the instruction: all 16 core `Farm` rows are missing
`farm_type` and Eldama is missing `company`, both `reqd: 1`. Any `doc.save()` on
an existing Farm raises *Farm Type is required*. Even a well-meant write would
fail. Reads only, and `frappe.db.set_value` never touches Farm at all.

Related hazard worth recording: Upande Kaitet owns four Custom Fields on `Farm`
(`custom_handles_sales`, `custom_sales_order_type`, `custom_location`,
`custom_column_break_32dil`) and a `field_order` Property Setter naming `farm`
and `kephis_farm_id` — fields core `Farm` does not have. It is inert today
(Frappe falls back to core's order). WM owns nothing there, so nothing of WM's
can be lost to it; it is documented so the next person does not read that
Property Setter as ours.

## Tests

TDD — each of these is written before the change it describes.

- `test_api_doctype_guards.py`: `Work Management Farm` leaves `FRAGILE`.
  `test_the_fragile_list_is_all_doctypes_this_app_ships` (line 56) asserts every
  `FRAGILE` name is a doctype this app ships, so deleting the doctype *requires*
  this edit — the two stay consistent by construction. Every other guard stays.
- **New** `test_farm_source.py`, all source-level, no site:
  - no shipped JSON has a Link whose `options` is `Work Management Farm`
  - `Farm` appears in no `exists()` guard
  - `required_apps` names `upande_core`
  - `CORE_CUSTOM_FIELDS` declares no field on `Farm`
  - nothing in the app writes a Property Setter against `Farm`
  - nothing in the app calls `.save()`, `.insert()` or `set_value` on `Farm`
  - `CORE_CUSTOM_FIELDS` declares no `Warehouse.custom_farm`
  - the `Employee.custom_farm` declaration matches upande_kaitet's field shape
    (label, fieldtype, options, `insert_after`)
- **New** `test_move_farms_to_upande_core.py`: carries project and area into the
  Settings table; clears the orphan and logs it; is idempotent; leaves core
  `Farm` rows byte-identical.
- Update `test_adoption.py:32,137`, `test_sections.py:34,46,505`,
  `test_taxonomy.py:293,304`, `test_desk_sync.py:246,250,343-348`.
- The 343 existing tests stay green:
  `PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest discover -s work_management/tests -t . -p "test_*.py"`

## The mirror

`port_app.py` gains one rewrite rule covering two sites:

- `server_scripts/wm_masterplan.py:83` — the
  `for mp_farm_dt in ("Work Management Farm", "Farm")` loop becomes a plain
  `Farm` read.
- `server_scripts/wm_dashboard.py:2792` — the guarded
  `Work Management Farm` / `area_ha` read becomes `Farm` / `area`.

`scripts/check_ported.py` must still report *all 10 api module(s) match a fresh
port* afterwards. The mirror files themselves do not change, so
`sync.py diff` stays clean against live and live keeps its 15 farms.

## Docs

`README.md` — the app is no longer installable standalone; say so where it
claims portability, and replace the `Work Management Farm` bullet with core
`Farm` plus the Settings farms table. `docs/DEVELOPER_GUIDE.md` — the farm
source, the read-only rule and why, and the upande_kaitet `field_order` note.
`docs/manual_content.py` — where the user guide says to add a farm, it now says
Upande Core, and the cost project is set on Settings.

## Risks

| risk | disposition |
|---|---|
| WM stops installing without upande_core | accepted, by decision |
| A site whose `Farm` is Upande Kaitet's | install fails on the missing app before WM can read the wrong doctype |
| Core `Farm` rows fail their own mandatory fields | WM never writes to a Farm document at all |
| A farm exists in Core but is missing from the Settings table | it appears in the pickers with no cost project — the same state a newly added farm is in today; the Rates tab shows nothing for it until someone fills it in |
| Orphan references cleared silently | logged per reference with what held it; on kaitet.local it is two Warehouses and nothing else |
| Two apps declare `Employee.custom_farm` | resolved by declaring it identically, not by winning: same label, same target, same position. A test asserts the declaration matches upande_kaitet's shape |
| WM stops declaring `Warehouse.custom_farm` | Core ships it as a fixture and depends on it in three doctypes and a hook, so it cannot silently vanish. A site with neither app would have no such field, but such a site cannot install WM anyway |
| Taxonomy can no longer rename the farm level's own labels | accepted; renaming another app's field would leak into every app that uses it |

## Order of work

1. Tests for the end state (they fail).
2. `hooks.py` `required_apps`; `install.py` options and deletions.
3. Repoint the 10 Link `options`; delete the doctype folder.
4. `config.py`, `approvals.py`, `taxonomy.py`, `desk.py`, `seed/kaitet.py`,
   workspace and sidebar JSON, Settings description.
5. The migration patch.
6. `port_app.py` rewrite + `check_ported.py` green.
7. Docs.
8. Full suite green; then `bench migrate` on kaitet.local — which also picks up
   upande_core's new `farm_location` — and drive the five screens plus the
   Master Plan screen against the real 16 farms.
