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
		"""What a fresh install gets, and the count that has to be deliberate.

		Fifteen steps: the fourteen this pipeline has always run, plus the second
		planner approval, which ships switched off (`default_off`) so adding it
		changed no existing chain. Pinning the number is what makes a sixteenth a
		decision rather than a diff nobody read.
		"""
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


class TestTheStagePickerOffersEveryConfiguredStep(unittest.TestCase):
	"""The picker on Stage Approver was a Select with fifteen labels compiled in.

	Now that a step can be added, that Select is the next thing that lies: the
	step exists, drives a real workflow transition, and cannot be chosen in the
	one table that names who takes it. `stage_labels()` was written for exactly
	this -- its docstring says "Select options for Work Management Stage
	Approver.stage_label" -- and nothing ever called it.
	"""

	def test_the_labels_come_from_the_configured_chain(self):
		s = Settings(rows(
			{"stage": "planner_submit", "stage_label": "Planner: Submit",
			 "document_type": "Work Management Planner", "kind": "Submit",
			 "state": "Draft", "action": "Go", "enabled": 1, "required": 1},
			{"stage": "planner_finance", "stage_label": "Planner: Finance",
			 "document_type": "Work Management Planner", "kind": "Approval",
			 "state": "Pending Finance", "action": "Finance Approve", "enabled": 1},
		))
		self.assertEqual(
			approvals.stage_labels(s), ["Planner: Submit", "Planner: Finance"]
		)

	def test_an_added_step_is_offered(self):
		"""The whole point: a step the app never shipped is choosable."""
		s = Settings(rows(
			{"stage": "planner_finance", "stage_label": "Planner: Finance",
			 "document_type": "Work Management Planner", "kind": "Approval",
			 "state": "Pending Finance", "action": "Finance Approve", "enabled": 1},
		))
		self.assertIn("Planner: Finance", approvals.stage_labels(s))
		# the picker's stored values are keys; the form shows the name
		self.assertIn("planner_finance", approvals.stage_keys(s))

	def test_two_steps_may_not_share_a_label(self):
		"""The picker stores a label, so a duplicate makes it ambiguous -- an
		approver row would resolve to whichever step sorted first."""
		self.assertIsNotNone(approvals.duplicate_stage_labels(
			["Planner: Finance", "Planner: Finance"]
		))
		self.assertIsNone(approvals.duplicate_stage_labels(
			["Planner: Submit", "Planner: Finance"]
		))

	def test_the_duplicate_report_names_the_label(self):
		bad = approvals.duplicate_stage_labels(["A", "B", "A", "B", "C"])
		self.assertIn("A", bad)
		self.assertIn("B", bad)
		self.assertNotIn("C", bad)

	def test_the_options_are_written_where_frappe_reads_them(self):
		"""Named once, in PICKER, rather than spelled into the function body."""
		self.assertEqual(approvals.PICKER, ("Work Management Stage Approver", "stage"))
		source = open(os.path.join(HERE, "approvals.py")).read()
		self.assertIn("def apply_stage_picker_options", source)
		block = source[source.index("def apply_stage_picker_options"):][:1400]
		self.assertIn("PICKER", block)
		self.assertIn('"options"', block)

	def test_it_runs_when_the_chain_changes(self):
		"""Adding a step and not refreshing the picker leaves the same lie in a
		different place, so it is wired to the same events that rebuild workflows."""
		hooks = open(os.path.join(HERE, "hooks.py")).read()
		controller = open(os.path.join(
			HERE, "work_management", "doctype", "work_management_settings",
			"work_management_settings.py")).read()
		self.assertTrue(
			"apply_stage_picker_options" in hooks
			or "apply_stage_picker_options" in controller,
			"nothing refreshes the picker",
		)
