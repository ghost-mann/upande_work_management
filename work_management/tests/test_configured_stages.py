"""The approval chain is what Settings holds, not what the code shipped.

`CATALOGUE` used to *be* the chain. Settings looked like it held it -- fifteen
editable rows -- but `stage_rows()` kept only rows whose key the code recognised
and `seed_stages()` deleted the rest, so a step somebody added was silently
thrown away on the next migrate. Switching a step off was configuration; adding
one was a release.

That is the wall this app hits at a second company: a deployment needing a
Finance sign-off, or two approval steps where Kaitet has three, cannot express it.

So the catalogue becomes the *seed* -- the default chain a fresh install starts
with -- and the chain itself is read from the rows, in their own order. A row with
a key the code has never heard of is a step like any other.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_configured_stages -v
"""

import json
import os
import unittest

from work_management import approvals

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Row(dict):
	"""A Settings child row, as frappe hands one over."""

	def __getattr__(self, name):
		try:
			return self[name]
		except KeyError:
			return None


def rows(*specs):
	out = []
	for i, spec in enumerate(specs, 1):
		row = Row(spec)
		row.setdefault("idx", i)
		out.append(row)
	return out


class Settings(dict):
	def __init__(self, stage_rows):
		super().__init__(approval_stages=stage_rows)

	def get(self, key, default=None):
		return dict.get(self, key, default)


class TestTheChainComesFromSettings(unittest.TestCase):
	def test_a_row_the_code_never_heard_of_is_a_step(self):
		"""The whole point. `finance_signoff` is in no catalogue anywhere."""
		s = Settings(rows(
			{"stage": "planner_submit", "stage_label": "Planner: Submit",
			 "document_type": "Work Management Planner", "kind": "Submit",
			 "state": "Draft", "action": "Submit for Approval", "role": "HR User",
			 "enabled": 1, "required": 1},
			{"stage": "finance_signoff", "stage_label": "Planner: Finance",
			 "document_type": "Work Management Planner", "kind": "Approval",
			 "state": "Pending Finance", "action": "Finance Approve",
			 "role": "Accounts Manager", "enabled": 1},
		))
		chain = approvals.configured_stages(s)
		self.assertEqual([st.key for st in chain], ["planner_submit", "finance_signoff"])
		finance = chain[1]
		self.assertEqual(finance.state, "Pending Finance")
		self.assertEqual(finance.action, "Finance Approve")
		self.assertEqual(finance.role, "Accounts Manager")

	def test_the_order_is_the_rows_order_not_the_catalogues(self):
		"""Reordering the table reorders the chain -- that is what a step's
		position means, and idx is what the grid gives you when you drag a row."""
		s = Settings(rows(
			{"stage": "b", "stage_label": "B", "document_type": "X", "kind": "Approval",
			 "state": "S2", "action": "A2", "enabled": 1, "idx": 2},
			{"stage": "a", "stage_label": "A", "document_type": "X", "kind": "Submit",
			 "state": "S1", "action": "A1", "enabled": 1, "idx": 1},
		))
		self.assertEqual([st.key for st in approvals.configured_stages(s)], ["a", "b"])

	def test_a_row_with_no_key_is_ignored_rather_than_crashing(self):
		"""A half-typed row in an open grid must not take the migrate down."""
		s = Settings(rows(
			{"stage": "", "stage_label": "", "document_type": "X", "kind": "Approval"},
			{"stage": "a", "stage_label": "A", "document_type": "X", "kind": "Submit",
			 "state": "S1", "action": "A1", "enabled": 1},
		))
		self.assertEqual([st.key for st in approvals.configured_stages(s)], ["a"])

	def test_settings_with_no_rows_falls_back_to_the_shipped_chain(self):
		"""A site mid-install has no rows yet, and must still generate workflows."""
		chain = approvals.configured_stages(Settings([]))
		self.assertEqual([st.key for st in chain], [st.key for st in approvals.CATALOGUE])

	def test_the_shipped_catalogue_is_still_the_seed(self):
		"""Nothing changes for an existing deployment: the fifteen steps Kaitet
		runs are the fifteen the app ships, and they are what a fresh install gets."""
		self.assertEqual(len(approvals.CATALOGUE), 15)


class TestTheChildTableCanCarryAStep(unittest.TestCase):
	"""A row has to hold everything a step is, or the chain cannot come from it."""

	def field(self, fieldname):
		path = os.path.join(HERE, "work_management", "doctype",
			"work_management_approval_stage", "work_management_approval_stage.json")
		with open(path) as handle:
			doc = json.load(handle)
		for f in doc.get("fields", []):
			if f.get("fieldname") == fieldname:
				return f
		return None

	def test_it_carries_the_state_and_the_action(self):
		"""Without these the chain is unbuildable from the rows -- they are the
		workflow state a step waits in and the button that leaves it."""
		self.assertEqual(self.field("state")["fieldtype"], "Data")
		self.assertEqual(self.field("action")["fieldtype"], "Data")

	def test_it_carries_whether_the_step_is_scoped(self):
		self.assertEqual(self.field("scoped")["fieldtype"], "Check")

	def test_it_carries_whether_the_step_can_be_switched_off(self):
		self.assertEqual(self.field("required")["fieldtype"], "Check")

	def test_the_shipped_steps_stay_read_only_where_they_must(self):
		"""Renaming a shipped step's key would orphan documents sitting in its
		state, so the key is not editable. Everything else about a row is."""
		self.assertTrue(self.field("stage").get("read_only"))


class TestSeedingNoLongerDeletesWhatItDoesNotRecognise(unittest.TestCase):
	def test_the_seed_keeps_rows_it_did_not_create(self):
		source = open(os.path.join(HERE, "approvals.py")).read()
		block = source[source.index("def seed_stages"):]
		block = block[:block.index("\ndef ")]
		self.assertIn("keep", block.lower())
		self.assertNotIn("Rows for\n\tstages that no longer exist are dropped", block)
