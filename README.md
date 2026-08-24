# Work Management

A portable Frappe app for task-work management — the full pipeline in five web
pages backed by five API endpoints and a doctype family:

```
Plan (Work Management Planner) → Assign (… Assigner) → Capture (… Actuals) → Pay (… Payment)
```

| Route              | Page            | API endpoint                 |
|--------------------|-----------------|------------------------------|
| `/work-management` | Command Centre  | `/api/method/wm_dashboard`   |
| `/work-planner`    | Planner         | `/api/method/wm_planner`     |
| `/work-assigner`   | Assigner        | `/api/method/wm_assigner`    |
| `/work-actuals`    | Actuals         | `/api/method/wm_actuals`     |
| `/work-payment`    | Payment         | `/api/method/wm_payment`     |

The bare method names are kept via `override_whitelisted_methods`, so the pages
are byte-compatible with the Web Page + Server Script implementation this app
was extracted from.

Nothing about any one customer is compiled in. Farms, the company, and who
approves each step are configuration. A fresh install has no farms and no
approvers, and the screens say so rather than offering someone else's.

## What's in the app

- **Doctypes** (module *Work Management*): Work Management Master Plan /
  Planner / Assigner / Actuals / Payment, Work Management Farm, Work Task Rate,
  Work Rate Recalc Run, and their child tables.
- **API** (`work_management/api/`): ports of the five Server Scripts, generated
  from the upstream mirror by its `port_app.py`. Edit the mirror script, not
  these files.
- **Work Management Settings** (single): the approval stages and their
  approvers, default company, block-exclude keywords, attendance and
  discrepancy checks, rates and payroll settings, header logo.
- **Work Management Farm**: the unit work is planned against — farm, estate,
  site, division, whatever your project calls it — with its cost project.
- **Desk surfaces**: a Workspace, a v16 Workspace Sidebar, and an apps-screen
  entry (`add_to_apps_screen`). The sidebar is v16-only and is simply not read
  on v15.
- **Generated workflows**: the five approval workflows are built from the stage
  configuration by `work_management/approvals.py`, not shipped as fixtures.
- **Install hooks** (`install.py`):
  - `before_install` *adopts* the doctypes if they already exist on the site as
    custom doctypes — flips `custom=0`, points the module at this app, keeps all
    data.
  - `after_install` creates the custom fields needed on core doctypes
    (Employee/Warehouse `custom_farm`, Warehouse `custom_area_ha`,
    Task `custom_uom` / `custom_daily_target` / `custom_rate`, …), then seeds
    the approval stages and generates the workflows.

## Approvals

Every step of every chain is a row in **Work Management Settings → Approval
Stages**: the step, the document it belongs to, whether it is on, and the role
that takes it. **Stage Approvers** names the people, one row each, and saving
grants them the stage's role.

The workflows are generated from those rows, so they stay ordinary role-based
Frappe workflows — approvers keep the action buttons, the notifications and the
awaiting-approval inbox.

- Switching a stage off relinks the chain: with `Assigner: GM` off, HR approval
  goes straight to Assigned.
- Submit steps cannot be switched off.
- On a farm-scoped stage, give each farm its own approver and role override to
  keep one farm's approvals out of another's reach. Leaving an approver's Farm
  empty lets them act on every farm. Settings refuses to save a configuration
  that would leave a farm with nobody to approve its work.

Adding a stage is a change to `CATALOGUE` in `work_management/approvals.py`;
the next `bench migrate` seeds it and rebuilds the workflows.

## Install

```bash
bench get-app https://github.com/<org>/work_management
bench --site <site> install-app work_management
bench --site <site> migrate
bench build --app work_management
```

Supports Frappe 15 and 16.

### Installing on a fresh site

1. Install the app. Doctypes, roles, custom fields, the approval stages and the
   workflows are created.
2. Create a **Work Management Farm** for each unit you plan work against, with
   its cost project.
3. Open **Work Management Settings**:
   - under **Approvals**, set the role for each stage and add the people to
     Stage Approvers;
   - set the default company and the block-exclude keywords;
   - optionally set a header logo.
4. Set `custom_farm` on Warehouses (blocks) and Employees (task workers), and
   `custom_uom` / `custom_daily_target` / `custom_rate` on Tasks.

### Migrating a site that ran the earlier version

`work_management.patches.v1_0.migrate_farms_and_approvers` runs on migrate and
carries the old configuration forward: the `WM Farm` rows in Settings become
Work Management Farm records, and `approver_role` plus `consultant_users`
become Stage Approver rows. Both source fields stay read-only for one release
so the patch can read them.

One behaviour change to know about: the workflows this replaced carried an
unconditional `Farm Manager` transition alongside the per-farm ones, so anyone
holding the plain role could approve any farm. Once per-farm approvers are
configured, only they can.

### Site-specific configuration

`work_management/seed/kaitet.py` holds one deployment's own values — farms,
roles, company, per-farm approvers — and is the only module in the repo that
knows them:

```bash
bench --site <site> execute work_management.seed.kaitet.execute
```

### If the workspace, sidebar or app icon do not appear

All three surfaces are derived from `Workspace.module` and `Workspace.app` on a
single record. Frappe skips a standard JSON when the record already in the
database has a newer `modified` than the file, so a Work Management workspace
built in the desk — one filed under Projects, say — silently beats the one this
app ships, and the surviving record belongs to the wrong app. Nothing reports
this; the surfaces just are not there.

`work_management.desk.sync` repairs it on install and on every migrate. To run
it now rather than wait for a migrate:

```bash
bench --site <site> execute work_management.desk.sync
```

It re-points the workspace at this app, force-imports the shipped definition and
rebuilds the desktop icon. A workspace that is already correct is left alone.

## The user guide

`docs/Work_Management_User_Guide.pdf` is the document to hand people. Part I is
the operations manual for everyone using the system day to day; Part II is the
setup and administration guide for whoever installs it on a new project.

Rebuild it after changing the approval stage catalogue or the Settings doctype —
the stage catalogue and the settings reference are generated from the code, so
they are only correct as of the last build:

```bash
env/bin/python docs/build_manual.py     # writes the PDF and the DOCX
```

The words live in `docs/manual_content.py`; `docs/build_manual.py` renders them.
It needs the bench environment's python for WeasyPrint.

## Development

The upstream mirror and its sync tooling live in
`~/vscodeProjects/kaitet-work-management` (not part of this repo). Run its
`port_app.py` after every Server Script change to regenerate `api/*.py`.

Tests need no site and no database:

```bash
./env/bin/python -m unittest discover -s apps/work_management/work_management/tests -t apps/work_management
```

#### License

MIT
