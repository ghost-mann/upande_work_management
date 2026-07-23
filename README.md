# Upande Work Management

A portable Frappe app for farm task-work management — the full pipeline in five
web pages backed by five API endpoints and a doctype family:

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
are byte-compatible with the original Web Page + Server Script implementation
on kaitet-group.upande.com.

## What's in the app

- **Doctypes** (module *Work Management*): Work Management Planner / Assigner /
  Actuals / Payment, children Work Planner Block, Work Assignment Employee,
  Work Actuals Employee, Work Payment Line, Work Management Task — including
  all the fields that lived as Custom Fields on live (close-request flow,
  approval timestamps, qty tracking).
- **API** (`upande_work_management/api/`): faithful ports of the five live
  Server Scripts. Same actions, same request/response shapes.
- **Work Management Settings** (single): farms (name + cost project + approver
  role), default company, block-exclude keywords. Empty settings = original
  Kaitet defaults, so behaviour is unchanged out of the box.
- **Fixtures**: the four approval Workflows, their Workflow States / Actions,
  and the roles the flow depends on.
- **Install hooks** (`install.py`):
  - `before_install` *adopts* the doctypes if they already exist on the site as
    custom doctypes (the kaitet-group case) — flips `custom=0`, points the
    module at this app, keeps all data.
  - `after_install` creates the custom fields needed on core doctypes
    (Employee/Warehouse `custom_farm`, Warehouse `custom_area_ha`,
    Task `custom_uom` / `custom_daily_target` / `custom_rate`, …). Link fields
    degrade to Data fields when the link target (e.g. the Kaitet `Farm`
    doctype) is not on the site.
- **Frontend**: the original page JS untouched (`public/js/`), re-skinned by
  `public/css/wm-theme.css` — Upande glass theme (Poppins + Fraunces, ink
  palette, frosted cards on a warm canvas, per-stage accent hues).

## Install

```bash
bench get-app https://github.com/<org>/upande_work_management
bench --site <site> install-app upande_work_management
bench --site <site> migrate
bench build --app upande_work_management
```

### Deploying to kaitet-group.upande.com (Frappe Cloud)

1. Push this repo to GitHub and add it to the bench group in the Frappe Cloud
   dashboard, then deploy + install on the site.
2. `before_install` adopts the existing custom doctypes automatically — data in
   `tabWork Management Planner` etc. is preserved.
3. After verifying the pages, **unpublish/delete the five old Web Page
   documents** (`work-management-dashboard`, `work-planner`, `work-assigner`,
   `work-actuals`, `work-payment`) and **disable the five Server Scripts**
   (Work Management Dashboard / Work Planner / Work Assigner / Work Actuals /
   Work Payment). The app's `www/` pages and API methods take over the same
   routes and method names. (Route resolution prefers the Web Page documents,
   so the app pages only show once the Web Pages are gone.)

### Installing on a fresh site

1. Install the app (doctypes, workflows, roles, custom fields are created).
2. Open **Work Management Settings** and enter your farms (one row each:
   farm name, cost project, approver role), default company and block-exclude
   keywords.
3. Set `custom_farm` on Warehouses (blocks) and Employees (task workers), and
   `custom_uom` / `custom_daily_target` / `custom_rate` on Tasks.
4. Give users the roles: Production Section Head (raise plans), farm approver
   roles, General Manager, HOD HR, and accounts roles for payment.

## Development

Local mirror + sync tooling for the live site lives in
`~/vscodeProjects/kaitet-work-management` (not part of this repo).

#### License

MIT
