"""Guards on the farm backfill and on sections.

Both decisions are pure and tested without a site::

    ./env/bin/python -m unittest work_management.tests.test_sections -v
"""

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
