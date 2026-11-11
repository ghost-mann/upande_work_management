"""Master plans per greenhouse: which plan funds a request, and what it is called.

Altura raises one master plan per greenhouse and wants them named after it
(GH-3-MP-26-001). Two consequences, both tested here without a site:

1. WHICH PLAN. With one plan per greenhouse a farm routinely holds several
   approved plans over the same days, so the dates alone stop identifying a
   budget. The rule (master_plan.py:pick_master_plan) -- the link the request
   carries wins if that plan may fund its blocks; a greenhouse plan beats a
   farm-level one; two at the same level is refused; blocks spanning
   greenhouses with no farm-level plan is refused naming the greenhouses. The
   drawdown SQL applies the same precedence, run here against sqlite.

2. WHAT IT IS CALLED. Settings > Naming > Document names, insert-if-missing
   seeded with Altura's format. Empty keeps the doctype's WMMP-#####, and
   existing plans keep their names.

    ./env/bin/python -m unittest work_management.tests.test_master_plans_by_greenhouse -v
"""

import json
import os
import unittest

from work_management.master_plan import (
	attributed_to_plan,
	blocks_greenhouses,
	expand_name_format,
	name_format_needs_greenhouse,
	name_part,
	pick_master_plan,
	plan_fits_blocks,
	resolve_master_plan,
	unattributed_to_plan,
)
from work_management.tests.test_concurrent_master_plans import SUM, Ledger, sqlite_query

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
	with open(os.path.join(HERE, *parts)) as handle:
		return handle.read()


def doctype(slug):
	return json.loads(read("work_management", "doctype", slug, slug + ".json"))


# {block: ancestors}: GH-3 and GH-4 are leaf greenhouses (Altura's shape), B1
# and B2 sit inside the group GH-9.
GH3 = {"GH-3 - KFL": {"GH-3 - KFL", "All - KFL"}}
GH4 = {"GH-4 - KFL": {"GH-4 - KFL", "All - KFL"}}
BOTH = dict(GH3, **GH4)
NESTED = {"B1": {"B1", "GH-9 - KFL", "All - KFL"}, "B2": {"B2", "GH-9 - KFL", "All - KFL"}}


def plan(name, gh=""):
	return {"name": name, "greenhouse": gh}


class TestWhichPlansMayFundTheBlocks(unittest.TestCase):
	def test_a_farm_level_plan_funds_anything(self):
		self.assertTrue(plan_fits_blocks("", BOTH))

	def test_a_greenhouse_plan_funds_its_own_greenhouse(self):
		self.assertTrue(plan_fits_blocks("GH-3 - KFL", GH3))

	def test_and_not_another(self):
		self.assertFalse(plan_fits_blocks("GH-3 - KFL", GH4))

	def test_every_block_has_to_be_in_it(self):
		self.assertFalse(plan_fits_blocks("GH-3 - KFL", BOTH))

	def test_a_block_under_a_greenhouse_group_is_in_it(self):
		self.assertTrue(plan_fits_blocks("GH-9 - KFL", NESTED))

	def test_blocks_not_known_yet_filter_nothing(self):
		"""The screen asks for dates before blocks; nothing is ruled out on a guess."""
		self.assertTrue(plan_fits_blocks("GH-3 - KFL", None))


class TestThePrecedence(unittest.TestCase):
	def test_a_greenhouse_plan_beats_the_farm_level_one(self):
		got = pick_master_plan("", [plan("FARM"), plan("GH3", "GH-3 - KFL")], GH3)
		self.assertEqual((got["name"], got["kind"]), ("GH3", "picked"))

	def test_the_farm_level_plan_covers_a_greenhouse_without_one(self):
		got = pick_master_plan("", [plan("FARM"), plan("GH3", "GH-3 - KFL")], GH4)
		self.assertEqual(got["name"], "FARM")

	def test_two_greenhouse_plans_for_the_blocks_are_refused_naming_both(self):
		got = pick_master_plan("", [plan("A", "GH-3 - KFL"), plan("B", "GH-3 - KFL"), plan("FARM")], GH3)
		self.assertIsNone(got["name"])
		self.assertEqual(got["kind"], "tied")
		self.assertEqual(got["tied"], ["A", "B"])
		self.assertIn("A, B", got["reason"])

	def test_the_farm_level_plan_does_not_break_a_greenhouse_tie(self):
		"""Refuse only when two at the SAME level qualify -- and the winning
		level here is greenhouse, where there are two."""
		got = pick_master_plan("", [plan("A", "GH-3 - KFL"), plan("B", "GH-3 - KFL"), plan("FARM")], GH3)
		self.assertNotEqual(got["name"], "FARM")

	def test_two_farm_level_plans_are_refused_as_before(self):
		got = pick_master_plan("", [plan("F1"), plan("F2")], GH3)
		self.assertEqual(got["kind"], "tied")

	def test_blocks_spanning_greenhouses_need_a_farm_level_plan(self):
		got = pick_master_plan("", [plan("FARM"), plan("GH3", "GH-3 - KFL"), plan("GH4", "GH-4 - KFL")], BOTH)
		self.assertEqual(got["name"], "FARM")

	def test_without_one_the_refusal_names_the_greenhouses(self):
		got = pick_master_plan("", [plan("GH3", "GH-3 - KFL"), plan("GH4", "GH-4 - KFL")], BOTH)
		self.assertIsNone(got["name"])
		self.assertEqual(got["kind"], "span")
		self.assertIn("GH-3 - KFL", got["reason"])
		self.assertIn("GH-4 - KFL", got["reason"])
		self.assertIn("one request per greenhouse", got["reason"])

	def test_a_greenhouse_with_no_plan_of_its_own_is_still_named(self):
		got = pick_master_plan("", [plan("GH3", "GH-3 - KFL")], BOTH)
		self.assertEqual(got["kind"], "span")
		self.assertIn("GH-4 - KFL", got["reason"])

	def test_one_block_and_no_plan_is_the_plain_refusal(self):
		got = pick_master_plan("", [plan("GH3", "GH-3 - KFL")], GH4)
		self.assertEqual(got["kind"], "none")


class TestTheStoredLink(unittest.TestCase):
	def test_it_wins_when_it_may_fund_the_blocks(self):
		"""The person chose the farm-level plan although a greenhouse one fits."""
		got = pick_master_plan("FARM", [plan("FARM"), plan("GH3", "GH-3 - KFL")], GH3)
		self.assertEqual(got["name"], "FARM")

	def test_a_plan_for_another_greenhouse_is_refused_and_says_why(self):
		got = pick_master_plan("GH3", [plan("FARM"), plan("GH3", "GH-3 - KFL")], GH4)
		self.assertIsNone(got["name"])
		self.assertEqual(got["kind"], "stored_elsewhere")
		self.assertIn("GH-3 - KFL", got["reason"])
		self.assertIn("GH-4 - KFL", got["reason"])

	def test_a_plan_that_does_not_cover_the_dates_is_refused_as_before(self):
		got = pick_master_plan("GONE", [plan("FARM")], GH3)
		self.assertEqual(got["kind"], "stored_missing")
		self.assertIn("does not cover this request's farm and dates", got["reason"])


class TestEveryOldCallerStillWorks(unittest.TestCase):
	"""Bare names are farm-level plans: the shape before greenhouses, and what
	patches/v1_0/link_planners_to_their_master_plan still passes."""

	def test_bare_names(self):
		self.assertEqual(resolve_master_plan("", ["WMMP-1"]), ("WMMP-1", None))
		self.assertIsNone(resolve_master_plan("", ["WMMP-1", "WMMP-2"])[0])

	def test_the_greenhouse_each_block_is_budgeted_under(self):
		houses = blocks_greenhouses([plan("G9", "GH-9 - KFL")], NESTED)
		self.assertEqual(houses, {"B1": "GH-9 - KFL", "B2": "GH-9 - KFL"})


class TestTheDrawdownFollowsThePrecedence(unittest.TestCase):
	"""attributed_to_plan / unattributed_to_plan, run for real against sqlite.

	Unlinked rows -- every request raised before the link existed -- go to the
	plan pick_master_plan() would pick. Linked rows go to their link, always.
	"""

	def setUp(self):
		led = self.led = Ledger()
		led.warehouse("All - KFL", 1, 100)
		led.warehouse("GH-3 - KFL", 2, 3)
		led.warehouse("GH-4 - KFL", 4, 5)
		led.warehouse("GH-9 - KFL", 6, 11)
		led.warehouse("B1", 7, 8)
		led.warehouse("B2", 9, 10)
		self.period = ("2026-11-01", "2026-11-30")

	def plan(self, name, gh=None, state="Approved"):
		return self.led.plan(name, "F", self.period[0], self.period[1], state=state, greenhouse=gh)

	def ask(self, plan):
		return self.led.charged(plan), self.led.unattributed(plan)

	def test_the_greenhouse_plan_takes_its_own_row_over_the_farm_plan(self):
		self.plan("FARM"); self.plan("GH3", "GH-3 - KFL")
		self.led.request("R1", "F", "2026-11-05", "2026-11-05", 6, block="GH-3 - KFL")
		self.assertEqual(self.ask("GH3"), (6, 0))
		self.assertEqual(self.ask("FARM"), (0, 0))

	def test_the_farm_plan_takes_a_row_no_greenhouse_plan_fits(self):
		self.plan("FARM"); self.plan("GH3", "GH-3 - KFL")
		self.led.request("R1", "F", "2026-11-05", "2026-11-05", 6, block="GH-4 - KFL")
		self.assertEqual(self.ask("FARM"), (6, 0))
		self.assertEqual(self.ask("GH3"), (0, 0))

	def test_an_extra_block_elsewhere_takes_it_off_the_greenhouse_plan(self):
		self.plan("FARM"); self.plan("GH3", "GH-3 - KFL")
		self.led.request("R1", "F", "2026-11-05", "2026-11-05", 6, block="GH-3 - KFL",
			extra_blocks=["GH-4 - KFL"])
		self.assertEqual(self.ask("GH3"), (0, 0))
		self.assertEqual(self.ask("FARM"), (6, 0))

	def test_a_block_under_a_greenhouse_group_is_its_plan_s(self):
		self.plan("FARM"); self.plan("G9", "GH-9 - KFL")
		self.led.request("R1", "F", "2026-11-05", "2026-11-05", 6, block="B1", extra_blocks=["B2"])
		self.assertEqual(self.ask("G9"), (6, 0))

	def test_two_greenhouse_plans_charge_neither_and_report_it(self):
		self.plan("A", "GH-3 - KFL"); self.plan("B", "GH-3 - KFL"); self.plan("FARM")
		self.led.request("R1", "F", "2026-11-05", "2026-11-05", 6, block="GH-3 - KFL")
		self.assertEqual(self.ask("A"), (0, 6))
		self.assertEqual(self.ask("B"), (0, 6))
		self.assertEqual(self.led.charged("FARM"), 0)

	def test_a_row_one_greenhouse_plan_takes_is_nobody_s_remainder(self):
		self.plan("F1"); self.plan("F2"); self.plan("GH3", "GH-3 - KFL")
		self.led.request("R1", "F", "2026-11-05", "2026-11-05", 6, block="GH-3 - KFL")
		self.assertEqual(self.ask("GH3"), (6, 0))
		self.assertEqual(self.ask("F1"), (0, 0))

	def test_a_pending_greenhouse_plan_changes_nothing(self):
		self.plan("FARM"); self.plan("GH3", "GH-3 - KFL", state="Pending Manager")
		self.led.request("R1", "F", "2026-11-05", "2026-11-05", 6, block="GH-3 - KFL")
		self.assertEqual(self.ask("FARM"), (6, 0))

	def test_a_linked_row_stays_with_its_link(self):
		self.plan("FARM"); self.plan("GH3", "GH-3 - KFL")
		self.led.request("R1", "F", "2026-11-05", "2026-11-05", 6, block="GH-3 - KFL",
			master_plan="FARM")
		self.assertEqual(self.ask("FARM"), (6, 0))
		self.assertEqual(self.ask("GH3"), (0, 0))

	def test_both_strings_format_with_any_alias(self):
		for rule in (attributed_to_plan("q"), unattributed_to_plan("q")):
			self.assertNotIn("{a}", rule)
			self.assertIn("q.block_section", rule)
			sqlite_query(SUM + rule)


class TestTheName(unittest.TestCase):
	def test_the_company_suffix_goes(self):
		self.assertEqual(name_part("GH-3 - KFL", "KFL"), "GH-3")

	def test_without_an_abbreviation_any_trailing_suffix_goes(self):
		self.assertEqual(name_part("GH-3 - KFL"), "GH-3")

	def test_it_is_made_safe_for_a_document_name(self):
		self.assertEqual(name_part("Green House/3 (east) - KFL", "KFL"), "Green-House-3-east")

	def test_altura_s_format(self):
		fmt = "{greenhouse}-MP-{YY}-{###}"
		self.assertEqual(expand_name_format(fmt, {"greenhouse": "GH-3", "YY": "26"}),
			("GH-3-MP-26-", 3, ""))

	def test_the_counter_key_differs_per_greenhouse_and_per_year(self):
		"""Frappe's series counts per prefix, which is what makes the counter run
		per greenhouse per year with nothing else keeping count."""
		fmt = "{greenhouse}-MP-{YY}-{###}"
		keys = {expand_name_format(fmt, {"greenhouse": g, "YY": y})[0]
			for g, y in (("GH-3", "26"), ("GH-4", "26"), ("GH-3", "27"))}
		self.assertEqual(len(keys), 3)

	def test_a_format_with_no_counter_gets_five_digits(self):
		self.assertEqual(expand_name_format("MP-{YYYY}-", {"YYYY": "2026"}), ("MP-2026-", 5, ""))

	def test_an_unknown_placeholder_is_refused(self):
		with self.assertRaises(ValueError):
			expand_name_format("{block}-{###}", {})

	def test_a_missing_value_is_refused_rather_than_left_blank(self):
		with self.assertRaises(ValueError):
			expand_name_format("{greenhouse}-MP-{###}", {"greenhouse": ""})

	def test_only_a_greenhouse_format_needs_a_greenhouse(self):
		self.assertTrue(name_format_needs_greenhouse("{greenhouse}-MP-{YY}-{###}"))
		self.assertFalse(name_format_needs_greenhouse(""))


class TestTheDoctypes(unittest.TestCase):
	def field(self, slug, fieldname):
		for f in doctype(slug)["fields"]:
			if f["fieldname"] == fieldname:
				return f

	def test_master_plan_has_a_greenhouse(self):
		f = self.field("work_management_master_plan", "greenhouse")
		self.assertEqual((f["fieldtype"], f["options"]), ("Link", "Warehouse"))
		self.assertIn("greenhouse", doctype("work_management_master_plan")["field_order"])

	def test_the_default_name_is_still_wmmp(self):
		"""Other sites, and an empty format, keep WMMP-#####."""
		d = doctype("work_management_master_plan")
		self.assertEqual(d["autoname"], "naming_series:")
		self.assertEqual(self.field("work_management_master_plan", "naming_series")["options"],
			"WMMP-.#####")

	def test_the_format_lives_in_the_naming_tab(self):
		order = doctype("work_management_settings")["field_order"]
		tab = order.index("tab_taxonomy")
		nxt = min(i for i, f in enumerate(order) if i > tab and f.startswith("tab_"))
		self.assertTrue(tab < order.index("mp_name_format") < nxt)

	def test_the_controller_names_new_plans_only(self):
		src = read("work_management", "doctype", "work_management_master_plan",
			"work_management_master_plan.py")
		self.assertIn("def autoname(self):", src)
		self.assertIn("master_plan_name(self)", src)


class TestTheSeed(unittest.TestCase):
	def setUp(self):
		self.src = read("patches", "v1_0", "seed_master_plan_name_format.py")

	def test_it_seeds_altura_s_format(self):
		self.assertIn('ALTURA_FORMAT = "{greenhouse}-MP-{YY}-{###}"', self.src)

	def test_it_never_overwrites(self):
		self.assertIn("if stored(FIELD) is not None:\n\t\treturn", self.src)

	def test_it_is_registered_before_the_rescue_patch(self):
		lines = [l.strip() for l in read("patches.txt").split("\n") if l.strip() and not l.startswith(("#", "["))]
		self.assertIn("work_management.patches.v1_0.seed_master_plan_name_format", lines)


class TestTheScreensShowTheGreenhouse(unittest.TestCase):
	def test_the_master_plan_api_reads_and_writes_it(self):
		src = read("api", "masterplan.py")
		self.assertIn('elif action == "greenhouses":', src)
		self.assertIn("d.greenhouse = sv_greenhouse or None", src)
		self.assertIn('out["greenhouse_required"]', src)
		self.assertIn('"farm", "greenhouse", "plan_name"', src)

	def test_the_planner_picker_offers_only_plans_that_fit(self):
		src = read("api", "planner.py")
		self.assertIn('bg["fits"] = 1 if plan_fits_blocks(', src)
		self.assertIn("mp.greenhouse", src)

	def test_the_planner_screen_shows_and_sends_it(self):
		src = read("public", "js", "work-planner.js")
		self.assertIn('id="mpf-greenhouse"', src)
		self.assertIn("<th>Greenhouse</th>", src)
		self.assertIn("blocks:pickedList().join(\",\")", src)

	def test_the_dashboard_shows_it(self):
		self.assertIn("mp.greenhouse", read("api", "dashboard.py"))
		self.assertIn("ghLabel(r.greenhouse)", read("public", "js", "work-management-dashboard.js"))


if __name__ == "__main__":
	unittest.main()
