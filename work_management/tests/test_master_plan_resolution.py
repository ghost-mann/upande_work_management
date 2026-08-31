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
