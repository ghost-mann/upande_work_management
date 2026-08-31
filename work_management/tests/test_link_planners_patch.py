"""Recording which plan each existing request drew against.

`master_plan` arrives with this release; 1,578 requests on live predate it. Their
budget was inferred from farm plus dates, which was reliable only because two
plans could not cover the same days -- so every one of them has exactly one
answer, and this release is the last moment that is true. Once somebody raises a
second overlapping plan, a request written before then can no longer be resolved
at all.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_link_planners_patch -v

The decision is resolve_master_plan(), tested in test_master_plan_resolution.py.
What is tested here is the patch's own contract: what it touches, what it refuses
to touch, and that it runs after the field it writes to exists.
"""

import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestItIsRegisteredInTheRightPlace(unittest.TestCase):
	def test_it_runs_after_the_model_is_synced(self):
		"""It writes to a column that arrives with this release."""
		with open(os.path.join(HERE, "patches.txt")) as handle:
			txt = handle.read()
		self.assertIn("link_planners_to_their_master_plan", txt)
		self.assertGreater(
			txt.index("link_planners_to_their_master_plan"), txt.index("[post_model_sync]")
		)


class TestWhatItRefusesToDo(unittest.TestCase):
	def setUp(self):
		with open(os.path.join(
			HERE, "patches", "v1_0", "link_planners_to_their_master_plan.py")) as handle:
			self.src = handle.read()

	def test_it_only_looks_at_rows_with_no_link(self):
		"""A request that already names its plan is already right, and overwriting
		it would undo a correction somebody made deliberately."""
		self.assertIn("IFNULL(master_plan, '') = ''", self.src)

	def test_it_writes_with_set_value_not_a_saved_document(self):
		"""Planner is submittable; a submitted document will not accept a save."""
		self.assertIn("frappe.db.set_value", self.src)
		self.assertIn("update_modified=False", self.src)
		self.assertNotIn(".save(", self.src)

	def test_it_asks_whether_the_column_exists_before_writing_to_it(self):
		"""A site mid-migrate may not have synced the doctype, and asking for a
		missing column is a hard SQL error that takes the whole migrate down."""
		self.assertIn('has_column("Work Management Planner", "master_plan")', self.src)

	def test_it_uses_the_shared_rule_rather_than_its_own_copy(self):
		self.assertIn("from work_management.master_plan import resolve_master_plan", self.src)

	def test_an_ambiguous_request_is_named_rather_than_guessed(self):
		self.assertIn("left unlinked rather than guessed", self.src)

	def test_it_reports_what_it_could_not_resolve(self):
		"""Silence here would hide the rows that need a human."""
		self.assertIn("no covering plan", self.src)
