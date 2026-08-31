# Two Master Plans Over One Period — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A farm may hold more than one master plan over the same days, and each planner request records which plan it draws against instead of that being inferred from its dates.

**Architecture:** The relationship between a request and its budget stops being an inference and becomes a stored `master_plan` link on `Work Management Planner`. The resolution rule — stored link first, date containment as the fallback, refuse when two plans match and nothing is stored — lives as a pure function in `work_management/master_plan.py`, which is already the unit-tested home for the cap arithmetic. The overlap check keeps reporting a clash but stops rejecting it. A patch backfills the 1,578 existing live requests, which is unambiguous precisely because overlap has been forbidden until now.

**Tech Stack:** Frappe v16 (bench `~/frappe-v16-bench`, site `kaitet.local`), Python 3, `unittest`. The mirror at `/home/austin/vscodeProjects/kaitet-work-management` holds the Server Scripts live runs; `port_app.py` generates `work_management/api/*.py` from them. Screens are vanilla JS in `work_management/public/js/` mirrored to `web_pages/`.

**Spec:** `docs/superpowers/specs/2026-08-28-two-master-plans-one-period-design.md`

## Global Constraints

- **The mirror is the source for `api/*.py`.** Never hand-edit a file in `work_management/api/` — edit `server_scripts/<name>.py` in the mirror and run `python3 port_app.py <name>`. `scripts/check_ported.py` must report *all 10 api module(s) match a fresh port*.
- **No `def` or `return` in the mirror.** Server Scripts run in a sandbox; every action is an inline `elif action == "...":` block. Pure helpers go in the app's `master_plan.py`, and the mirror inlines the arithmetic.
- **Live's Work Management doctypes are custom doctypes.** Both new fields must exist on live as Custom Fields *before* any script reading them is pushed, or those reads return nothing. This is a deployment step, not a code change.
- **Never `.save()` a submitted document.** Planner, Assigner, Actuals and Payment are submittable; use `frappe.db.set_value(..., update_modified=False)`.
- **Empty means all, never none.** Follow the precedent set by `config.farms_in_use`: a setting nobody has touched must not empty a screen.
- **Test command:** `PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest discover -s work_management/tests -t . -p "test_*.py"` — 390 tests green before this plan, all green after each task.
- **JS parity:** after editing a screen, copy it to the mirror and `node --check` both.

## File Structure

| file | responsibility |
|---|---|
| `work_management/master_plan.py` | **the resolution rule** — `resolve_master_plan(stored, candidates)`, pure, no site |
| `work_management/work_management/doctype/work_management_master_plan/…json` | gains `plan_name` |
| `work_management/work_management/doctype/work_management_planner/…json` | gains `master_plan` |
| `work_management/patches/v1_0/link_planners_to_their_master_plan.py` | **new** — backfills the link |
| `<mirror>/server_scripts/wm_masterplan.py` | overlap warns; `plan_name` accepted and returned |
| `<mirror>/server_scripts/wm_planner.py` | `tasks` and `save` honour the named plan; `save` stores it |
| `<mirror>/server_scripts/wm_dashboard.py` | `mp_value` and `plan_completion` attribute by the stored link |
| `work_management/public/js/work-planner.js` + mirror copy | the plan chips become the selector; the choice is sent |
| `work_management/tests/test_master_plan_resolution.py` | **new** — the rule |
| `work_management/tests/test_link_planners_patch.py` | **new** — the backfill |

---

### Task 1: The resolution rule

**Files:**
- Modify: `work_management/master_plan.py`
- Test: `work_management/tests/test_master_plan_resolution.py` (create)

**Interfaces:**
- Produces: `resolve_master_plan(stored, candidates) -> (name, error)`. `stored` is the request's `master_plan` or `""`/`None`. `candidates` is a list of plan names whose period contains the request's dates. Returns `(name, None)` on success, `(None, reason)` when it must refuse. Every later task calls this.

- [ ] **Step 1: Write the failing test**

```python
from work_management.master_plan import resolve_master_plan

class TestResolution(unittest.TestCase):
	def test_a_stored_link_wins_even_when_others_contain_the_dates(self):
		self.assertEqual(resolve_master_plan("WMMP-2", ["WMMP-1", "WMMP-2"]), ("WMMP-2", None))

	def test_one_candidate_and_nothing_stored_resolves_to_it(self):
		"""Every request written before the field existed looks like this."""
		self.assertEqual(resolve_master_plan("", ["WMMP-1"]), ("WMMP-1", None))

	def test_two_candidates_and_nothing_stored_refuses(self):
		name, reason = resolve_master_plan("", ["WMMP-1", "WMMP-2"])
		self.assertIsNone(name)
		self.assertIn("WMMP-1", reason)
		self.assertIn("WMMP-2", reason)

	def test_no_candidate_refuses_and_says_so(self):
		name, reason = resolve_master_plan("", [])
		self.assertIsNone(name)
		self.assertIn("no approved master plan", reason.lower())

	def test_a_stored_link_that_does_not_contain_the_dates_refuses(self):
		name, reason = resolve_master_plan("WMMP-9", ["WMMP-1"])
		self.assertIsNone(name)
		self.assertIn("WMMP-9", reason)
```

- [ ] **Step 2: Run it, expect FAIL**

`PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest work_management.tests.test_master_plan_resolution -v`
Expected: `ImportError: cannot import name 'resolve_master_plan'`

- [ ] **Step 3: Implement it**

```python
def resolve_master_plan(stored, candidates):
	"""Which master plan a request draws against. Returns (name, reason).

	The link the request carries wins. It has to: once two plans can cover the
	same days, the dates no longer identify a budget, and picking the first by
	period would silently draw somebody's work down against the wrong money.

	Nothing stored is the shape of every request written before the field
	existed. One candidate is then unambiguous and is used. Two is refused
	rather than guessed -- guessing which budget work came from is the error
	this whole change exists to prevent.
	"""
	names = [n for n in (candidates or []) if n]
	if stored:
		if stored in names:
			return stored, None
		return None, (
			f"{stored} does not cover this request's farm and dates. "
			"Choose a master plan whose period contains them."
		)
	if not names:
		return None, (
			"No approved master plan covers these dates for this farm. "
			"A master plan must be approved before work can be planned."
		)
	if len(names) > 1:
		return None, (
			"More than one approved master plan covers these dates: "
			+ ", ".join(sorted(names))
			+ ". Say which one this work is planned against."
		)
	return names[0], None
```

- [ ] **Step 4: Run it, expect PASS. Then the full suite.**

- [ ] **Step 5: Commit** — `Decide which master plan a request draws against, once`

---

### Task 2: The two fields

**Files:**
- Modify: `work_management/work_management/doctype/work_management_master_plan/work_management_master_plan.json`
- Modify: `work_management/work_management/doctype/work_management_planner/work_management_planner.json`
- Test: `work_management/tests/test_master_plan_resolution.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Work Management Master Plan.plan_name` (Data) and `Work Management Planner.master_plan` (Link → Work Management Master Plan). Tasks 3-6 read both.

- [ ] **Step 1: Write the failing test**

```python
class TestTheFields(unittest.TestCase):
	def test_the_plan_carries_a_purpose(self):
		f = field("work_management_master_plan", "plan_name")
		self.assertEqual(f["fieldtype"], "Data")
		self.assertFalse(f.get("reqd"), "a plan raised before this field existed has none")

	def test_the_request_carries_its_plan(self):
		f = field("work_management_planner", "master_plan")
		self.assertEqual(f["fieldtype"], "Link")
		self.assertEqual(f["options"], "Work Management Master Plan")

	def test_the_link_is_not_reqd_on_the_doctype(self):
		"""Enforced in save() where it can be conditional: a farm with no plan at
		all must still be able to raise a request, and 1,578 rows predate this."""
		self.assertFalse(field("work_management_planner", "master_plan").get("reqd"))
```

- [ ] **Step 2: Run it, expect FAIL** — both fields absent.

- [ ] **Step 3: Add the fields.** `plan_name` goes after `farm` in `field_order`, label "Purpose", with description "What this plan is for — Field operations, Replanting. Two plans can cover the same farm and dates, and this is how a person tells them apart." `master_plan` goes after `farm` on the Planner, label "Master Plan", read_only 1 (the screen sets it), description "The budget this request draws against."

  Also set the Master Plan's `title_field` to `plan_name`. It is `farm` today, so
  two Saboti plans render identically in every link field and list; the purpose is
  the only thing that distinguishes them. A plan raised before this field existed
  has none, and Frappe falls back to the docname there, which is the old behaviour.

- [ ] **Step 4: Run the full suite, expect PASS.**

- [ ] **Step 5: Commit** — `Give a plan a purpose, and a request the plan it draws against`

---

### Task 3: Overlap warns instead of blocking

**Files:**
- Modify: `<mirror>/server_scripts/wm_masterplan.py` — the `period_free` action (~line 92) and the save clash check (~line 286)
- Test: `work_management/tests/test_master_plan_resolution.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `period_free` keeps returning `clash`/`clash_from`/`clash_to`/`clash_state` but `free` is always 1; `save` no longer sets `sv_err` for a clash and returns `out["clash_warning"]` instead.

- [ ] **Step 1: Write the failing test** — grep the ported module, since the mirror is not importable:

```python
class TestOverlapNoLongerBlocks(unittest.TestCase):
	def setUp(self):
		with open(os.path.join(HERE, "api", "masterplan.py")) as h:
			self.src = h.read()

	def test_a_clash_no_longer_becomes_an_error(self):
		self.assertNotIn("already has a master plan covering those dates", self.src)

	def test_a_clash_is_still_reported(self):
		self.assertIn('out["clash"]', self.src)
		self.assertIn("clash_warning", self.src)
```

- [ ] **Step 2: Run it, expect FAIL.**

- [ ] **Step 3: Edit the mirror.** In `period_free`, set `out["free"] = 1` unconditionally and keep populating the clash keys. In `save`, replace the `sv_err = (...)` assignment with:

```python
            if sv_clash:
                sv_c = sv_clash[0]
                # Reported, not refused. A farm can run separate streams of work
                # over the same days -- field operations and a replanting project
                # -- each with its own budget. What used to be an invariant is now
                # a fact worth knowing: raising the same plan twice by mistake
                # looks identical to raising a deliberate second one, and this is
                # the moment that is cheapest to notice.
                out["clash_warning"] = (
                    str(sv_farm) + " already has a master plan over these dates: " +
                    sv_c.name + " (" + str(sv_c.period_from) + " to " +
                    str(sv_c.period_to) + ", " + str(sv_c.workflow_state) +
                    "). Raising a second one is allowed; give each a purpose so "
                    "they can be told apart.")
                out["clash"] = sv_c.name
```

- [ ] **Step 4: Port and verify** — `python3 port_app.py wm_masterplan && python3 scripts/check_ported.py`, then the full suite.

- [ ] **Step 5: Commit both repos** — `Let a farm hold a second budget over the same days`

---

### Task 4: The planner honours the named plan

**Files:**
- Modify: `<mirror>/server_scripts/wm_planner.py` — `tasks` (~line 69), `save`'s cap lookup (~line 334) and the document write (~line 406)
- Test: `work_management/tests/test_master_plan_resolution.py`

**Interfaces:**
- Consumes: `resolve_master_plan` from Task 1 (inlined in the mirror, imported in the app's tests).
- Produces: `tasks` and `save` accept `master_plan` in `frappe.form_dict`; `save` writes `d.master_plan`.

- [ ] **Step 1: Write the failing test**

```python
class TestThePlannerStoresIt(unittest.TestCase):
	def setUp(self):
		with open(os.path.join(HERE, "api", "planner.py")) as h:
			self.src = h.read()

	def test_save_reads_a_named_plan_from_the_request(self):
		self.assertIn('frappe.form_dict.get("master_plan")', self.src)

	def test_save_writes_the_link_onto_the_document(self):
		self.assertIn("d.master_plan =", self.src)

	def test_it_no_longer_takes_the_first_plan_by_period(self):
		"""ORDER BY period_from DESC LIMIT 1 is the bug once two plans overlap."""
		block = self.src[self.src.index("MASTER PLAN CAP"):][:1200]
		self.assertNotIn("LIMIT 1", block)
```

- [ ] **Step 2: Run it, expect FAIL.**

- [ ] **Step 3: Edit the mirror.** The cap lookup drops `ORDER BY … LIMIT 1` and returns every containing plan; the named plan is then chosen from them by the inlined rule:

```python
        mp_named = frappe.form_dict.get("master_plan") or ""
        cap_all = frappe.db.sql("""
            SELECT name, period_from, period_to FROM `tabWork Management Master Plan`
            WHERE farm = %(f)s AND workflow_state = 'Approved'
              AND period_from <= %(from)s AND period_to >= %(to)s
            ORDER BY period_from DESC
        """, {"f": farm, "from": from_date, "to": to_date}, as_dict=True)
        cap_names = [c.name for c in cap_all]
        # resolve_master_plan(), inlined: no def in the sandbox. Keep in step with
        # work_management/master_plan.py, which is unit-tested.
        cap_pick = None
        cap_err = None
        if mp_named:
            if mp_named in cap_names:
                cap_pick = mp_named
            else:
                cap_err = (mp_named + " does not cover this request's farm and dates. "
                           "Choose a master plan whose period contains them.")
        elif not cap_names:
            cap_err = ("No approved master plan covers " + str(from_date) + " to " +
                       str(to_date) + " for " + str(farm) +
                       ". A master plan must be approved before work can be planned.")
        elif len(cap_names) > 1:
            cap_err = ("More than one approved master plan covers these dates: " +
                       ", ".join(sorted(cap_names)) +
                       ". Say which one this work is planned against.")
        else:
            cap_pick = cap_names[0]
        cap_mp = [c for c in cap_all if c.name == cap_pick]
```

Everything downstream already reads `cap_mp[0]`, so it needs no change. At the document write, add `d.master_plan = cap_pick` beside `d.farm = farm`. Apply the same lookup in `tasks`, which currently has its own copy.

- [ ] **Step 4: Port, `check_ported.py`, full suite.**

- [ ] **Step 5: Commit both repos** — `Draw a request down against the plan it names`

---

### Task 5: The backfill

**Files:**
- Create: `work_management/patches/v1_0/link_planners_to_their_master_plan.py`
- Modify: `work_management/patches.txt`
- Test: `work_management/tests/test_link_planners_patch.py` (create)

**Interfaces:**
- Consumes: `resolve_master_plan` from Task 1.
- Produces: `execute()`; `CARRIERS = ("Work Management Planner",)`.

- [ ] **Step 1: Write the failing test** — the pure decision, not the SQL:

```python
from work_management.master_plan import resolve_master_plan

class TestTheBackfillDecision(unittest.TestCase):
	def test_one_containing_plan_is_the_answer(self):
		self.assertEqual(resolve_master_plan("", ["WMMP-1"]), ("WMMP-1", None))

	def test_no_containing_plan_is_left_alone(self):
		self.assertIsNone(resolve_master_plan("", [])[0])

	def test_two_containing_plans_are_left_alone_and_named(self):
		name, reason = resolve_master_plan("", ["WMMP-1", "WMMP-2"])
		self.assertIsNone(name)
		self.assertIn("WMMP-2", reason)

class TestItIsRegistered(unittest.TestCase):
	def test_after_post_model_sync(self):
		with open(os.path.join(HERE, "patches.txt")) as h:
			txt = h.read()
		self.assertIn("link_planners_to_their_master_plan", txt)
		self.assertGreater(txt.index("link_planners_to_their_master_plan"),
			txt.index("[post_model_sync]"))
```

- [ ] **Step 2: Run it, expect FAIL** on the registration test.

- [ ] **Step 3: Write the patch.**

```python
"""Record which master plan each existing request drew against.

`master_plan` arrives with this release, and 1,578 requests on live predate it.
Their budget was inferred from farm plus dates, which was reliable only because
two plans could not cover the same days -- so every one of them has exactly one
answer, and this is the last moment that is true.

A request with no containing plan is left null and counted: the fallback still
resolves it, and inventing a link would be worse than none. A request with two
is named rather than guessed, which cannot happen on data written under the old
rule but is reported in case it does.
"""

import frappe

from work_management.master_plan import resolve_master_plan


def execute():
	if not frappe.db.has_column("Work Management Planner", "master_plan"):
		return  # the field arrives with this release; a site mid-migrate may lack it

	rows = frappe.db.sql("""
		SELECT name, farm, from_date, to_date FROM `tabWork Management Planner`
		WHERE IFNULL(master_plan, '') = '' AND IFNULL(farm, '') != ''
		  AND from_date IS NOT NULL AND to_date IS NOT NULL
	""", as_dict=True)

	linked, unresolved, ambiguous = 0, 0, []
	for row in rows:
		candidates = frappe.db.sql_list("""
			SELECT name FROM `tabWork Management Master Plan`
			WHERE farm = %(f)s AND IFNULL(workflow_state,'') != 'Rejected'
			  AND period_from <= %(a)s AND period_to >= %(b)s
		""", {"f": row.farm, "a": row.from_date, "b": row.to_date})
		name, reason = resolve_master_plan("", candidates)
		if name:
			# set_value: these are submitted documents and will not accept a save
			frappe.db.set_value("Work Management Planner", row.name, "master_plan",
				name, update_modified=False)
			linked += 1
		elif len(candidates) > 1:
			ambiguous.append((row.name, sorted(candidates)))
		else:
			unresolved += 1

	frappe.db.commit()
	print(f"Work Management: linked {linked} request(s) to their master plan")
	if unresolved:
		print(f"Work Management: {unresolved} request(s) have no covering plan; "
			"left unlinked, and the date fallback still resolves them")
	for request, plans in ambiguous:
		print(f"Work Management: {request} is covered by {', '.join(plans)} -- "
			"left unlinked rather than guessed; set it by hand")
```

- [ ] **Step 4: Register it in `patches.txt` after `backfill_task_subjects`. Run the full suite.**

- [ ] **Step 5: Commit** — `Link every existing request to the plan it drew against`

---

### Task 6: The dashboard attributes by the stored link

**Files:**
- Modify: `<mirror>/server_scripts/wm_dashboard.py` — `mp_value` (~line 1328) and `plan_completion` (~line 3325)
- Test: `work_management/tests/test_master_plan_resolution.py`

**Interfaces:**
- Consumes: the `master_plan` column from Task 2, populated by Tasks 4 and 5.
- Produces: nothing new; both cards stop double-counting.

- [ ] **Step 1: Write the failing test**

```python
class TestTheDashboardDoesNotDoubleCount(unittest.TestCase):
	def setUp(self):
		with open(os.path.join(HERE, "api", "dashboard.py")) as h:
			self.src = h.read()

	def test_both_cards_prefer_the_stored_link(self):
		for marker in ('action == "mp_value"', 'action == "plan_completion"'):
			block = self.src[self.src.index(marker):][:6000]
			self.assertIn("master_plan", block, marker)
```

- [ ] **Step 2: Run it, expect FAIL.**

- [ ] **Step 3: Edit the mirror.** Both cards join planner rows by containment. Add the stored link as the preferred match, containment only where it is null — in `mp_value`'s requested/delivered subqueries and `plan_completion`'s `pc_req`, `pc_off`, `pc_act`, replacing

```sql
              AND pr.from_date >= %(pfrom)s AND pr.to_date <= %(pto)s
```

with

```sql
              AND (pr.master_plan = %(plan)s
                   OR (IFNULL(pr.master_plan,'') = ''
                       AND pr.from_date >= %(pfrom)s AND pr.to_date <= %(pto)s))
```

and adding `"plan": pc.name` (or `mp.name`) to each params dict.

- [ ] **Step 4: Port, `check_ported.py`, full suite.**

- [ ] **Step 5: Commit both repos** — `Count a request against one budget, not both`

---

### Task 7: Audit the three remaining scripts

**Files:**
- Read, and modify only where they attribute work to a plan: `<mirror>/server_scripts/wm_payment.py` (10 period references), `wm_payroll.py` (2), `wm_rates.py` (3)
- Test: `work_management/tests/test_master_plan_resolution.py`

**Interfaces:**
- Consumes: the `master_plan` column from Task 2.
- Produces: nothing new. This task's deliverable is a decision per reference, recorded in the commit message.

The spec lists these as "audited case by case", and most of their period
references will be plan *listing* or period *display*, which need no change. Only
a read that attributes work to a budget does. Guessing which is which without
reading them is how the double count survives in a corner nobody checked.

- [ ] **Step 1: Write the failing test** — a record of the audit, so it cannot be skipped silently:

```python
class TestTheRemainingScriptsWereAudited(unittest.TestCase):
	"""Each of these either attributes work to a plan or does not. The audit's
	conclusion is recorded here so a future reader knows it was done on purpose."""

	AUDITED = ("payment", "payroll", "rates")

	def test_each_audited_module_says_what_it_concluded(self):
		for mod in self.AUDITED:
			with open(os.path.join(HERE, "api", mod + ".py")) as h:
				src = h.read()
			self.assertIn("master plan attribution:", src.lower(), mod)
```

- [ ] **Step 2: Run it, expect FAIL** — none of the three carries the note.

- [ ] **Step 3: Read each period reference and act.** In each mirror script add one
comment at the point the question arises, in the form
`# Master plan attribution: <reads a plan's period for display only | now joins on pr.master_plan>`,
and where it does attribute work, apply the same predicate Task 6 uses:

```sql
              AND (pr.master_plan = %(plan)s
                   OR (IFNULL(pr.master_plan,'') = ''
                       AND pr.from_date >= %(pfrom)s AND pr.to_date <= %(pto)s))
```

- [ ] **Step 4: Port all three, `check_ported.py`, full suite.**

- [ ] **Step 5: Commit both repos** — `Audit the last three scripts for plan attribution`, naming in the body what each concluded.

---

### Task 8: The planner screen names the plan

**Files:**
- Modify: `work_management/public/js/work-planner.js` — `renderPeriodBar` and the save payload (`~line 1004`)
- Modify: `<mirror>/web_pages/work-planner.js` (copy of the above)
- Test: `work_management/tests/test_master_plan_resolution.py`

**Interfaces:**
- Consumes: `save` and `tasks` accepting `master_plan` (Task 4).
- Produces: `ST.masterPlan` holds the chosen plan name; every `tasks` and `save` call carries it.

- [ ] **Step 1: Write the failing test**

```python
class TestTheScreenSendsTheChoice(unittest.TestCase):
	def setUp(self):
		with open(os.path.join(HERE, "public", "js", "work-planner.js")) as h:
			self.src = h.read()

	def test_the_chip_records_which_plan_was_chosen(self):
		self.assertIn("ST.masterPlan", self.src)

	def test_the_save_payload_carries_it(self):
		block = self.src[self.src.index("action:\"save\""):][:400]
		self.assertIn("master_plan", block)

	def test_the_plans_purpose_is_shown_on_the_chip(self):
		"""Two plans over one period are otherwise two numbers."""
		self.assertIn("plan_name", self.src)
```

- [ ] **Step 2: Run it, expect FAIL.**

- [ ] **Step 3: Edit both copies.** In the chip click handler set `ST.masterPlan = x.getAttribute("data-bn")` alongside `boundDatesToPlan(...)`; render `data-bn` and the purpose in the chip markup; add `master_plan: ST.masterPlan || ""` to the `save` args and to `loadPlannableTasks`'s `tasks` call. When only one plan covers the dates, select it automatically so nothing changes for a farm with one budget.

- [ ] **Step 4: `node --check` both copies; full suite.**

- [ ] **Step 5: Commit both repos** — `Choose the budget on the screen, not by its dates`

---

### Task 9: Prove it on kaitet.local

- [ ] **Step 1: Full suite green; `check_ported.py` reports all 10 modules matching.**
- [ ] **Step 2: `bench --site kaitet.local migrate`** — expect the backfill to print what it linked. Note the bench's known first-run failure: `upande_irrigation` ships `Tank And Valve` with `custom=0` as a fixture, which needs developer mode; it succeeds on a retry and is not ours.
- [ ] **Step 3: Create two overlapping approved plans** on one farm for the same month, with different purposes.
- [ ] **Step 4: Raise a request against each** through `wm_planner`'s `save`, and confirm: naming neither is refused with both plan names in the message; naming one succeeds and stores it.
- [ ] **Step 5: Call `mp_value` and `plan_completion`** and confirm each request is counted against exactly one plan — the sum of the two plans' requested value equals the two requests, not four.
- [ ] **Step 6: Commit anything the run turned up, then push.**
