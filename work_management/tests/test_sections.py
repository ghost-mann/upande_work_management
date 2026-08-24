"""Guards on the farm backfill and on sections.

Both decisions are pure and tested without a site::

    ./env/bin/python -m unittest work_management.tests.test_sections -v
"""

import glob
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
