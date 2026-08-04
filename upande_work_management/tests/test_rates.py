# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Classification tests for effective-dated rates.

These need no site and no database — ``classify`` is pure arithmetic — so they
run with the bench python directly:

    ./env/bin/python -m unittest upande_work_management.tests.test_rates -v

Every case below is a real row from the Kaitet live Task master as at
2026-08-04, not an invented number.
"""

import unittest

from upande_work_management.rates import KNOWN_DAILY_WAGES, LEGACY_DAILY_WAGE, classify


class TestClassify(unittest.TestCase):
	def assert_verdict(self, rate, target, expected, expected_wage=None, msg=None):
		verdict, implied, wage = classify(rate, target)
		self.assertEqual(
			verdict,
			expected,
			msg or "{0} x {1} = {2}/day -> {3}, expected {4}".format(
				rate, target, implied, verdict, expected
			),
		)
		if expected_wage is not None:
			self.assertEqual(wage, expected_wage, "matched the wrong wage tier")

	# ---------------------------------------------------------- clean matches

	def test_exact_derivations_are_derived(self):
		"""Rates that divide the wage cleanly."""
		self.assert_verdict(13.6, 25, "derived")  # Planting avocado(Lokitela)
		self.assert_verdict(1.7, 200, "derived")  # Mulching -Avocado
		self.assert_verdict(340.0, 1, "derived")  # Garderner, Cleaners
		self.assert_verdict(68.0, 5, "derived")  # Turn boy
		self.assert_verdict(6.8, 50, "derived")  # Soil mixing-Forest soil

	def test_rounding_drift_still_counts_as_derived(self):
		"""2dp storage moves the implied wage a little either way.

		These are the values that made pay_recalc_wages necessary in the first
		place: a full day paying 337.50 or 340.50 instead of 340.
		"""
		self.assert_verdict(0.27, 1250, "derived")  # Boom sprayer -> 337.50
		self.assert_verdict(48.57, 7, "derived")  # Kanpsack Herbicide -> 339.99
		self.assert_verdict(113.33, 3, "derived")  # Scouting(Lokitela) -> 339.99
		self.assert_verdict(22.67, 15, "derived")  # Young tree granualar -> 340.05
		self.assert_verdict(2.27, 150, "derived")  # Boundary-Weeding Kei Apple -> 340.50

	# -------------------------------------------------------------- the bug

	def test_planting_grass_is_not_silently_excluded(self):
		"""The regression that motivated widening the band.

		Planting grass holds 4.6 where the true rate is 340/75 = 4.5333 —
		someone rounded up, putting the implied wage at 345. The old 1% band
		(pay_recalc_wages, BAND = 3.4) threw it out, silently skipping 57 rows
		and KES 19,665 of work that really is wage-derived. It must reach a
		human instead of being dropped.
		"""
		verdict, implied, _wage = classify(4.6, 75)
		self.assertEqual(verdict, "borderline")
		self.assertAlmostEqual(implied, 345.0, places=6)
		self.assertNotEqual(verdict, "not_derived", "Planting grass must not be silently excluded")

	# ------------------------------------------------------- premium & broken

	def test_premium_rates_are_not_wage_derived(self):
		"""Held at their own values by decision — they must not be rescaled."""
		self.assert_verdict(62.5, 8, "not_derived")  # Team leader-Avocado, Store Clerk-Vale -> 500
		self.assert_verdict(40.08, 12, "not_derived")  # Secuity-Supervisor(Avocado) -> 480.96

	def test_malformed_task_master_rows_are_excluded(self):
		"""custom_rate filled in as the DAILY WAGE rather than a per-unit rate.

		A blanket ``387 / daily_target`` would wreck every one of these, so the
		classifier has to reject them by rule.
		"""
		self.assert_verdict(6000.0, 600, "not_derived")  # Wood cutting -> 3,600,000/day
		self.assert_verdict(340.0, 4000, "not_derived")  # Planting coffee seedlings -> 1,360,000
		self.assert_verdict(250.0, 6000, "not_derived")  # Sticking of Grafted plants -> 1,500,000
		self.assert_verdict(340.0, 8, "not_derived")  # Avocado Pruning(Lokitela) -> 2,720/day

	def test_missing_inputs_are_unknown_not_derived(self):
		self.assert_verdict(0, 25, "unknown")
		self.assert_verdict(13.6, 0, "unknown")
		self.assert_verdict(None, None, "unknown")

	# ------------------------------------------------------------ 350 tier

	def test_350_is_a_wage_tier_not_drift(self):
		"""14 live tasks imply exactly 350.00/day.

		Packhouse, greenhouse, QC and reliever work sit on a 350 tier rather
		than 340. Confirmed as a real tier, so they are wage-derived and rise to
		387 with everyone else — not held back as unclassifiable.
		"""
		# GREEN HOUSE OPERATIONS, QC SUPPORT, Trailer Offloading (350 x 1 Day)
		self.assert_verdict(350.0, 1, "derived", expected_wage=350.0)
		self.assert_verdict(3.5, 100, "derived", expected_wage=350.0)  # piece-rate equivalent
		self.assert_verdict(43.75, 8, "derived", expected_wage=350.0)  # 8-hour equivalent

	def test_tiers_do_not_poach_each_others_tasks(self):
		"""A 340-derived rate must not be matched to the 350 tier."""
		self.assert_verdict(340.0, 1, "derived", expected_wage=340.0)
		self.assert_verdict(1.7, 200, "derived", expected_wage=340.0)
		self.assert_verdict(2.27, 150, "derived", expected_wage=340.0)

	def test_still_borderline_after_adding_the_350_tier(self):
		"""These four live values sit between tiers and still need a decision."""
		self.assert_verdict(4.6, 75, "borderline")  # Planting grass -> 345.00
		self.assert_verdict(3.5, 103, "borderline")  # Loading crates to a container -> 360.50
		self.assert_verdict(0.09, 4000, "borderline")  # White paints application-Nusery -> 360.00
		self.assert_verdict(0.08, 4000, "borderline")  # White Paints ...(Lokitela) -> 320.00

	# ------------------------------------------------------------- boundaries

	def test_band_edges(self):
		"""Bands are inclusive, and two tiers mean two overlapping windows.

		Derived: 340 +/-1% = [336.6, 343.4] and 350 +/-1% = [346.5, 353.5].
		Borderline reaches 340 -10% = 306 at the bottom and 350 +10% = 385 at
		the top; outside that union nothing is wage-derived.
		"""
		self.assertEqual(KNOWN_DAILY_WAGES, (340.0, 350.0))
		# inside each tier's exact band
		self.assert_verdict(343.4, 1, "derived", expected_wage=340.0)
		self.assert_verdict(336.6, 1, "derived", expected_wage=340.0)
		self.assert_verdict(346.5, 1, "derived", expected_wage=350.0)
		self.assert_verdict(353.5, 1, "derived", expected_wage=350.0)
		# between the two tiers -> nobody claims it outright
		self.assert_verdict(345.0, 1, "borderline")
		# outer edges of the review window, inclusive
		self.assert_verdict(306.0, 1, "borderline", expected_wage=340.0)
		self.assert_verdict(385.0, 1, "borderline", expected_wage=350.0)
		# just beyond
		self.assert_verdict(305.0, 1, "not_derived")
		self.assert_verdict(386.0, 1, "not_derived")


class TestWageUplift(unittest.TestCase):
	"""The uplift itself: new rate = new wage / existing daily target."""

	def test_uplift_is_exactly_the_wage_ratio(self):
		new_wage, old_wage = 387.0, 340.0
		for rate, target in ((13.6, 25), (1.7, 200), (28.33, 12), (0.85, 400)):
			new_rate = new_wage / target
			old_exact = old_wage / target
			self.assertAlmostEqual(new_rate / old_exact, new_wage / old_wage, places=9)

	def test_uplift_keeps_a_full_day_whole(self):
		"""A worker hitting target must earn exactly the daily wage.

		Deriving from the wage at 6dp is what makes this true; a 2dp rate
		would land on 386.50 or 387.60.
		"""
		for target in (25, 200, 1250, 7, 3, 75, 1):
			rate = 387.0 / target
			self.assertAlmostEqual(rate * target, 387.0, places=9)


if __name__ == "__main__":
	unittest.main()
