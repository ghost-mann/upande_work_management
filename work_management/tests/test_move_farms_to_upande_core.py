"""The patch that hands the farms over to Upande Core.

Pure functions only -- what to carry, and what to clear -- so the decisions can
be read and tested without a site::

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_move_farms_to_upande_core -v

The site-touching half of execute() is deliberately thin: it walks these answers
and writes them with frappe.db.set_value, which runs no document validation. It
has to be that way, because every Farm row on the live site is missing
`farm_type` -- a reqd field -- so anything that saved a Farm document would be
rejected by Core's own validation.
"""

import unittest

from work_management.patches.v1_0 import move_farms_to_upande_core as patch


class TestWhatToCarryAcrossToSettings(unittest.TestCase):
	def test_a_farm_with_a_cost_project_is_carried(self):
		rows = patch.rows_to_carry([{"name": "Saboti", "project": "PROJ-0031", "area_ha": 0}])
		self.assertEqual(rows, [{"farm": "Saboti", "project": "PROJ-0031", "area_ha": 0.0}])

	def test_a_farm_with_an_area_is_carried_even_with_no_project(self):
		rows = patch.rows_to_carry([{"name": "Vale", "project": None, "area_ha": 12.5}])
		self.assertEqual(rows, [{"farm": "Vale", "project": None, "area_ha": 12.5}])

	def test_a_farm_with_neither_is_not_carried(self):
		"""Most farms are exactly this, and a row saying nothing is noise.

		On kaitet.local every one of the fourteen is: no project, area 0.0. A row
		per farm carrying two empty columns would make the Settings table look
		configured when nothing has been.
		"""
		self.assertEqual(patch.rows_to_carry([{"name": "Karen", "project": None, "area_ha": 0}]), [])

	def test_an_existing_settings_row_is_not_duplicated(self):
		rows = patch.rows_to_carry(
			[{"name": "Saboti", "project": "PROJ-0031", "area_ha": 0}],
			already={"Saboti"},
		)
		self.assertEqual(rows, [])

	def test_the_order_is_the_order_the_farms_came_in(self):
		rows = patch.rows_to_carry([
			{"name": "Vale", "project": "PROJ-0031", "area_ha": 0},
			{"name": "Endebess", "project": "PROJ-0032", "area_ha": 0},
		])
		self.assertEqual([row["farm"] for row in rows], ["Vale", "Endebess"])


class TestWhichReferencesToClear(unittest.TestCase):
	def test_a_name_upande_core_has_is_left_alone(self):
		self.assertEqual(patch.orphans({"Saboti", "Vale"}, {"Saboti", "Vale"}), [])

	def test_a_name_upande_core_has_not_got_is_cleared(self):
		"""Kabarak, on kaitet.local: two Warehouses and nothing else.

		No Employee, no Planner, no Actuals, no Assigner, no Payment, no Master
		Plan, no Section. Clearing it costs two links that already pointed at a
		farm the rest of the system had never heard of.
		"""
		self.assertEqual(patch.orphans({"Saboti", "Kabarak"}, {"Saboti"}), ["Kabarak"])

	def test_the_answer_is_sorted_so_the_log_reads_the_same_every_run(self):
		self.assertEqual(
			patch.orphans({"Zulu", "Alpha"}, set()), ["Alpha", "Zulu"]
		)

	def test_nothing_in_use_clears_nothing(self):
		self.assertEqual(patch.orphans(set(), {"Saboti"}), [])
