# Note for the mirror (port_app.py)

This branch (`mutara`) edits the generated `work_management/api/*.py` files by hand.
The mirror must carry the same changes or the next port overwrites them.

New Work Management Settings fields (all in `work_management_settings.json`):
- `known_daily_wages` (Small Text, Rates tab): comma-separated wage tiers, e.g. `340, 350`.
- `default_worker_employment_type` (Link Employment Type, General tab): blank means "Task Worker".
- `payroll_pack_company` (Link Company, Payroll pack section): blank means Default Company.

Python outside the generated files
- `rates.py`: `LEGACY_DAILY_WAGE` and `KNOWN_DAILY_WAGES` removed; new `known_wages()` and
  `fallback_wage()` read Settings; `classify()` returns `unknown` when no tier is configured.
- `payroll_pack.py`: `TASK_PAY_COMPANY` removed; new `pack_company()`.
- `patches/v1_0/seed_wage_and_company_settings.py` (registered in patches.txt).

Generated API files
- `api/config.py` (not generated): `get_config()` gains `default_worker_employment_type`
  (default "Task Worker", overridden from Settings).
- `api/actuals.py`, `api/assigner.py`, `api/payment.py`, `api/dashboard.py`: add
  `DEFAULT_WORKER_TYPE = _cfg["default_worker_employment_type"]` after `DEFAULT_COMPANY`.
  - actuals/assigner/payment: the `TW_CLAUSES` fallback is
    `"<alias>.employment_type = " + frappe.db.escape(DEFAULT_WORKER_TYPE)` instead of the literal.
  - payment: workforce pool query, the zero-value query and the repair check
    (`etype != DEFAULT_WORKER_TYPE`, and the value written back to `employment_type`) use
    `DEFAULT_WORKER_TYPE`; the SQL ones take it as a `%s` parameter.
  - dashboard: the workforce CASE/GROUP BY and the zero-value KPI query take it as `%s`
    parameters (CASE param, then farm tuple, then GROUP BY CASE param; for the KPI query it
    sits between `entered_by` and the two dates).
  - actuals (`wage snap`, ~line 1193): `snap_wage = 340.0` replaced by Settings
    `current_daily_wage` (0 when empty); the snap is skipped when `snap_wage` is not > 0.
- `api/rates.py`: the inline `LEGACY_DAILY_WAGE` / `KNOWN_DAILY_WAGES` literals become
  `_rates.fallback_wage()` / `list(_rates.known_wages())` (`from work_management import rates as _rates`);
  `backfill` treats an empty tier list as `unknown`; the confirm fallback basis is `None` when no wage is known.

Tests: `test_rates.py` passes the 340/350 tiers explicitly and gains Settings-driven cases;
`test_payroll_pack_send.py` patches `pack_company()` to "Kaitet Ltd.".

Also (same pass)
- `api/payment.py` `pay_recalc_wages`: `WAGE = 340.0` / `BAND = 3.4` become Settings `current_daily_wage`
  and `WAGE * 0.01`; the plan scan is skipped when the wage is 0.
- `api/dashboard.py` team-leader visibility: the role list no longer names "HR Manager Kaitet"
  (it names "HR Manager"; `seed/kaitet.py` already carries HR Manager Kaitet holders into HR Manager).
