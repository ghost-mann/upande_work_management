# Farms From Upande Core — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire `Work Management Farm`; Upande Core's `Farm` becomes the only farm doctype this app knows, read-only.

**Architecture:** Ten Link fields repoint from `Work Management Farm` to `Farm` (values are farm names and already exist in core, so no data is rewritten). What Core does not track — a farm's cost project and area override — moves to the farms table on Work Management Settings, which already has those columns and was slated for deletion. The app adds nothing to core `Farm`, writes no Property Setter against it, and never saves one of its documents. A patch carries the old rows across, clears references to farms Core lacks, and drops the doctype.

**Tech Stack:** Frappe v16 (bench at `~/frappe-v16-bench`, site `kaitet.local`), Python 3, `unittest`. The mirror repo at `/home/austin/vscodeProjects/kaitet-work-management` generates `api/*.py` via `port_app.py`.

**Spec:** `docs/superpowers/specs/2026-08-27-farm-from-upande-core-design.md`

## Global Constraints

- `required_apps = ["upande_core"]`. No `frappe.db.exists("DocType", "Farm")` guard anywhere.
- Core `Farm` is read-only to this app: no Custom Field on it, no Property Setter against it, no `.save()`/`.insert()`/`set_value` on it. All 16 rows on kaitet.local fail their own `reqd` fields (`farm_type`, and `company` on Eldama), so a write would raise anyway.
- `Employee.custom_farm` must be declared byte-identically to upande_kaitet's: label `Unit/Division`, `Link`, options `Farm`, `insert_after: grade`.
- `Warehouse.custom_farm` is Upande Core's. This app must not declare it.
- Business unit on a farm is dropped entirely. `Employee.custom_business_unit` stays as it is.
- Nothing is pushed to live. The mirror's server scripts are not edited; only `port_app.py` changes.
- Test command: `PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest discover -s work_management/tests -t . -p "test_*.py"` — 343 tests green before, all green after.

## File Structure

| file | responsibility after this change |
|---|---|
| `work_management/hooks.py` | declares upande_core required; drops the business-unit hooks from `after_migrate` |
| `work_management/install.py` | declares `Employee.custom_farm` to match upande_kaitet; no `Warehouse.custom_farm`; no business-unit Link machinery |
| `work_management/api/config.py` | farm list from `Farm`, `farm_project` from the Settings farms table |
| `work_management/taxonomy.py` | labels for this app's own fields only; nothing keyed to core `Farm` |
| `work_management/patches/v1_0/move_farms_to_upande_core.py` | **new** — carries rows across, clears orphans, deletes the doctype |
| `work_management/tests/test_farm_source.py` | **new** — source-level guards for every Global Constraint above |
| `/home/austin/vscodeProjects/kaitet-work-management/port_app.py` | rewrites the mirror's two farm-doctype reads into plain core-`Farm` reads |

---

### Task 1: Declare upande_core required

**Files:**
- Modify: `work_management/hooks.py`
- Test: `work_management/tests/test_farm_source.py` (create)

**Interfaces:**
- Produces: `test_farm_source.py` module, which later tasks add cases to. Reads the app's own source files; needs no site.

- [ ] **Step 1: Write the failing test**

```python
class TestUpandeCoreIsRequired(unittest.TestCase):
	def test_hooks_declares_upande_core_required(self):
		source = read("hooks.py")
		self.assertIn('required_apps = ["upande_core"]', source)
```

- [ ] **Step 2: Run it, expect FAIL**

`PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest work_management.tests.test_farm_source -v`

- [ ] **Step 3: Add `required_apps = ["upande_core"]` to hooks.py**, next to `app_name`, with a comment saying why: `Farm` belongs to Upande Core, a doctype name is global, and Upande Kaitet's `Farm` must never be what this app reads.

- [ ] **Step 4: Run it, expect PASS**

- [ ] **Step 5: Commit** — `Require upande_core, because "Farm" alone is ambiguous`

---

### Task 2: Stop fighting over the two `custom_farm` fields

**Files:**
- Modify: `work_management/install.py:89,94`
- Test: `work_management/tests/test_farm_source.py`

**Interfaces:**
- Consumes: `install.CORE_CUSTOM_FIELDS` — tuples of `(dt, fieldname, label, fieldtype, options, insert_after, extras)`.

- [ ] **Step 1: Write the failing tests**

```python
	def test_employee_farm_matches_upande_kaitet(self):
		row = field("Employee", "custom_farm")
		self.assertEqual(row[2:6], ("Unit/Division", "Link", "Farm", "grade"))

	def test_warehouse_farm_is_not_ours(self):
		self.assertIsNone(field("Warehouse", "custom_farm"))
```

- [ ] **Step 2: Run, expect two failures** — options is `Work Management Farm`, insert_after is `department`, and the Warehouse row exists.

- [ ] **Step 3: Edit `CORE_CUSTOM_FIELDS`** — `Employee.custom_farm` becomes `("Employee", "custom_farm", "Unit/Division", "Link", "Farm", "grade", {})`; delete the `Warehouse.custom_farm` row; repoint `Warehouse.custom_area_ha`'s `insert_after` to `custom_farm` still (Core's field, same name, so the anchor holds). Comment both: why the declaration is deliberately identical to another app's, and who owns the Warehouse one.

- [ ] **Step 4: Run, expect PASS**

- [ ] **Step 5: Commit** — `Declare the employee farm box identically, and leave the warehouse one to Core`

---

### Task 3: Repoint the ten Link fields and delete the doctype

**Files:**
- Modify: the 9 doctype JSONs + `wm_farm.json` listed in the spec
- Delete: `work_management/work_management/doctype/work_management_farm/`
- Modify: `work_management/tests/test_api_doctype_guards.py:28`
- Test: `work_management/tests/test_farm_source.py`

- [ ] **Step 1: Write the failing tests**

```python
	def test_no_shipped_link_points_at_the_old_farm_doctype(self):
		self.assertEqual(links_to("Work Management Farm"), [])

	def test_the_farm_doctype_is_gone(self):
		self.assertNotIn("Work Management Farm", install.shipped_doctypes())
```

- [ ] **Step 2: Run, expect FAIL** — ten links, and the doctype still ships.

- [ ] **Step 3: `sed` each `"options": "Work Management Farm"` to `"options": "Farm"`** in the ten JSONs; `git rm -r` the doctype folder; drop `"Work Management Farm"` from `FRAGILE` in `test_api_doctype_guards.py`.

- [ ] **Step 4: Run the full suite** — `test_the_fragile_list_is_all_doctypes_this_app_ships` proves the two stayed consistent.

- [ ] **Step 5: Commit** — `Point every farm link at Upande Core's Farm, and drop our own`

---

### Task 4: Read farms from Core, cost projects from Settings

**Files:**
- Modify: `work_management/api/config.py:32-40,118-126`
- Modify: `work_management/work_management/doctype/work_management_settings/work_management_settings.json:103-108`
- Modify: `work_management/work_management/doctype/wm_farm/wm_farm.json`
- Test: `work_management/tests/test_farm_source.py`, `work_management/tests/test_config.py` if present

- [ ] **Step 1: Write the failing test** — `_farms()` reads `Farm`, filters on `disabled` only where the column exists, and takes `farm_project` from the Settings farms table.

```python
	def test_farms_reads_core_farm_without_a_guard(self):
		source = read("api/config.py")
		self.assertIn('frappe.get_all(\n\t\t"Farm"', source)
		self.assertNotIn('exists("DocType", "Work Management Farm")', source)
```

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Rewrite `_farms()`**

```python
def _farms():
	"""Active farms from Upande Core, and their cost projects from Settings.

	Which farms exist is Upande Core's answer -- required_apps makes `Farm`
	unambiguous, so no exists() check stands here. `disabled` is not a field
	Core ships: where a site has added one this respects it, and where none
	exists every farm is active. upande_scp reads it the same way.
	"""
	filters = {}
	if frappe.db.has_column("Farm", "disabled"):
		filters["disabled"] = 0
	names = frappe.get_all("Farm", filters=filters, fields=["name"], order_by="creation asc")
	return [row.name for row in names], {}
```

and move `farm_project` to the Settings table branch, which stops being a fallback.

- [ ] **Step 4: Un-deprecate the Settings farms table** — remove `read_only` from the `farms` field, rewrite its description ("Each farm's cost project, and an area override where the farm's own area is not the figure to divide by. The farms themselves come from Upande Core."), repoint `wm_farm.json`'s `farm` Link to `Farm`, and rewrite `approver_role`'s description to keep it the only deprecated column.

- [ ] **Step 5: Run the full suite, expect PASS. Commit** — `Farms come from Core; their cost projects come from Settings`

---

### Task 5: The rest of the references

**Files:**
- Modify: `work_management/approvals.py:509`, `work_management/desk.py:69`, `work_management/taxonomy.py`, `work_management/hooks.py` (after_migrate), `work_management/install.py:347-404`, `work_management/patches.txt`
- Delete: `work_management/patches/v1_0/enable_business_unit_level_if_used.py`
- Modify: `work_management/work_management/workspace/work_management_setup/work_management_setup.json:29`, `work_management/workspace_sidebar/work_management.json:289`
- Test: `work_management/tests/test_farm_source.py`, `test_desk_sync.py`, `test_taxonomy.py`

- [ ] **Step 1: Write the failing tests**

```python
	def test_no_property_setter_targets_core_farm(self):
		for doctype, _field, _template in taxonomy.FIELD_LABELS:
			self.assertNotEqual(doctype, "Farm")
			self.assertNotEqual(doctype, "Work Management Farm")

	def test_business_unit_visibility_machinery_is_gone(self):
		self.assertFalse(hasattr(taxonomy, "apply_business_unit_visibility"))
		self.assertFalse(hasattr(install, "upgrade_business_unit_link"))
```

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Make the edits.** `approvals.validate_configuration` reads `Farm` unguarded; `desk.NAV_LABELS` keys on `Farm`; `taxonomy.FIELD_LABELS` loses its two `Work Management Farm` entries and gains nothing (the `("WM Farm", "farm")` entry already covers the Settings table); delete `apply_business_unit_visibility` and `business_unit_hidden`, `install.plan_business_unit_field` and `install.upgrade_business_unit_link`; drop both from `after_migrate` and rewrite that comment block; delete the business-unit patch and its `patches.txt` line; point the two nav JSONs at `Farm`.

- [ ] **Step 4: Update `test_desk_sync.py:246,250,343-348` and `test_taxonomy.py` to the new keys. Run the full suite.**

- [ ] **Step 5: Commit** — `Follow the farm through approvals, the desk and the taxonomy`

---

### Task 6: The Kaitet seed fills the mapping instead of making farms

**Files:**
- Modify: `work_management/seed/kaitet.py:56,81-93,156`
- Test: `work_management/tests/test_seed_kaitet.py` if present, else `test_farm_source.py`

- [ ] **Step 1: Write the failing test** — `ensure_farms` creates no `Farm`, and writes the four `FARMS` rows into the Settings farms table for farms that exist.

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Rewrite `ensure_farms()` as `ensure_farm_projects()`**, returning `(written, missing)`: for each `(farm, project)` in `FARMS`, skip when `Farm` has no such record (collect the name), otherwise upsert a row on the Settings farms table. `FARM_APPROVER_ROLE` loop at line 156 checks `Farm` instead of `Work Management Farm`.

- [ ] **Step 4: Run the full suite, expect PASS. Commit** — `The Kaitet seed carries the cost projects, not the farms`

---

### Task 7: The migration patch

**Files:**
- Create: `work_management/patches/v1_0/move_farms_to_upande_core.py`
- Modify: `work_management/patches.txt`
- Test: `work_management/tests/test_move_farms_to_upande_core.py` (create)

- [ ] **Step 1: Write the failing tests** — pure functions first, so they need no site: `rows_to_carry(wm_farms)` returns only farms with a project or a non-zero area; `orphans(names_in_use, core_names)` returns the set to clear.

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Write the patch.** `execute()`:
  1. return early unless `frappe.db.exists("DocType", "Work Management Farm")`
  2. carry `project` and `area_ha` into the Settings farms table
  3. for every `(doctype, fieldname)` in `backfill_farms_in_use.SOURCES`, blank values absent from `Farm` via `frappe.db.set_value`, printing each with what held it
  4. `install.drop_stale_link_options()` handles the leftover `options` overrides
  5. delete the doctype, its Property Setters and its Custom Fields

- [ ] **Step 4: Run the new tests and the full suite, expect PASS**

- [ ] **Step 5: Commit** — `Move the farms to Upande Core, and say what it cleared`

---

### Task 8: Teach port_app.py the rewrite

**Files:**
- Modify: `/home/austin/vscodeProjects/kaitet-work-management/port_app.py`
- Verify: `/home/austin/vscodeProjects/kaitet-work-management/scripts/check_ported.py`

- [ ] **Step 1: Run `python3 scripts/check_ported.py`, expect FAIL** — the app's `masterplan.py` and `dashboard.py` no longer match a fresh port.

- [ ] **Step 2: Add the rewrite** — `wm_masterplan`'s `for mp_farm_dt in ("Work Management Farm", "Farm"):` block becomes a plain `Farm` read; `wm_dashboard`'s guarded `Work Management Farm` / `area_ha` read becomes `Farm` / `area`.

- [ ] **Step 3: Run `python3 port_app.py`, then `python3 scripts/check_ported.py`, expect *all 10 api module(s) match a fresh port***

- [ ] **Step 4: Run `python3 sync.py diff`, expect the five trailing-newline diffs and nothing else** — proof live is untouched.

- [ ] **Step 5: Commit both repos** — the mirror's message says the app diverges here and why.

---

### Task 9: Docs

**Files:**
- Modify: `README.md`, `docs/DEVELOPER_GUIDE.md`, `docs/manual_content.py`

- [ ] **Step 1** — README: the portability claim gains its exception (upande_core required), and the `Work Management Farm` bullet becomes core `Farm` plus the Settings farms table.
- [ ] **Step 2** — DEVELOPER_GUIDE: where farms come from, the read-only rule and why (`farm_type` is `reqd` and unset on every row), and the note that upande_kaitet's `field_order` Property Setter on `Farm` is not ours.
- [ ] **Step 3** — `manual_content.py`: adding a farm is done in Upande Core; the cost project is set in Work Management Settings.
- [ ] **Step 4: Rebuild the manual if the build script is cheap; run the full suite. Commit** — `Tell the docs where farms live now`

---

### Task 10: Prove it on kaitet.local

- [ ] **Step 1: Full suite green.**
- [ ] **Step 2: `bench --site kaitet.local migrate`** — also picks up upande_core's new `farm_location`. Expect the patch to print what it carried and what it cleared (`Kabarak` on two Warehouses).
- [ ] **Step 3: Confirm the state** — `Work Management Farm` doctype gone; `Employee.custom_farm` is `Link → Farm` sitting after `grade`; 3,241 Employee and 528 Warehouse farm values unchanged; the two Kabarak warehouses blanked.
- [ ] **Step 4: Drive the six screens** — call `wm_dashboard`, `wm_planner`, `wm_assigner`, `wm_actuals`, `wm_payment`, `wm_masterplan` and confirm each returns its farms and no error.
- [ ] **Step 5: Commit anything the run turned up.**
