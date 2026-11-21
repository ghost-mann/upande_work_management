import json
import os
import unittest

from work_management.portions import (
	portion_changes,
	portion_cost,
	portion_errors,
	portion_headroom,
	unallocated,
)

LINE = {"task": "TASK-1", "label": "Pruning", "work_qty": 100, "cost": 1000}


def P(key, tl, qty, blocks, cost=None):
	return {"portion_key": key, "team_leader": tl, "work_qty": qty,
	        "cost": qty * 10 if cost is None else cost, "blocks": blocks}


class Errors(unittest.TestCase):
	def test_a_clean_split_has_no_errors(self):
		self.assertEqual(portion_errors(LINE, [P("a", "otieno", 60, ["B1"]), P("b", "chebet", 40, ["B2"])]), [])

	def test_over_the_line_quantity(self):
		errs = portion_errors(LINE, [P("a", "otieno", 61, ["B1"], cost=590), P("b", "chebet", 40, ["B2"])])
		self.assertEqual(len(errs), 1)
		self.assertIn("over", errs[0])
		self.assertIn("101", errs[0])

	def test_over_the_line_cost_alone(self):
		errs = portion_errors(LINE, [P("a", "otieno", 50, ["B1"], cost=900), P("b", "chebet", 40, ["B2"])])
		self.assertTrue(any("KES" in e for e in errs))

	def test_a_block_in_two_portions_is_named(self):
		errs = portion_errors(LINE, [P("a", "otieno", 50, ["B1", "B3"]), P("b", "chebet", 40, ["B3"])])
		self.assertEqual(len(errs), 1)
		self.assertIn("B3", errs[0])
		self.assertIn("otieno", errs[0])
		self.assertIn("chebet", errs[0])

	def test_a_portion_needs_a_leader_and_a_block(self):
		errs = portion_errors(LINE, [P("a", "", 50, ["B1"]), P("b", "chebet", 40, [])])
		self.assertEqual(len(errs), 2)
		self.assertIn("team leader", errs[0])
		self.assertIn("block", errs[1])

	def test_the_same_leader_may_run_two_portions(self):
		self.assertEqual(portion_errors(LINE, [P("a", "otieno", 50, ["B1"]), P("b", "otieno", 40, ["B2"])]), [])

	def test_leader_must_be_on_the_list_when_one_is_given(self):
		errs = portion_errors(LINE, [P("a", "stranger", 50, ["B1"])], valid_leaders={"otieno"})
		self.assertEqual(len(errs), 1)
		self.assertIn("stranger", errs[0])

	def test_cannot_cut_a_portion_below_what_it_has_used(self):
		errs = portion_errors(LINE, [P("a", "otieno", 40, ["B1"])], used={"a": {"q": 50, "c": 500}})
		self.assertEqual(len(errs), 1)
		self.assertIn("50", errs[0])

	def test_cannot_remove_a_portion_with_requests(self):
		errs = portion_errors(LINE, [P("b", "chebet", 40, ["B2"])], used={"a": {"q": 10, "c": 100}},
		                      leaders={"a": "otieno"})
		self.assertEqual(len(errs), 1)
		self.assertIn("has requests", errs[0])
		self.assertIn("otieno", errs[0])

	def test_earlier_requests_without_a_portion_take_room(self):
		ok = [P("a", "otieno", 40, ["B1"]), P("b", "chebet", 30, ["B2"])]
		self.assertEqual(portion_errors(LINE, ok, legacy={"q": 30, "c": 300}), [])
		errs = portion_errors(LINE, ok, legacy={"q": 31, "c": 310})
		self.assertEqual(len(errs), 2)
		self.assertIn("earlier requests", errs[0])

	def test_no_portions_is_always_fine(self):
		self.assertEqual(portion_errors(LINE, []), [])


class Figures(unittest.TestCase):
	def test_cost_is_qty_times_rate_rounded(self):
		self.assertEqual(portion_cost(7, 1.333), 9.33)
		self.assertEqual(portion_cost(None, 5), 0.0)

	def test_headroom(self):
		h = portion_headroom(P("a", "otieno", 60, ["B1"]), {"q": 59.999, "c": 599.99})
		self.assertAlmostEqual(h["remaining_qty"], 0.001)
		self.assertTrue(h["exhausted"])
		self.assertFalse(portion_headroom(P("a", "otieno", 60, ["B1"]), None)["exhausted"])

	def test_unallocated_is_the_gap(self):
		u = unallocated(LINE, [P("a", "otieno", 60, ["B1"])], legacy={"q": 10, "c": 100})
		self.assertEqual(u, {"qty": 30.0, "cost": 300.0})


class Changes(unittest.TestCase):
	def test_each_kind_is_reported(self):
		old = [P("a", "otieno", 60, ["B1"]), P("b", "chebet", 40, ["B2"])]
		new = [P("a", "wanjiru", 50, ["B1", "B4"]), P("c", "kamau", 10, ["B5"])]
		ch = portion_changes(old, new)
		kinds = sorted((c["kind"], c["portion_key"]) for c in ch)
		self.assertEqual(kinds, [("added", "c"), ("blocks", "a"), ("budget", "a"), ("leader", "a"), ("removed", "b")])
		lead = [c for c in ch if c["kind"] == "leader"][0]
		self.assertEqual((lead["old_value"], lead["new_value"]), ("otieno", "wanjiru"))
		bud = [c for c in ch if c["kind"] == "budget"][0]
		self.assertEqual((bud["old_value"], bud["new_value"]), ("60", "50"))

	def test_nothing_changed_is_nothing(self):
		old = [P("a", "otieno", 60, ["B2", "B1"])]
		self.assertEqual(portion_changes(old, [P("a", "otieno", 60, ["B1", "B2"])]), [])


DOCTYPES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "work_management", "doctype")


def meta(name):
	with open(os.path.join(DOCTYPES, name, name + ".json")) as f:
		return json.load(f)


class Doctypes(unittest.TestCase):
	def test_the_master_plan_carries_the_three_tables(self):
		f = {x["fieldname"]: x for x in meta("work_management_master_plan")["fields"]}
		self.assertEqual(f["portions"]["options"], "Work Management Activity Portion")
		self.assertEqual(f["portion_blocks"]["options"], "Work Management Activity Portion Block")
		self.assertEqual(f["portion_changes"]["options"], "Work Management Portion Change")
		order = meta("work_management_master_plan")["field_order"]
		for k in ("portions", "portion_blocks", "portion_changes"):
			self.assertIn(k, order)

	def test_the_child_tables_are_tables(self):
		for n in ("work_management_activity_portion", "work_management_activity_portion_block",
		          "work_management_portion_change"):
			self.assertEqual(meta(n).get("istable"), 1, n)

	def test_a_portion_has_its_fields(self):
		names = {x["fieldname"] for x in meta("work_management_activity_portion")["fields"]}
		self.assertTrue({"portion_key", "task", "team_leader", "label", "work_qty", "cost",
		                 "man_days", "days"} <= names)

	def test_the_planner_carries_the_portion(self):
		f = {x["fieldname"]: x for x in meta("work_management_planner")["fields"]}
		self.assertEqual(f["portion"]["fieldtype"], "Data")
		self.assertEqual(f["portion"].get("allow_on_submit"), 1)
