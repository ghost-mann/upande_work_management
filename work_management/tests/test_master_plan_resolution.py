"""Which master plan a request draws against.

A farm may hold more than one master plan over the same days -- field operations
and a replanting project, each with its own budget. The moment that is possible,
the request's dates stop identifying a budget, and the old lookup
(`ORDER BY period_from DESC LIMIT 1`) would silently draw work down against
whichever plan happened to sort first.

So the request carries the answer, and this is the rule that reads it::

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_master_plan_resolution -v

It lives in master_plan.py, beside the cap arithmetic it belongs with, and the
mirror inlines it because a Server Script sandbox allows no `def`.
"""

import json
import os
import unittest

from work_management.master_plan import resolve_master_plan

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def shipped(slug):
	path = os.path.join(HERE, "work_management", "doctype", slug, slug + ".json")
	with open(path) as handle:
		return json.load(handle)


def field(slug, fieldname):
	for f in shipped(slug).get("fields", []):
		if f.get("fieldname") == fieldname:
			return f
	return None


class TestResolution(unittest.TestCase):
	def test_a_stored_link_wins_even_when_others_contain_the_dates(self):
		"""The whole point: two plans cover these days and the request says which."""
		self.assertEqual(
			resolve_master_plan("WMMP-2", ["WMMP-1", "WMMP-2"]), ("WMMP-2", None)
		)

	def test_one_candidate_and_nothing_stored_resolves_to_it(self):
		"""Every request written before the field existed looks like this."""
		self.assertEqual(resolve_master_plan("", ["WMMP-1"]), ("WMMP-1", None))

	def test_two_candidates_and_nothing_stored_refuses(self):
		"""Refused rather than guessed, and both names are in the message: the
		person reading it is the one who knows which budget the work came from."""
		name, reason = resolve_master_plan("", ["WMMP-1", "WMMP-2"])
		self.assertIsNone(name)
		self.assertIn("WMMP-1", reason)
		self.assertIn("WMMP-2", reason)

	def test_no_candidate_refuses_and_says_so(self):
		name, reason = resolve_master_plan("", [])
		self.assertIsNone(name)
		self.assertIn("no approved master plan", reason.lower())

	def test_a_stored_link_that_does_not_contain_the_dates_refuses(self):
		"""A plan can be edited after a request named it, or the dates widened."""
		name, reason = resolve_master_plan("WMMP-9", ["WMMP-1"])
		self.assertIsNone(name)
		self.assertIn("WMMP-9", reason)

	def test_none_and_empty_string_mean_the_same_absence(self):
		self.assertEqual(resolve_master_plan(None, ["WMMP-1"]), ("WMMP-1", None))

	def test_blank_candidates_are_ignored_rather_than_counted(self):
		"""A null farm or a null period yields a blank row from SQL; counting it
		would report two candidates where there is one."""
		self.assertEqual(resolve_master_plan("", ["WMMP-1", None, ""]), ("WMMP-1", None))

	def test_the_refusal_names_the_plans_in_a_stable_order(self):
		"""So the message reads the same on every attempt."""
		a = resolve_master_plan("", ["WMMP-2", "WMMP-1"])[1]
		b = resolve_master_plan("", ["WMMP-1", "WMMP-2"])[1]
		self.assertEqual(a, b)


class TestTheFields(unittest.TestCase):
	def test_the_plan_carries_a_purpose(self):
		"""Two Saboti plans for August are otherwise two numbers in a picker."""
		f = field("work_management_master_plan", "plan_name")
		self.assertIsNotNone(f)
		self.assertEqual(f["fieldtype"], "Data")
		self.assertFalse(f.get("reqd"), "a plan raised before this field existed has none")

	def test_the_purpose_is_what_a_plan_is_titled_by(self):
		"""title_field was `farm`, so two plans for one farm rendered identically
		in every link field and list. Frappe falls back to the docname where the
		purpose is empty, which is the old behaviour for older plans."""
		self.assertEqual(shipped("work_management_master_plan").get("title_field"), "plan_name")

	def test_the_request_carries_its_plan(self):
		f = field("work_management_planner", "master_plan")
		self.assertIsNotNone(f)
		self.assertEqual(f["fieldtype"], "Link")
		self.assertEqual(f["options"], "Work Management Master Plan")

	def test_the_link_is_not_reqd_on_the_doctype(self):
		"""Enforced in save(), where it can be conditional: a farm with no plan at
		all must still raise requests, and 1,578 rows predate the field."""
		self.assertFalse(field("work_management_planner", "master_plan").get("reqd"))

	def test_the_request_does_not_let_someone_type_it_in(self):
		"""The screen sets it from the plan that was chosen. Typed by hand it
		would name a budget nobody picked."""
		self.assertTrue(field("work_management_planner", "master_plan").get("read_only"))


def ported(module):
	with open(os.path.join(HERE, "api", module + ".py")) as handle:
		return handle.read()


class TestOverlapNoLongerBlocks(unittest.TestCase):
	"""A farm may hold two budgets over the same days.

	The rule that prevented it was not arbitrary -- nothing recorded which plan a
	request belonged to, so one plan per period was what made the inference safe.
	The link makes it unnecessary, and what is left is worth keeping as a note:
	raising the same plan twice by mistake looks exactly like raising a deliberate
	second one, and creation is the cheapest moment to notice.
	"""

	def setUp(self):
		self.src = ported("masterplan")

	def test_a_clash_no_longer_becomes_an_error(self):
		self.assertNotIn("already has a master plan covering those dates", self.src)
		self.assertNotIn("A farm has one budget per period", self.src)

	def test_a_clash_is_still_reported(self):
		self.assertIn('out["clash"]', self.src)
		self.assertIn("clash_warning", self.src)

	def test_period_free_stops_saying_a_period_is_taken(self):
		"""The form asked this the moment a farm and period were chosen, and used
		the answer to refuse. It now reports the neighbour and lets you continue."""
		block = self.src[self.src.index('action == "period_free"'):][:1800]
		self.assertIn('out["free"] = 1', block)
		self.assertNotIn('out["free"] = 0', block)
