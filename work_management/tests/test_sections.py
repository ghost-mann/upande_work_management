"""Guards on the farm backfill and on sections.

Both decisions are pure and tested without a site::

    ./env/bin/python -m unittest work_management.tests.test_sections -v
"""

import contextlib
import glob
import io
import json
import os
import unittest

from work_management.patches.v1_0 import backfill_farms_in_use as backfill


class TestFarmBackfillDecision(unittest.TestCase):
	def test_a_farm_in_settings_is_created_active(self):
		self.assertFalse(backfill.should_disable("Saboti", configured={"Saboti", "Vale"}))

	def test_a_farm_only_employees_use_is_created_disabled(self):
		"""Torongo and the rest are the wider group, not farms we plan against."""
		self.assertTrue(backfill.should_disable("Torongo", configured={"Saboti", "Vale"}))

	def test_nothing_is_disabled_when_settings_names_no_farms(self):
		"""A fresh site has no configured farms; disabling everything would hide all."""
		self.assertFalse(backfill.should_disable("Torongo", configured=set()))


def _shipped_farm_links():
	"""(doctype, fieldname) for every Link field the app's own JSON points at

	Work Management Farm. Custom Fields (Employee.custom_farm,
	Warehouse.custom_farm) live outside this JSON, so this is a subset of what
	SOURCES must cover, never the whole of it.
	"""
	here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	found = set()
	for path in glob.glob(os.path.join(here, "work_management", "doctype", "*", "*.json")):
		with open(path) as handle:
			doc = json.load(handle)
		if doc.get("doctype") != "DocType":
			continue
		for field in doc.get("fields", []):
			if field.get("fieldtype") == "Link" and field.get("options") == "Work Management Farm":
				found.add((doc["name"], field["fieldname"]))
	return found


class TestFarmSourcesStayComplete(unittest.TestCase):
	"""SOURCES must scan every Link field the app itself points at Work Management
	Farm, or a dangling link goes unnoticed the way this whole task started.

	This is one-directional: the app's shipped JSON is a subset of SOURCES, not
	equal to it, because the two Custom Fields (Employee, Warehouse) aren't in
	that JSON at all.
	"""

	# Doctypes deliberately left unscanned, with the reason -- an exclusion
	# should be a visible decision here, not a silent gap in SOURCES.
	DELIBERATELY_EXCLUDED = set()

	def test_every_shipped_farm_link_is_in_sources(self):
		known = set(backfill.SOURCES)
		missing = sorted(
			pair
			for pair in _shipped_farm_links()
			if pair[0] not in self.DELIBERATELY_EXCLUDED and pair not in known
		)
		self.assertEqual(missing, [], f"SOURCES is missing: {missing}")


from work_management import sections


class TestOneSectionPerBlock(unittest.TestCase):
	"""A block counted in two sections doubles its cost in the rollup."""

	def test_no_duplicates_in_a_clean_table(self):
		rows = [{"block": "A1"}, {"block": "A2"}, {"block": "A3"}]
		self.assertEqual(sections.duplicate_blocks(rows), [])

	def test_a_block_listed_twice_in_one_section_is_reported(self):
		rows = [{"block": "A1"}, {"block": "A2"}, {"block": "A1"}]
		self.assertEqual(sections.duplicate_blocks(rows), ["A1"])

	def test_blank_rows_are_ignored_rather_than_reported(self):
		rows = [{"block": ""}, {"block": None}, {"block": "A1"}]
		self.assertEqual(sections.duplicate_blocks(rows), [])

	def test_every_duplicate_is_reported_not_just_the_first(self):
		rows = [{"block": "A1"}, {"block": "A1"}, {"block": "A2"}, {"block": "A2"}]
		self.assertEqual(sections.duplicate_blocks(rows), ["A1", "A2"])


class TestUnassigned(unittest.TestCase):
	def test_the_unassigned_bucket_has_a_name(self):
		"""Blocks with no section are grouped, never dropped from a total."""
		self.assertTrue(sections.UNASSIGNED)


from work_management.patches.v1_0 import seed_sections_from_cost_centres as seed


class TestSectionSeedNaming(unittest.TestCase):
	def test_the_company_suffix_is_dropped_from_a_section_name(self):
		"""'SBT - Saboti - KL' reads better as 'SBT - Saboti'."""
		self.assertEqual(seed.section_name_for("SBT - Saboti - KL", "KL"), "SBT - Saboti")

	def test_a_name_without_the_suffix_is_unchanged(self):
		self.assertEqual(seed.section_name_for("BLOCK M", "KL"), "BLOCK M")

	def test_an_unknown_abbreviation_is_left_alone(self):
		self.assertEqual(seed.section_name_for("BLOCK M - KR", "KL"), "BLOCK M - KR")


class TestAmbiguousCostCentreName(unittest.TestCase):
	"""cost_center_name is not scoped to a company, so two companies can share
	one. Guessing which company a block belongs to would risk binding it to
	the wrong parent, farm and section -- so ambiguity refuses rather than
	guesses, same as no match at all."""

	def test_a_single_match_is_used(self):
		self.assertEqual(seed.unique_cost_centre(["SBT - Saboti - KL"]), "SBT - Saboti - KL")

	def test_two_companies_sharing_a_name_is_refused(self):
		self.assertIsNone(seed.unique_cost_centre(["SBT - Saboti - KL", "SBT - Saboti - VL"]))

	def test_no_match_is_none(self):
		self.assertIsNone(seed.unique_cost_centre([]))


class TestSectionFarmMismatch(unittest.TestCase):
	"""Reusing a section by name must not silently move a block onto a
	different farm than the one that section already carries."""

	def test_a_matching_farm_is_not_a_conflict(self):
		self.assertFalse(seed.farm_mismatch("Saboti", "Saboti"))

	def test_a_different_farm_is_a_conflict(self):
		self.assertTrue(seed.farm_mismatch("Saboti", "Vale"))


class TestPlannerBlocksQueryIsOrdered(unittest.TestCase):
	"""`select distinct` with no ordering leaves iteration order up to the
	database -- both the ambiguity refusal and the farm-mismatch refusal
	become nondeterministic run to run without one."""

	def test_the_query_orders_its_results(self):
		self.assertIn("order by", seed.PLANNER_BLOCKS_SQL.lower())


class TestSectionSeedSummary(unittest.TestCase):
	"""Someone reading migrate output should be able to tell 'no grouping
	existed for this' apart from 'the grouping was ambiguous and I refused to
	guess' -- the two skip reasons must be named separately, not folded into
	one number."""

	def test_both_skip_reasons_are_named_separately(self):
		message = seed.summary_message(created=2, placed=5, ambiguous=3, farm_conflict=1)
		self.assertIn("3 skipped for an ambiguous cost-centre name", message)
		self.assertIn("1 skipped for a farm mismatch", message)


class TestRollUp(unittest.TestCase):
	"""Rolls the per-block cost-centre rows up to per-section totals, the same
	shape as the existing farm-level rollup in the cost-centre view: sum the
	money/quantity fields, count blocks, derive cost_per_unit guarded on qty.

	Real per-block rows (dashboard.py) carry labour_spend, gl_spend, qty and
	worker_days -- there is no 'spend' field, so the fixtures below use the
	real names rather than the shorter ones an earlier draft of this test used.
	"""

	BLOCKS = [
		{"block": "A1", "labour_spend": 100.0, "gl_spend": 90.0, "qty": 10.0, "worker_days": 8.0},
		{"block": "A2", "labour_spend": 50.0, "gl_spend": 40.0, "qty": 5.0, "worker_days": 4.0},
		{"block": "Z9", "labour_spend": 25.0, "gl_spend": 0.0, "qty": 2.0, "worker_days": 2.0},
	]
	MAPPING = {"A1": "BLOCK A", "A2": "BLOCK A"}

	def test_blocks_in_a_section_are_totalled_under_it(self):
		rows = {r["key"]: r for r in sections.roll_up(self.BLOCKS, self.MAPPING)}
		self.assertEqual(rows["BLOCK A"]["labour_spend"], 150.0)
		self.assertEqual(rows["BLOCK A"]["gl_spend"], 130.0)
		self.assertEqual(rows["BLOCK A"]["blocks"], 2)

	def test_qty_and_worker_days_are_also_totalled(self):
		rows = {r["key"]: r for r in sections.roll_up(self.BLOCKS, self.MAPPING)}
		self.assertEqual(rows["BLOCK A"]["qty"], 15.0)
		self.assertEqual(rows["BLOCK A"]["worker_days"], 12.0)

	def test_a_block_with_no_section_is_kept_under_unassigned(self):
		rows = {r["key"]: r for r in sections.roll_up(self.BLOCKS, self.MAPPING)}
		self.assertIn(sections.UNASSIGNED, rows)
		self.assertEqual(rows[sections.UNASSIGNED]["labour_spend"], 25.0)

	def test_the_section_total_equals_the_block_total(self):
		"""The whole point: switching the toggle must not change the money."""
		rolled = sections.roll_up(self.BLOCKS, self.MAPPING)
		self.assertEqual(
			sum(r["labour_spend"] for r in rolled),
			sum(b["labour_spend"] for b in self.BLOCKS),
		)

	def test_rows_come_back_biggest_first(self):
		rolled = sections.roll_up(self.BLOCKS, self.MAPPING)
		self.assertEqual([r["key"] for r in rolled], ["BLOCK A", sections.UNASSIGNED])

	def test_cost_per_unit_is_derived_like_the_farm_rollup(self):
		"""Same guard as farm_totals: labour / qty, or None rather than a
		division by zero, when qty is not positive."""
		rows = {r["key"]: r for r in sections.roll_up(self.BLOCKS, self.MAPPING)}
		self.assertAlmostEqual(rows["BLOCK A"]["cost_per_unit"], 150.0 / 15.0)
		zero_qty = [{"block": "A1", "labour_spend": 10.0, "gl_spend": 0.0, "qty": 0.0, "worker_days": 0.0}]
		rows = {r["key"]: r for r in sections.roll_up(zero_qty, self.MAPPING)}
		self.assertIsNone(rows["BLOCK A"]["cost_per_unit"])

	def test_an_empty_input_gives_an_empty_result(self):
		self.assertEqual(sections.roll_up([], {}), [])

	def test_a_none_amount_is_treated_as_zero_not_an_error(self):
		"""The real per-block row can carry gl_spend=None (e.g. no GL match) --
		summing must not raise, and must not corrupt the other blocks' total."""
		rows = [
			{"block": "A1", "labour_spend": 100.0, "gl_spend": None, "qty": 10.0, "worker_days": 8.0},
			{"block": "A2", "labour_spend": 50.0, "gl_spend": 40.0, "qty": 5.0, "worker_days": 4.0},
		]
		rolled = {r["key"]: r for r in sections.roll_up(rows, self.MAPPING)}
		self.assertEqual(rolled["BLOCK A"]["gl_spend"], 40.0)

	def test_a_row_with_no_block_at_all_is_kept_under_unassigned(self):
		"""mapping.get(row.get("block")) must not raise when 'block' is
		missing entirely, and a row with nothing to look up is unassigned
		the same as a row naming a block no section claims."""
		rows = [{"labour_spend": 5.0, "gl_spend": 0.0, "qty": 1.0, "worker_days": 1.0}]
		rolled = {r["key"]: r for r in sections.roll_up(rows, self.MAPPING)}
		self.assertIn(sections.UNASSIGNED, rolled)
		self.assertEqual(rolled[sections.UNASSIGNED]["labour_spend"], 5.0)


import inspect

from work_management.api import dashboard as cost_center_dashboard


class TestCostCentreTotalsBlockCountSurvivesTheToggle(unittest.TestCase):
	"""Regression guard for a real bug: the cost_center action's group_by
	branch reassigns `rows` to the (shorter) list of section buckets, and
	out["totals"]["blocks"] must not be computed from that reassigned `rows`
	-- it must stay a genuine block count in both toggle positions, not the
	number of section buckets (Unassigned included).

	The action itself can't be exercised as a pure function: it reads
	frappe.form_dict, runs frappe.db.sql for the labour/weekly-trend queries,
	and calls frappe.get_meta -- all of which need a live site, so a real
	before/after assertion on out["totals"] is not reachable without a
	disproportionate restructure of a large pre-existing file. What follows
	is a source-level check instead (the same technique test_page_bootstrap.py
	already uses on the dashboard JS): it holds the exact ordering invariant
	whose violation caused the bug -- the true count is captured before the
	group_by branch can reassign `rows`, and out["totals"] reads that capture
	rather than re-deriving it from whatever `rows` happens to hold by then.
	"""

	def setUp(self):
		self.src = inspect.getsource(cost_center_dashboard.wm_dashboard)

	def test_the_block_count_is_captured_before_the_group_by_branch(self):
		capture_at = self.src.find("block_count = len(rows)")
		branch_at = self.src.find('== "section":')
		self.assertNotEqual(capture_at, -1, "no captured block count found")
		self.assertNotEqual(branch_at, -1, "no group_by section branch found")
		self.assertLess(
			capture_at, branch_at,
			"block_count must be captured before the group_by branch can "
			"reassign `rows`, or it silently becomes a section count",
		)

	def test_totals_blocks_uses_the_capture_not_a_fresh_len_of_rows(self):
		self.assertIn('"blocks": block_count', self.src)
		self.assertNotIn('"totals"] = {"labour": tot_labour, "gl": tot_gl, "blocks": len(rows)', self.src)


class TestOneBadRecordDoesNotAbortTheMigrate(unittest.TestCase):
	"""Both patches walk records the app has never seen. A legacy value that
	will not validate is a fact of life; aborting `bench migrate` for the whole
	site over one of them is not, and it contradicts the very principle
	`without_aborting_the_migrate` was added to establish.
	"""

	@staticmethod
	@contextlib.contextmanager
	def quiet():
		"""The skip notes are printed and logged on purpose; swallow them so a
		passing run stays quiet and a real failure still stands out."""
		noise = io.StringIO()
		with contextlib.redirect_stdout(noise), contextlib.redirect_stderr(noise):
			yield

	def test_every_missing_farm_is_created_with_the_right_disabled_flag(self):
		made = []
		created, notes = backfill.create_missing(
			["Saboti", "Torongo"], {"Saboti"}, lambda farm, disabled: made.append((farm, disabled))
		)
		self.assertEqual(made, [("Saboti", False), ("Torongo", True)])
		self.assertEqual(created, 2)
		self.assertEqual(notes, [])

	def test_a_farm_that_will_not_insert_does_not_stop_the_farms_after_it(self):
		made = []

		def create(farm, disabled):
			if farm == "Kiptagich":
				raise ValueError("Value missing for Work Management Farm: Farm")
			made.append(farm)

		with self.quiet():
			created, notes = backfill.create_missing(
				["Isinya", "Kiptagich", "Torongo"], set(), create
			)
		self.assertEqual(made, ["Isinya", "Torongo"])
		self.assertEqual(created, 2)
		self.assertEqual(len(notes), 1)
		self.assertIn("Kiptagich", notes[0])

	def test_each_block_outcome_is_counted(self):
		outcomes = {
			"A1": seed.CREATED, "A2": seed.PLACED, "A3": seed.AMBIGUOUS,
			"A4": seed.FARM_CONFLICT, "A5": None,
		}
		counts, notes = seed.tally(sorted(outcomes), outcomes.get)
		self.assertEqual(counts["created"], 1)
		self.assertEqual(counts["placed"], 2, "a created section also holds its block")
		self.assertEqual(counts["ambiguous"], 1)
		self.assertEqual(counts["farm_conflict"], 1)
		self.assertEqual(notes, [])

	def test_a_block_that_cannot_be_placed_does_not_stop_the_blocks_after_it(self):
		def place(block):
			if block == "VALE-B7":
				raise ValueError("Warehouse VALE-B7 not found")
			return seed.PLACED

		with self.quiet():
			counts, notes = seed.tally(["A1", "VALE-B7", "B2"], place)
		self.assertEqual(counts["placed"], 2)
		self.assertEqual(len(notes), 1)
		self.assertIn("VALE-B7", notes[0])
