"""The chain reaches the screens through get_config(), like everything else.

`port_app.py` strips the mirror's module-top constants and rebuilds them from
`get_config()`. That is how every ported screen gets its `FARMS`, and it is how
they will get the approval chain: one stripped line each, so the app reads the
configuration and the live Server Script reads its own fallback, with no third
implementation in between.

Two keys, because the screens need two different things and mixing them is the
bug this whole change fixes:

  `stage_rows`    every step, in order, with the state it waits in, the state
                  approving it leads to, and whether it is on. For **writes**.
  `stage_states`  every state a document could be carrying, per document type,
                  switched-off steps included. For **reads**.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_config_carries_the_chain -v
"""

import inspect
import json
import unittest

from work_management import approvals
from work_management.api import config


class TestGetConfigExposesTheChain(unittest.TestCase):
	def setUp(self):
		self.source = inspect.getsource(config.get_config)

	def test_it_carries_the_steps(self):
		self.assertIn('"stage_rows"', self.source)

	def test_it_carries_the_readable_states(self):
		self.assertIn('"stage_states"', self.source)

	def test_the_steps_come_from_the_shared_helper(self):
		"""Not recomputed here. Two implementations of the chain is the defect."""
		self.assertIn("effective_chain", self.source)

	def test_the_states_come_from_the_shared_helper(self):
		self.assertIn("pipeline_states", self.source)

	def test_an_unconfigured_install_still_gets_both_keys(self):
		"""`get_config()` returns early when Settings will not load, and a screen
		reading a missing key would fail at module top -- taking the whole screen
		down rather than degrading."""
		early = self.source[:self.source.index("try:")]
		self.assertIn('"stage_rows"', early)
		self.assertIn('"stage_states"', early)


class TestTheDefaultsAreUsable(unittest.TestCase):
	"""What a screen gets before anything is configured. It has to be the shipped
	chain, not empty: an empty chain means no screen can advance anything."""

	def test_the_fallback_chain_is_the_shipped_one(self):
		rows = approvals.effective_chain(settings=None)
		self.assertTrue(rows)
		keys = {row["key"] for row in rows}
		for key in ("assigner_farm_manager", "assigner_hr_head", "assigner_gm"):
			self.assertIn(key, keys)

	def test_every_shipped_step_is_on_by_default(self):
		for row in approvals.effective_chain(settings=None):
			self.assertTrue(row["on"], "%s ships off" % row["key"])

	def test_the_shipped_assigner_chain_is_fm_then_hr_then_gm(self):
		by_key = {r["key"]: r for r in approvals.effective_chain(settings=None)}
		self.assertEqual(by_key["assigner_farm_manager"]["next_state"], "Pending HR Head")
		self.assertEqual(by_key["assigner_hr_head"]["next_state"], "Pending GM")
		self.assertEqual(by_key["assigner_gm"]["next_state"],
			approvals.CHAIN_ENDS["Work Management Assigner"]["terminal"][0])

	def test_gates_are_not_steps(self):
		"""A Gate is not a workflow transition, so it must never appear as one --
		a screen advancing into a Gate's state would strand the document, since
		the state does not exist in any workflow."""
		keys = {row["key"] for row in approvals.effective_chain(settings=None)}
		gates = [s.key for s in approvals.CATALOGUE if s.kind == "Gate"]
		for key in gates:
			self.assertNotIn(key, keys)


class TestItSurvivesTheTripToAServerScript(unittest.TestCase):
	"""Both keys are serialised into a Server Script's globals, so anything that
	is not plain JSON breaks at module top -- before any action runs."""

	def test_the_steps_are_json(self):
		rows = approvals.effective_chain(settings=None)
		self.assertEqual(json.loads(json.dumps(rows)), rows)

	def test_the_states_are_json(self):
		states = {
			doctype: approvals.pipeline_states(settings=None, document_type=doctype)
			for doctype in approvals.CHAIN_ENDS
		}
		self.assertEqual(json.loads(json.dumps(states)), states)


class TestTheReadableStatesCoverEveryDocumentType(unittest.TestCase):
	def test_one_entry_per_pipeline_doctype(self):
		for doctype in approvals.CHAIN_ENDS:
			states = approvals.pipeline_states(settings=None, document_type=doctype)
			self.assertTrue(states["all"], "%s has no readable states" % doctype)

	def test_each_includes_its_own_terminal_state(self):
		for doctype, ends in approvals.CHAIN_ENDS.items():
			states = approvals.pipeline_states(settings=None, document_type=doctype)
			self.assertEqual(states["terminal"], ends["terminal"][0])
			self.assertIn(ends["terminal"][0], states["all"])

	def test_no_document_type_leaks_another_ones_states(self):
		"""`CONFIRMED` belongs to Actuals and `Paid` to Payment; a filter that
		mixed them would widen a list past its own pipeline."""
		payment = approvals.pipeline_states(
			settings=None, document_type="Work Management Payment")
		self.assertIn("Paid", payment["all"])
		self.assertNotIn("CONFIRMED", payment["all"])

	def test_every_group_is_present_for_every_doctype(self):
		"""A screen reading a missing group fails at module top and takes the
		whole page with it."""
		for doctype in approvals.CHAIN_ENDS:
			states = approvals.pipeline_states(settings=None, document_type=doctype)
			for group in ("draft", "terminal", "reject", "waiting", "active",
					"open", "all"):
				self.assertIn(group, states, "%s missing %s" % (doctype, group))

	def test_payment_has_no_draft_state(self):
		"""Its chain starts at Unpaid -- a payment run is created already in the
		chain. So `draft` is honestly None rather than invented, and a screen
		must not assume every pipeline has a draft."""
		payment = approvals.pipeline_states(
			settings=None, document_type="Work Management Payment")
		self.assertIsNone(payment["draft"])


if __name__ == "__main__":
	unittest.main()
