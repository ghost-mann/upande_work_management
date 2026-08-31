"""One table of farms, and an explicit switch for whether it narrows.

Settings had two fields about farms, and a farm could need to appear in both:
`farms_in_use` decided which farms the screens offered, `farms` supplied each
farm's cost project. Nothing said so. Somebody setting a cost project got the
error "Lokitela has no cost project" solved and still saw sixteen farms, or
narrowed the farms and still had no project.

So: one table. A row is a farm you work, with its cost project and an area
override. And because "has a row" would otherwise silently mean "in use" -- add
Lokitela to give it a project and watch the other fifteen farms vanish from every
screen -- the narrowing is a checkbox you can see rather than a side effect of
having typed a row.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_one_farms_table -v
"""

import json
import os
import unittest

from work_management.api import config

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SETTINGS = os.path.join(HERE, "work_management", "doctype",
	"work_management_settings", "work_management_settings.json")


def settings_doc():
	with open(SETTINGS) as handle:
		return json.load(handle)


def field(fieldname):
	for f in settings_doc().get("fields", []):
		if f.get("fieldname") == fieldname:
			return f
	return None


class TestThereIsOneTable(unittest.TestCase):
	def test_the_separate_picker_is_gone(self):
		"""Two fields about farms is what made this confusing."""
		self.assertIsNone(field("farms_in_use"))

	def test_its_child_doctype_is_gone_too(self):
		from work_management import install

		self.assertNotIn("Work Management Farm In Use", install.shipped_doctypes())

	def test_the_one_table_carries_farm_project_and_area(self):
		self.assertEqual(field("farms")["fieldtype"], "Table")
		self.assertEqual(field("farms")["options"], "WM Farm")
		row = os.path.join(HERE, "work_management", "doctype", "wm_farm", "wm_farm.json")
		with open(row) as handle:
			names = {f["fieldname"] for f in json.load(handle)["fields"]}
		self.assertLessEqual({"farm", "project", "area_ha"}, names)

	def test_the_narrowing_is_its_own_visible_switch(self):
		f = field("farms_restrict")
		self.assertIsNotNone(f, "nothing says whether the table narrows")
		self.assertEqual(f["fieldtype"], "Check")
		self.assertIn(f.get("default"), (None, "0", 0),
			"default must be off, or adding a row to set a cost project would "
			"silently hide every farm not in the table")

	def test_the_switch_sits_above_the_table_it_governs(self):
		order = settings_doc()["field_order"]
		self.assertLess(order.index("farms_restrict"), order.index("farms"))


class TestWhatTheScreensOffer(unittest.TestCase):
	ALL = ["Saboti", "Lokitela", "Vale", "Endebess", "cheptiret", "SIMO"]

	def test_switch_off_offers_every_farm_however_many_rows_exist(self):
		"""The case that was broken: a row exists only to carry a cost project."""
		self.assertEqual(
			config.farms_in_use(self.ALL, ["Lokitela"], restrict=False), self.ALL
		)

	def test_switch_on_offers_only_the_rows(self):
		self.assertEqual(
			config.farms_in_use(self.ALL, ["Saboti", "Vale"], restrict=True),
			["Saboti", "Vale"],
		)

	def test_switch_on_with_no_rows_offers_every_farm(self):
		"""Ticking the box and listing nothing is not a request for no farms."""
		self.assertEqual(config.farms_in_use(self.ALL, [], restrict=True), self.ALL)

	def test_the_order_is_upande_cores_not_the_rows_order(self):
		self.assertEqual(
			config.farms_in_use(self.ALL, ["Vale", "Saboti"], restrict=True),
			["Saboti", "Vale"],
		)

	def test_a_row_naming_a_farm_core_lost_is_dropped(self):
		self.assertEqual(
			config.farms_in_use(self.ALL, ["Saboti", "Kabarak"], restrict=True), ["Saboti"]
		)

	def test_every_row_stale_falls_back_to_all_rather_than_none(self):
		"""Taking the app dark over a rename, with nothing on screen saying why,
		is worse than offering what it offered before anyone narrowed it."""
		self.assertEqual(config.farms_in_use(self.ALL, ["Kabarak"], restrict=True), self.ALL)


class TestTheMoveIsCarriedOut(unittest.TestCase):
	def test_a_patch_moves_any_existing_picker_rows_into_the_table(self):
		with open(os.path.join(HERE, "patches.txt")) as handle:
			txt = handle.read()
		self.assertIn("merge_farms_in_use_into_farms", txt)
		self.assertGreater(
			txt.index("merge_farms_in_use_into_farms"), txt.index("[post_model_sync]")
		)

	def test_it_turns_the_switch_on_when_the_picker_had_narrowed(self):
		"""Somebody who had narrowed their farms must stay narrowed."""
		path = os.path.join(HERE, "patches", "v1_0", "merge_farms_in_use_into_farms.py")
		with open(path) as handle:
			src = handle.read()
		self.assertIn("farms_restrict", src)

	def test_it_does_not_ask_a_single_doctype_for_a_column(self):
		"""Work Management Settings is a Single: it has no table, so has_column()
		on it raises TableMissingError instead of answering False. The migrate died
		on exactly that, and grepping the source could not have caught it -- only
		running it could."""
		path = os.path.join(HERE, "patches", "v1_0", "merge_farms_in_use_into_farms.py")
		with open(path) as handle:
			src = handle.read()
		self.assertNotIn('has_column("Work Management Settings"', src)
