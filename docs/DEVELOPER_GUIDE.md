# Upande Work Management — Developer Guide

Portable Frappe app packaging the Kaitet work-management system: nine custom
doctypes, five whitelisted API modules, five glass-themed web pages, and the
workflows/roles as fixtures.

## Repository layout

```
upande_work_management/
├── hooks.py                  # override_whitelisted_methods, fixtures, install hooks
├── install.py                # adopts pre-existing custom doctypes, creates custom fields
├── api/
│   ├── config.py             # get_config(): farms, projects, company, approver roles
│   │                         #   from Work Management Settings (Kaitet defaults fallback)
│   ├── planner.py assigner.py actuals.py payment.py dashboard.py
│   │                         # ported 1:1 from the live Server Scripts
├── work_management/doctype/  # WM doctypes (see below)
├── public/js, public/css     # page JS + wm-theme.css (glass skin)
└── www/                      # web page shells (Jinja-escaped, boot-shim loader)
```

### API modules & endpoints
Each module exposes one whitelisted entry point taking `action` + params via
`frappe.form_dict`, e.g. `/api/method/wm_payment?action=pay_workers`.
`hooks.py override_whitelisted_methods` maps the bare names (`wm_payment`,
`wm_dashboard`, …) so the pages work unchanged from the Kaitet site.

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

`kaitet-work-management/port_app.py` regenerates all five `api/*.py` modules
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
bench get-app https://github.com/ghost-mann/upande_work_management
bench --site <site> install-app upande_work_management
```

`before_install` adopts identically-named custom doctypes already on the site
(sets `custom=0`, module Work Management); `after_install` creates the custom
fields (Employee farm, actuals review/payment stamps, …) with a Link→Data
fallback when a target doctype is missing. Configure farms/roles in
**Work Management Settings**; blank settings fall back to the Kaitet defaults
in `api/config.py`.

## The Kaitet live-site mirror

The live site (kaitet-group.upande.com) runs this system as Web Pages +
Server Scripts, mirrored in the `kaitet-work-management` repo:

```
sync.py pull            # refresh local copies from live
sync.py diff            # local vs live
sync.py push <file...>  # deploy (web_pages/*.html|js, server_scripts*/*.py)
```

Credentials come from `.env` (`API_KEY`/`API_SECRET`, gitignored). Every
change ships twice: push to live via `sync.py`, then regenerate/copy into this
app and push to GitHub.
