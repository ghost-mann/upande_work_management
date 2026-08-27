# Farms come from Upande Core

*2026-08-27*

## The change in one sentence

`Work Management Farm` is retired; Upande Core's `Farm` becomes the only farm
doctype Work Management knows, and the app declares upande_core a required app.

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

1. **Ownership.** Core `Farm` is the single source of truth. `Work Management
   Farm` is deleted from the app and from sites by a patch.
2. **Dependency.** Hard: `required_apps = ["upande_core"]` in `hooks.py`.
   `bench install-app work_management` fails on a site without it. Farm reads
   become plain `frappe.get_all("Farm", …)` with no `exists()` guard.
3. **Orphans.** A farm name in use with no core counterpart aborts the patch
   with the list. Nothing half-formed is written into another app's doctype.
4. **Business unit.** WM installs `custom_business_unit` (`Link → Business
   Unit`) on `Farm`, matching `Employee.custom_business_unit`, which is already
   a Link to core's Business Unit.
5. **Mirror.** The mirror keeps its `("Work Management Farm", "Farm")` fallback
   so live is untouched; `port_app.py` rewrites it to a plain core-`Farm` read
   when generating `api/*.py`.

## Non-goals

- **Live/v15.** Nothing is pushed to `kaitet-group.upande.com` in this change.
  Live keeps its 15 farms out of its own `Farm`, and the mirror keeps the
  fallback that reads it.
- **`Work Management Section` vs core `Section`.** The same overlap exists one
  level down (core `Section`, 0 rows; `Work Management Section`, 16 rows). Out
  of scope, deliberately.
- **Renaming or reshaping core `Farm`.** WM adds fields to it and reads it. It
  does not relabel it, reorder it, or change its mandatory fields.

## Field mapping

| `Work Management Farm` | lands on core `Farm` as |
|---|---|
| `farm_name` (Data, unique, `autoname: field:farm_name`) | core `farm_name` — identical shape and naming rule |
| `project` (Link Project, "Cost Project") | **new** `custom_project`, installed by WM |
| `area_ha` (Float, 2dp) | core `area` ("Area (Hectares)") — read by `dashboard.py:2812`; every value is 0.0, so nothing to carry |
| `disabled` (Check) | **new** `custom_disabled`, installed by WM |
| `business_unit` (Data, hidden, upgraded to Link at install) | **new** `custom_business_unit` (Link → Business Unit) |
| `description` (Small Text) | dropped — nothing reads it |

`disabled` deserves a note: core `Farm` does **not** ship one. The `disabled`
field on `kaitet.local` is a hand-made Custom Field, `module: None`, owner
otieno@upande.com, and `upande_scp/serverscripts/spray_plan_creator/admin.py:24`
reads it behind `frappe.db.has_column("Farm", "disabled")` — that app conceding
the same thing. WM owns `custom_disabled` rather than depending on someone's
UI edit. No row is disabled in either doctype today.

## Two constraints on how WM touches core `Farm`

**Never `.save()` a `Farm` document.** All 16 rows are missing `farm_type`
(`reqd: 1`) and Eldama is missing `company` (`reqd: 1`), so any `doc.save()`
raises *Farm Type is required*. WM writes its own fields with
`frappe.db.set_value` and the migration never round-trips a Farm doc.

**Insert fields explicitly, and expect interference.** Upande Kaitet owns four
Custom Fields on `Farm` (`custom_handles_sales`, `custom_sales_order_type`,
`custom_location`, `custom_column_break_32dil`) and a `field_order` Property
Setter naming `farm` and `kephis_farm_id` — fields core `Farm` does not have.
It is inert today (Frappe falls back to core's order) but a future upande_kaitet
fixture sync could reassert it and drop WM's fields off the form. Every WM field
is added with an explicit `insert_after`, and this risk is recorded in the
developer guide.

## Code changes

**`hooks.py`** — add `required_apps = ["upande_core"]`; delete the comment at
line 73 about upgrading `business_unit` to a Link once upande_core arrives, and
the hook it describes.

**`install.py`** — `CORE_CUSTOM_FIELDS`: `Employee.custom_farm` and
`Warehouse.custom_farm` options become `Farm` (lines 89, 94); add
`Farm.custom_project`, `Farm.custom_disabled`, `Farm.custom_business_unit`.
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
- `wm_farm.json` · `farm` (the deprecated Settings child table)

**Delete** `work_management/work_management/doctype/work_management_farm/`.

**`api/config.py`** — `_farms()` reads `Farm` with no `exists()` guard, fields
`["name", "custom_project"]`, filter `{"custom_disabled": 0}`; update the module
docstring (line 4) and the legacy-fallback comment (line 120).

**`approvals.py:509`** — farm list reads `Farm`, guard dropped.

**`taxonomy.py`** — remove the two `FIELD_LABELS` entries keyed to
`Work Management Farm` (`farm_name`, `business_unit`) and
`apply_business_unit_visibility()` entirely. WM must not write a Property Setter
against core `Farm`: it would relabel the field for every app that uses it
(spray plan, irrigation, sales). Consequence, accepted: the configurable
taxonomy can still rename WM's own `farm` link labels on Planner, Assigner,
Actuals, Payment and Section, but the farm record's own labels now belong to
Upande Core.

**`desk.py:69`** — `nav_label` key becomes `Farm`.

**Desk artifacts** — `workspace/work_management_setup/…json:29` and
`workspace_sidebar/work_management.json:289` link to `Farm`.

**`seed/kaitet.py:84,87,156`** — creates core `Farm` records via
`frappe.db.set_value` for WM's own fields only, and does not attempt to satisfy
core's mandatory fields; a farm it cannot create is reported, not invented.

**Existing patches** — `migrate_farms_and_approvers`, `backfill_farms_in_use`,
`seed_sections_from_cost_centres` and `enable_business_unit_level_if_used` all
already return early when `Work Management Farm` is absent, so they no-op once
the doctype is gone. `enable_business_unit_level_if_used` is deleted from
`patches.txt` along with the visibility machinery it drives.

**Settings** — `work_management_settings.json:103` describes the deprecated
`farms` table as "Superseded by the Work Management Farm doctype". Reword: it is
superseded by core `Farm`.

## The migration patch

`work_management.patches.v1_0.move_farms_to_upande_core`, `[post_model_sync]`:

1. **Collect every farm name in use.** From `Work Management Farm` where it
   still exists, from the deprecated `WM Farm` rows on Settings, and from every
   Link field in `backfill_farms_in_use.SOURCES` — which is already defined as
   "every Link field the app ships pointing at Work Management Farm".
2. **Abort on any name absent from core `Farm`**, listing each with what uses
   it (`Kabarak — 2 Warehouses`). The message says to create them in Upande
   Core with a real company, farm type and abbreviation, then re-run migrate.
   On kaitet.local this is exactly one name.
3. **Carry WM's fields across** with `frappe.db.set_value`: `project` →
   `custom_project`, `disabled` → `custom_disabled`, `business_unit` →
   `custom_business_unit`, and `area_ha` → `area` only where core's `area` is
   0 and `area_ha` is not.
4. **Clear stale overrides.** The JSON ships the new `options`, so this step
   only removes what a site wrote over it — Property Setters and Custom Field
   `options` still naming the old target. `install.is_stale_link_option()`
   (line 408) already decides this; reuse it rather than writing a second rule.
5. **Delete** the `Work Management Farm` doctype and its table, plus every
   Property Setter and Custom Field naming it.

Idempotent: a second run finds nothing in use that core lacks, no
`Work Management Farm` doctype, and exits.

## Tests

TDD — each of these is written before the change it describes.

- `test_api_doctype_guards.py`: `Work Management Farm` leaves `FRAGILE`.
  `test_the_fragile_list_is_all_doctypes_this_app_ships` (line 56) asserts every
  `FRAGILE` name is a doctype this app ships, so deleting the doctype *requires*
  this edit — the two stay consistent by construction. Every other guard stays.
- **New** `test_farm_source.py`: no shipped JSON has a Link whose `options` is
  `Work Management Farm`; `Farm` appears in no guard; `required_apps` names
  `upande_core`; WM writes no Property Setter against `Farm`; WM never calls
  `.save()`/`insert()` on a `Farm` doc (source-level assertion over `api/` and
  the app modules).
- **New** `test_move_farms_to_upande_core.py`: aborts and names the orphan;
  succeeds and carries the four fields when every name exists; is idempotent;
  leaves core `Farm` rows otherwise untouched.
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
`Farm` plus the three fields WM adds. `docs/DEVELOPER_GUIDE.md` — the farm
source, the never-`.save()`-a-`Farm` rule, and the upande_kaitet `field_order`
risk. `docs/manual_content.py` — where the user guide tells someone to add a
farm, it now points at Upande Core.

## Risks

| risk | disposition |
|---|---|
| WM stops installing without upande_core | accepted, by decision |
| A site whose `Farm` is Upande Kaitet's | install fails on the missing app before WM can read the wrong doctype |
| upande_kaitet reasserts its `field_order` Property Setter | WM's fields survive in the database; they can vanish from the form. Documented; explicit `insert_after` on every field |
| Core `Farm` rows fail their own mandatory fields | WM never saves a Farm doc; writes go through `frappe.db.set_value` |
| Taxonomy can no longer rename the farm level's own labels | accepted; renaming another app's field would leak into every app that uses it |
| Orphan farms block `bench migrate` | intended; the message names them and what uses them |

## Order of work

1. Tests for the end state (they fail).
2. `install.py` custom fields + `hooks.py` `required_apps`.
3. Repoint the 10 Link `options`; delete the doctype folder.
4. `config.py`, `approvals.py`, `taxonomy.py`, `desk.py`, `seed/kaitet.py`,
   workspace and sidebar JSON.
5. The migration patch.
6. `port_app.py` rewrite + `check_ported.py` green.
7. Docs.
8. Full suite green; then `bench migrate` on kaitet.local and drive the five
   screens plus the Master Plan screen against real data.
