"""Narrowing the app to the farms a project actually works.

Farms are Upande Core's records, and Core's list serves every Upande app on the
site: kaitet.local carries sixteen across eight companies, including one named
`cheptiret` whose company is `dummy`. Work Management plans work against four of
them. Before farms moved to Core this app had its own `disabled` tickbox for
exactly that; Core's own `disabled` is no substitute, because ticking it there
would hide the farm from the spray plan and irrigation screens too.

So Settings carries the choice, and it bites in one place -- `config._farms()`,
which every screen reads its farm list through.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_farms_in_use -v
"""

import unittest

from work_management.api import config


class TestWhichFarmsTheAppOffers(unittest.TestCase):
	ALL = ["Saboti", "Lokitela", "Vale", "Endebess", "cheptiret", "SIMO"]

	def test_choosing_none_offers_every_farm(self):
		"""The default has to be "all", not "none".

		An empty picker is what every existing site has, and on those nothing may
		change: a setting nobody has touched must not empty the pickers on five
		screens.
		"""
		self.assertEqual(config.farms_in_use(self.ALL, []), self.ALL)

	def test_choosing_some_offers_only_those(self):
		self.assertEqual(
			config.farms_in_use(self.ALL, ["Saboti", "Vale"]), ["Saboti", "Vale"]
		)

	def test_the_order_is_upande_cores_not_the_order_they_were_picked(self):
		"""Farms read in a stable order wherever they are listed."""
		self.assertEqual(
			config.farms_in_use(self.ALL, ["Vale", "Saboti"]), ["Saboti", "Vale"]
		)

	def test_a_chosen_farm_upande_core_no_longer_has_is_dropped(self):
		"""A farm can be renamed or deleted in Core without telling this app.

		Leaving it in would put a name in every picker that resolves to nothing.
		"""
		self.assertEqual(config.farms_in_use(self.ALL, ["Saboti", "Kabarak"]), ["Saboti"])

	def test_choosing_only_farms_core_has_lost_falls_back_to_all(self):
		"""Every choice being stale is indistinguishable from having chosen none.

		Answering "no farms" there would take the whole app dark over a rename,
		with nothing on screen saying why. Offering all of them is the same state
		the site was in before anyone narrowed it.
		"""
		self.assertEqual(config.farms_in_use(self.ALL, ["Kabarak"]), self.ALL)

	def test_nothing_configured_and_no_farms_at_all_is_still_empty(self):
		self.assertEqual(config.farms_in_use([], []), [])
