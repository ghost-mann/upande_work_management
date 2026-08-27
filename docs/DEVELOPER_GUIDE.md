# Work Management — Developer Guide

Portable Frappe app packaging the work-management system: the pipeline doctypes,
five whitelisted API modules, five glass-themed web pages, its own desk
surfaces, and approval workflows generated from configuration.

## Repository layout

```
work_management/
├── hooks.py                  # override_whitelisted_methods, fixtures, install hooks
├── install.py                # adopts pre-existing custom doctypes, creates custom fields
├── api/
│   ├── config.py             # get_config(): farms, projects, company, approver roles
│   │                         #   farms from Upande Core's Farm, their cost
│   │                         #   projects from Work Management Settings
│   ├── planner.py assigner.py actuals.py payment.py dashboard.py
│   │                         # ported 1:1 from the live Server Scripts
├── approvals.py              # stage catalogue + workflow generator
├── seed/kaitet.py            # one deployment's own cost projects, roles, company
├── patches/v1_0/             # carries old farm/approver config forward
├── work_management/doctype/  # WM doctypes (see below)
├── work_management/workspace/ # the desk workspace
├── workspace_sidebar/        # the v16 sidebar (not read on v15)
├── public/js, public/css     # page JS + wm-theme.css (glass skin)
└── www/                      # web page shells (Jinja-escaped, boot-shim loader)
```

### API modules & endpoints
Each module exposes one whitelisted entry point taking `action` + params via
`frappe.form_dict`, e.g. `/api/method/wm_payment?action=pay_workers`.
`hooks.py override_whitelisted_methods` maps the bare names (`wm_payment`,
`wm_dashboard`, …) so the pages work unchanged from the mirror site.

**Porting rule:** the live site runs the same logic as Server Scripts
(sandbox: no `_`-attrs, `frappe.form_dict` in, `frappe.response["message"]`
out). The app versions are generated mechanically: strip the constant block,
wrap in `@frappe.whitelist() def wm_x(**kwargs)`, inject `get_config()`
constants, `return out`. Keep them in lockstep — change the live script first,
then regenerate the app module.

## Doctypes

Pipeline documents (all in module *Work Management*):

- **Work Management Planner** (+ **Work Planner Block**) — the plan; workflow
  PENDING → APPROVED/REJECTED by the farm approver role.
- **Work Management Assigner** (+ **Work Assignment Employee**) — workers on a
  plan; `assigned_by`, `approved_by` (GM). Substitution events derive from row
  changes.
- **Work Management Actuals** (+ **Work Actuals Employee**) — daily work rows;
  parent carries `entered_by`, `hr_approved_by`, `gm_approved_by`, `rate`,
  `assignment`; workflow to CONFIRMED.
- **Work Management Payment** (+ **Work Payment Line**) — see next section.
- **Work Management Task**, **WM Farm**, **Work Management Settings**.

### Payment structure (worker-centric)

`pay_worker_submit` creates **one Work Management Payment per employee** when
a reviewed worker is sent to accounts:

Parent (`WMPAY-#####`): `employee`, `employee_name`, `farm`, `period_from/to`,
`total_days`, `total_qty`, `grand_total`, `reviewed_by`, `reviewed_at`,
`prepared_by`, workflow `Pending Accounts → Paid` (or withdrawn back).

Lines (`Work Payment Line`) — **one row per actuals document** the worker
earned on: `actuals` (link, reqd), `task`, `block`, `work_from`, `work_to`,
`days`, `qty`, `rate`, `amount`, `assignment` and the accountability chain:
`assigned_by`, `fm_approved_by` (assignment approval), `entered_by` (actuals
input), `hr_approved_by`, `gm_approved_by`.

### Where state lives on the work rows

`Work Actuals Employee` rows carry the payment lifecycle:

- `paid` (0/1) — stamped by `pay_mark_paid` when accounts releases.
- `payment_ref` — the WMPAY doc that contains this row (set at send-to-accounts,
  cleared on withdraw). Row status ladder: no ref+unreviewed = *Unpaid*,
  reviewed = *Reviewed*, ref+unpaid = *Sent to accounts*, paid = *Paid*.
- **Reviews are stored here too**: `custom_reviewed` (Check),
  `custom_reviewed_by` (User), `custom_reviewed_at` (Datetime) — stamped by
  `pay_worker_review`, cleared by day edits and withdrawals, and copied onto
  the payment entry header (`reviewed_by/reviewed_at`) at submit.
- `count_in_payroll` — excluded rows never enter payment maths.

### Payment API actions (module `api/payment.py`, action=…)

| Action | Purpose |
|---|---|
| `pay_workers` | All payable/paid workers in window (status ladder, filters) |
| `pay_worker_history` | One worker's full review sheet (KPIs, per-task cards with approver chain, daily log, runs) |
| `pay_worker_review` | Stamp a worker's unpaid rows Reviewed |
| `pay_worker_edit_day` | Edit one day's qty (recompute, audit comment, un-review) |
| `pay_worker_submit` | Create the per-worker payment entry, stamp `payment_ref` |
| `pay_bulk_review` | Review several workers at once (`employees` CSV) |
| `pay_bulk_submit` | Send several reviewed workers (`employees` CSV) — one entry each; skips anyone with unreviewed rows (frontend chunks in batches of 25) |
| `pay_pending` | Entries awaiting accounts |
| `pay_mark_paid` | Release: mark entry Paid + stamp rows |
| `pay_run_withdraw` | Return to unpaid: clear refs/review stamps, delete entry |

## The taxonomy — naming the levels

The module ships calling things **Farm** and **Block**. A project that runs
estates and plots says so once, and every label follows. Nothing about the
data or the meaning of a level is configurable — only what it is called.

### The levels

`work_management/taxonomy.py` holds them, ordered outermost first:

| key | shipped name | notes |
|---|---|---|
| `bu` | Business Unit / Units | optional, **off** by default |
| `top` | Farm / Farms | always present |
| `unit` | Block / Blocks | always present |
| `section` | Section / Sections | **not a level in the chain** — it names the cost-centre grouping and its toggle |

Names live on **Work Management Settings** as `tax_<key>_singular` /
`tax_<key>_plural`, plus `tax_bu_enabled`. A blank or whitespace-only value
falls back to the shipped default rather than rendering an empty label
(`_pick()`), so clearing a field restores the original wording instead of
breaking a form.

### How a name reaches the desk

`apply_labels()` writes **Property Setters** — never edits to the shipped
JSON — so the app's files are the same on every site. `FIELD_LABELS` is the
catalogue: 27 `(doctype, fieldname, template)` triples, where a template looks
like `"{unit_singular} / {section_singular}"` or `"Two {top_plural}, one day"`.
`label_for()` fills one and leaves an unknown placeholder **visible** rather
than raising — a typo in a label should look wrong, not stop a migrate.

`plan_labels()` compares the rendered label against the **shipped JSON**
(`shipped_labels()`), not against the setter it wrote last time. Two
consequences worth knowing:

- a site that renamed nothing carries **zero** Property Setters, where it used
  to carry one per catalogued field, each restating the JSON;
- clearing a name **removes** its setter rather than writing the old word into
  one, which is what makes "clearing restores the original" literally true.

### How a name reaches the five web screens

`get_config()["taxonomy"]` → the www controller sets `context.taxonomy` → the
template emits `window.WM_TAXONOMY = {{ taxonomy | tojson }}` → the screen's JS
reads `TX(key, fallback)`.

**Escaping is not optional here.** Frappe does not enable Jinja autoescape, so
`{{ }}` emits markup verbatim; every taxonomy interpolation carries `| e`, and
every JS insertion goes through `esc(TX(...))`. Level names are admin-entered
Data fields with no character restriction and Settings is writable by HR
Manager, so an unescaped one is a stored-XSS path into a System Manager's
browser. Two guards hold the line: one requires every `TX(` in the dashboard JS
to be wrapped in `esc(` (with a single named exemption for the accessor that
feeds `.textContent` and `.placeholder`), and one blanks Jinja expressions in
the five templates and fails on any level word left in plain markup.

### How a name reaches the desk navigation

Workspace Links and Workspace Sidebar Items are **records, not doctype
fields**, so no Property Setter reaches them. `desk.relabel_navigation()` sets
them in place, keyed on what each entry *points at* rather than on its label —
after the first relabel the label is no longer the shipped one and would not be
found again. It runs from `desk.sync()` (so after every migrate, and after any
force-import that puts the shipped labels back) and from
`Settings.on_update`, so a rename does not wait for a migrate.

### Farms are Upande Core's, and read-only to this app

`Farm` belongs to `upande_core`, which `hooks.py` declares a `required_apps`
dependency. Three rules follow, all of them tested in
`tests/test_farm_source.py` rather than left as habits:

1. **No guard around a `Farm` read.** A doctype name is global, and
   `upande_kaitet` ships a `Farm` of its own — so a guard cannot tell the right
   one from the wrong one, while requiring the owning app can. And a guard
   around a doctype every screen depends on answers "no farms" rather than
   failing, which reaches a person as a blank screen with no reason on it.
2. **Nothing of ours goes on it.** No Custom Field, no Property Setter, no
   saved document. Each farm's cost project and area override live on the farms
   table in Settings instead. Relabelling `Farm.farm_name` from the taxonomy
   would have renamed the field for the spray plan, irrigation and sales
   screens too, which is why the farm level is the one name renaming cannot
   reach.
3. **Never `.save()` a `Farm`.** Every row on the live site is missing
   `farm_type`, which Core marks `reqd`, so a saved document is rejected by
   Core's own validation. Reads only; the migration patch writes with
   `frappe.db.set_value` and never touches `Farm` at all.

`disabled` is not a field Core ships. Where a site has added one (kaitet.local
has, by hand) this app respects it; where none exists every farm is active.
`upande_scp` reads it the same way, behind the same `has_column` check.

One thing on that doctype is *not* ours and should not be read as ours:
`upande_kaitet` owns a `field_order` Property Setter on `Farm` naming `farm` and
`kephis_farm_id`, fields Core's `Farm` does not have. It is inert — Frappe falls
back to Core's own order — but it is there.

### Business Unit — a name, not a field on the farm

`tax_bu_enabled` and the `tax_bu_*` names still exist, and still name the level
above the farm for Employee records (`Employee.custom_business_unit`, a Link to
`upande_core`'s `Business Unit`) and for reports. What went with the farm
doctype is the *farm's* business unit: Core's `Farm` has no such field, and this
app adds none.

The paragraphs below describe the visibility machinery as it was before that.
`tax_bu_enabled` decided whether the level existed on the form at all. The field
shipped `hidden: 1`; turning the level on wrote a `hidden=0` setter, turning it
off **deletes** that setter rather than writing `hidden=1` over a field that is
hidden anyway. Naming the level is deliberately not the same as having one:
typing "Division" into the template without ticking the box reveals nothing.
A one-time patch (`enable_business_unit_level_if_used`) turns the level on
wherever any farm already carries a business unit, so a site that had started
using the field does not watch it vanish on the next migrate.

### Section — deliberately not a level

A `Work Management Section` **owns a table of blocks**; a block does not name
its section. So setting one up means opening a section and adding blocks to it,
rather than opening 83 blocks. A block belongs to at most one section —
counted twice it would double its cost and the section totals would quietly
stop matching the block totals they are built from. Blocks in no section group
under `Unassigned`, so the section view always totals the same as the block
view it replaces, and the doctype refuses the name "Unassigned" for a real
section because `roll_up` would merge the two.

### Guards that keep it honest

- **The reverse-completeness guard.** The catalogue used to be checked in one
  direction only — every entry names a real field. Nothing asked the reverse,
  so a field added after the catalogue was frozen was invisible to it; that is
  how `Work Management Section`, the one doctype this feature shipped, became
  the one place the feature did not apply to itself. The guard now scans every
  shipped DocType JSON for a label containing any level's shipped name and
  fails listing each one the catalogue does not carry. It found seven.
- **Named omissions.** `att_block_absent` — "block employees marked Absent" is
  a verb — and the `tax_*` fields themselves, because renaming "Farm level
  (singular)" the moment somebody types Estate into it hides the one label that
  explains what the field does. A second test fails if an exception outlives
  its field.
- **The generated-wording test** asserts every template renders to today's
  shipped wording, so an upgraded site looks unchanged until somebody edits the
  template.

### What the taxonomy deliberately does not touch

- **Doctype names.** A DocType's name is its identity.
- **Fieldnames, workflow states, roles.** "Farm Manager" is a real Role and is
  not renamed by the taxonomy.
- **Payroll export column headers.** The Excel/CSV exports build rows as
  `{Farm: ..., Block: ...}`, whose keys become the column headers — a data
  contract something downstream reads, not a label.
- **Reports.** Nothing groups by Business Unit. The Settings description, the
  README and the shipped guide used to promise that it did; the claim was
  removed rather than the feature invented.

### On the live site

None of this exists there yet. `kaitet-group.upande.com` has **no `tax_*`
fields**, and no `Work Management Section` doctype — its farms are records of
its own `Farm`, which belongs to `upande_kaitet` rather than to Upande Core —
its Work Management doctypes are custom records that the app has never been
installed over. The taxonomy is app-only until that install happens, and the
dashboard's Group toggle correctly falls back to block mode there.

## Time & Attendance gate

Toggles live on **Work Management Settings** (Single): `att_block_absent`,
`att_block_leave`, `att_block_off` — read with `get_single_value` inside a
try/except (missing doctype = checks default ON). Absent means a *submitted*
Attendance with status Absent; missing records never block.

- `a_employees` enriches each worker with `att_leave`, `att_absent_days`/
  `att_absent_span`, `att_all_off` (+ `out["att_checks"]` = active toggles)
  for badges and the pick-time confirm.
- `a_submit` (assigner) and `act_submit` (actuals) enforce server-side: on
  conflict they return `{needs_att_override: 1, att_conflicts: [{employee,
  name, reasons[]}]}` **without writing**; the frontend confirms once and
  retries with `att_override=1`. Overrides are logged via `add_comment` on the
  document and reported back as `att_overridden`.
- Semantics: assigner flags leave/absent anywhere in the plan window but offs
  only when they cover the WHOLE window (weekly offs inside long windows are
  normal); actuals checks the exact work date for all three.

**Rate precision:** `Task.custom_rate` (the task list that seeds plans) and
the `rate` fields on Planner / Actuals / Work Payment Line carry
`precision: "4"` — rates like 340/150 store as 2.2667, not 2.27. Stored task
rates in the 340 wage band were re-derived as round(340/daily_target, 4).

**Wage snap:** plan rates rounded to 2dp made full days pay 340.50/339.96
instead of the intended 340. `act_submit` values rows at qty × (340 ÷
daily_target) whenever the plan's implied daily wage (rate × daily_target) is
within 1% of 340; `pay_recalc_wages` (dry_run supported, 800-row chunks)
repairs historical unpaid rows the same way. Absent-day overrides in
`act_submit` require a farm-approver / GM / System Manager role — other
conflicts keep the normal logged override.

**Morning presence (scans):** settings `att_require_scan`, `att_scan_cutoff`
(Time — values come back unpadded, normalise before string-comparing!) and
`att_block_noscan_actuals`. When the window includes today, `a_employees`
returns `scan_info` {checked, gate_on, cutoff, cutoff_passed, present_count,
total} and per-worker `scan_in` (HH:MM), `present_today`, `is_night` (night =
Shift Type end < start via default_shift; exempt). Presence = today's
`Employee Checkin` scan OR submitted Present/Half Day/WFH Attendance.
`a_submit` adds a "no scan today" conflict only after the cutoff; `act_submit`
flags (employee, work_date) pairs ≤ today with no scan and no attendance,
suppressed when the day is already explained by absence/leave/off. Sandbox
gotcha: variable names starting with `_` are rejected by RestrictedPython.

## Porting to the app

The mirror's `port_app.py` regenerates all the `api/*.py` modules
from the mirror server scripts (strips constants, swaps farm-role if-chains
for the `FARM_APPROVER_ROLE` loop, wraps + indents, `return out`). Edit the
mirror script, `python3 port_app.py`, never the app module directly.

## Web pages

`www/*.html` render the shells (wrapped in `{% raw %}` — the inline CSS makes
Jinja choke otherwise) and load `public/js/*.js` via a boot shim that waits for
`window.frappe`. The glass skin (`public/css/wm-theme.css`) re-values each
page's CSS variables and frosts the surfaces; page roots: `#wmp #wpp #wap #acp
#wpay`.

## Install / deploy

```bash
bench get-app https://github.com/ghost-mann/work_management
bench --site <site> install-app work_management
```

`before_install` adopts identically-named custom doctypes already on the site
(sets `custom=0`, module Work Management); `after_install` creates the custom
fields (Employee farm, actuals review/payment stamps, …) with a Link→Data
fallback when a target doctype is missing. Farms are Upande Core's `Farm`
records; their cost projects and roles are configured in **Work Management
Settings**. No farms in Core means no farms in `api/config.py`, and the screens
say so.

## The upstream live-site mirror

The upstream site runs this system as Web Pages + Server Scripts, mirrored in
the `kaitet-work-management` repo:

```
sync.py pull            # refresh local copies from live
sync.py diff            # local vs live
sync.py push <file...>  # deploy (web_pages/*.html|js, server_scripts*/*.py)
```

Credentials come from `.env` (`API_KEY`/`API_SECRET`, gitignored). Every
change ships twice: push to live via `sync.py`, then regenerate/copy into this
app and push to GitHub.
