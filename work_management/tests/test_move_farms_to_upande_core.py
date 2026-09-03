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


class TestWhichColumnsToRead(unittest.TestCase):
	"""The columns asked for come from the table, not from the deleted JSON.

	`area_ha` was added to the doctype JSON one commit before that JSON was
	deleted. A site whose last migrate of this app predates that commit has a
	table without the column, and once the JSON is gone schema sync can never
	add it -- there is nothing left for sync to read. This patch asked for it
	unconditionally and every such site died on

	    MySQLdb.OperationalError: (1054, "Unknown column 'area_ha' in 'SELECT'")

	kentrout.local was one: its tabDocField rows for the retired doctype list
	farm_name, business_unit, project, column_break_main, disabled, description
	and no area_ha at all.
	"""

	def test_the_column_the_site_is_missing_is_not_asked_for(self):
		have = ["name", "creation", "farm_name", "business_unit", "project", "disabled"]
		self.assertEqual(patch.fields_to_read(have), ["name", "project"])

	def test_a_site_that_has_both_is_asked_for_both(self):
		have = ["name", "creation", "farm_name", "project", "area_ha"]
		self.assertEqual(patch.fields_to_read(have), ["name", "project", "area_ha"])

	def test_a_table_with_neither_still_yields_the_names(self):
		"""The names are the point: execute() prints them as it retires them."""
		self.assertEqual(patch.fields_to_read(["name", "creation", "farm_name"]), ["name"])

	def test_name_comes_first_so_the_row_is_always_identifiable(self):
		for have in (["name"], ["name", "area_ha"], ["name", "project", "area_ha"]):
			self.assertEqual(patch.fields_to_read(have)[0], "name")

	def test_a_missing_column_carries_nothing_rather_than_a_wrong_value(self):
		"""fields_to_read and rows_to_carry have to agree, so test them together.

		A farm read without `area_ha` has no area key, and rows_to_carry reads it
		with .get() -- so the farm is judged on its project alone. Saboti has one
		and is carried with area 0.0; Kabarak has neither and is skipped, exactly
		as it would be on a site that did have the column and held 0 in it.
		"""
		read = patch.fields_to_read(["name", "project"])
		self.assertNotIn("area_ha", read)
		farms = [
			{key: value for key, value in farm.items() if key in read}
			for farm in (
				{"name": "Saboti", "project": "PROJ-0031", "area_ha": 40.0},
				{"name": "Kabarak", "project": None, "area_ha": 12.5},
			)
		]
		self.assertEqual(
			patch.rows_to_carry(farms),
			[{"farm": "Saboti", "project": "PROJ-0031", "area_ha": 0.0}],
		)
