"""Field intelligence finds a farm's area whichever column the site keeps it in.

The area block was written against two site shapes that no longer describe the
only site that matters. It asked for `Work Management Farm` (retired) and for
`WM Farm` on Settings (the legacy Settings table), and on the live site neither
doctype exists -- so `farm_area` came back empty on every request and the four
areas somebody was asked to enter had nowhere to go. Live's `Farm` is Upande
Kaitet's, and it carries no area column at all until one is added.

So the block asks the table which column holds hectares instead of assuming:

    Upande Core's Farm      area
    the retired WM Farm     area_ha
    added by hand           custom_area_ha

`frappe.db.has_column` is not in the Server Script sandbox's globals, so this
goes through `frappe.get_meta`, which is -- and which knows custom fields too,
the whole point on a site where the column arrived as one.

One implementation for both worlds. The port used to rewrite this block, because
the mirror read one doctype and the app another; now they read the same thing and
the rewrite rule is gone. `test_ported` (check_ported.py) keeps them identical.

The block is lifted out of the shipped module and executed here, so what is
tested is the code that runs rather than a description of it.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_farm_area_column -v
"""

import inspect
import textwrap
import unittest

from work_management.api import dashboard

START = "farm_area = {}"
END = "# Nobody has entered an area yet"


class FakeMeta:
	"""Just enough of a Meta to answer "have you got this column?"."""

	def __init__(self, columns):
		self.columns = set(columns)

	def get_field(self, fieldname):
		return {"fieldname": fieldname} if fieldname in self.columns else None


class FakeUtils:
	@staticmethod
	def flt(value):
		try:
			return float(value or 0)
		except (TypeError, ValueError):
			return 0.0


class FakeDB:
	def __init__(self, doctypes):
		self.doctypes = set(doctypes)

	def exists(self, doctype, name):
		return name in self.doctypes if doctype == "DocType" else False


class FakeFrappe:
	"""A site shape: which columns Farm has, and which rows each read returns."""

	def __init__(self, farm_columns, farm_rows, doctypes=(), settings_rows=()):
		self.farm_columns = list(farm_columns)
		self.farm_rows = list(farm_rows)
		self.settings_rows = list(settings_rows)
		self.db = FakeDB(doctypes)
		self.utils = FakeUtils()
		self.asked_for = []

	def get_meta(self, doctype):
		if doctype != "Farm":
			raise AssertionError("only Farm's meta should be consulted here")
		return FakeMeta(self.farm_columns)

	def get_all(self, doctype, fields=None, filters=None, **kwargs):
		self.asked_for.append((doctype, tuple(fields or ())))
		if doctype == "Farm":
			# honour the alias the block asks for, as frappe does
			out = []
			for row in self.farm_rows:
				picked = {"name": row["name"]}
				for field in fields or []:
					if " as " in field:
						src, alias = [p.strip() for p in field.split(" as ")]
						picked[alias] = row.get(src)
					elif field != "name":
						picked[field] = row.get(field)
				out.append(picked)
			return out
		return list(self.settings_rows)


def run_block(fake):
	"""Execute the shipped area block against one site shape, return farm_area."""
	lines = inspect.getsource(dashboard.wm_dashboard).splitlines(True)
	first = next(i for i, l in enumerate(lines) if START in l)
	last = next(i for i, l in enumerate(lines) if END in l)
	block = textwrap.dedent("".join(lines[first:last]))
	namespace = {"frappe": fake}
	exec(compile(block, "<farm-area>", "exec"), namespace)
	return namespace["farm_area"]


class TestTheAreaIsFoundWhereverTheSiteKeepsIt(unittest.TestCase):
	def test_upande_core_calls_it_area(self):
		fake = FakeFrappe(["farm", "area"], [
			{"name": "Lokitela", "area": 217.0},
			{"name": "Endebess", "area": 295.0},
			{"name": "Saboti", "area": 70.0},
			{"name": "Vale", "area": 250.0},
		])
		self.assertEqual(run_block(fake),
			{"Lokitela": 217.0, "Endebess": 295.0, "Saboti": 70.0, "Vale": 250.0})

	def test_the_retired_doctype_called_it_area_ha(self):
		fake = FakeFrappe(["farm", "area_ha"], [{"name": "Saboti", "area_ha": 70.0}])
		self.assertEqual(run_block(fake), {"Saboti": 70.0})

	def test_a_column_added_by_hand_is_found_too(self):
		fake = FakeFrappe(["farm", "custom_area_ha"],
			[{"name": "Vale", "custom_area_ha": 250.0}])
		self.assertEqual(run_block(fake), {"Vale": 250.0})

	def test_core_wins_when_a_site_carries_more_than_one(self):
		"""A site that added custom_area_ha and later got Core's field should
		divide by Core's, which is the farm's own figure."""
		fake = FakeFrappe(["area", "custom_area_ha"],
			[{"name": "Saboti", "area": 70.0, "custom_area_ha": 999.0}])
		self.assertEqual(run_block(fake), {"Saboti": 70.0})


class TestASiteWithNoAreaColumnStillAnswers(unittest.TestCase):
	def test_no_column_means_no_areas_and_no_crash(self):
		"""Live, before the column is added: Farm has farm/company/abbreviation
		and nothing else. The old block returned {} here too -- but by asking
		two absent doctypes, so adding the column changed nothing. Now it does."""
		fake = FakeFrappe(["farm", "company", "abbreviation"], [{"name": "Saboti"}])
		self.assertEqual(run_block(fake), {})

	def test_farm_is_not_queried_when_it_has_no_area_column(self):
		"""Naming a column the site has not got does not narrow a query, it kills
		it -- the same (1054, "Unknown column") that took the assigner down."""
		fake = FakeFrappe(["farm", "company"], [{"name": "Saboti"}])
		run_block(fake)
		self.assertEqual([d for d, _ in fake.asked_for if d == "Farm"], [])

	def test_a_blank_area_is_not_taken_as_zero_hectares(self):
		"""A farm nobody has measured must fall through to the block fallback,
		not divide the whole screen by zero."""
		fake = FakeFrappe(["area"], [
			{"name": "Saboti", "area": 70.0},
			{"name": "Kabarak", "area": 0.0},
			{"name": "Kisumu", "area": None},
		])
		self.assertEqual(run_block(fake), {"Saboti": 70.0})


class TestSettingsStillOverridesTheFarm(unittest.TestCase):
	def test_the_settings_table_fills_a_farm_the_farm_does_not_answer(self):
		fake = FakeFrappe(["area"], [{"name": "Saboti", "area": 70.0}],
			doctypes=["WM Farm"],
			settings_rows=[{"farm": "Vale", "area_ha": 250.0}])
		self.assertEqual(run_block(fake), {"Saboti": 70.0, "Vale": 250.0})

	def test_the_farms_own_figure_wins_over_settings(self):
		"""Core's field is the default because a farm's area is a property of the
		farm, not of this app's configuration."""
		fake = FakeFrappe(["area"], [{"name": "Saboti", "area": 70.0}],
			doctypes=["WM Farm"],
			settings_rows=[{"farm": "Saboti", "area_ha": 999.0}])
		self.assertEqual(run_block(fake), {"Saboti": 70.0})

	def test_a_site_without_the_settings_table_is_not_asked_for_it(self):
		fake = FakeFrappe(["area"], [{"name": "Saboti", "area": 70.0}])
		run_block(fake)
		self.assertEqual([d for d, _ in fake.asked_for if d == "WM Farm"], [])


class TestTheSandboxCanRunThisBlock(unittest.TestCase):
	def test_it_does_not_reach_for_has_column(self):
		"""frappe.db.has_column is not in the Server Script sandbox's globals, so
		the mirror cannot use it and neither can this block."""
		lines = inspect.getsource(dashboard.wm_dashboard).splitlines(True)
		first = next(i for i, l in enumerate(lines) if START in l)
		last = next(i for i, l in enumerate(lines) if END in l)
		self.assertNotIn("has_column", "".join(lines[first:last]))


if __name__ == "__main__":
	unittest.main()
