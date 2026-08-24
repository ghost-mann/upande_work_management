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
