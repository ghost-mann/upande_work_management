"""A step with documents waiting in it cannot be switched off.

Switching a step off removes its state from the chain. A document sitting in that
state when it goes is stranded -- there is no transition out, and the screen that
used to offer one no longer knows the state exists.

The alternative was to advance those documents automatically as part of the save,
which is convenient and defensible since the step is being removed anyway. It was
rejected deliberately: it means a document passes an approval nobody gave, and
the audit trail then shows an HR step cleared with no approver. Refusing is the
honest option, and clearing a busy step first is a small cost.

Only steps being switched off **in this save** are checked. Checking every
already-off step would mean that a single document somehow sitting in a retired
state -- restored from a backup, edited directly -- would refuse every future
Settings save, locking the whole configuration screen. A guard that can lock you
out of the thing that fixes it is worse than the problem.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_switching_off_a_busy_step -v
"""

import unittest
from unittest import mock

from work_management import approvals

SWITCHED_OFF = approvals.steps_switched_off


def before(**enabled):
	return dict(enabled)


class TestWhichStepsAreBeingSwitchedOff(unittest.TestCase):
	def test_on_to_off_is_caught(self):
		self.assertEqual(
			SWITCHED_OFF({"assigner_hr_head": 1}, {"assigner_hr_head": 0}),
			["assigner_hr_head"])

	def test_off_to_off_is_not_caught(self):
		"""Already off. Checking it would refuse every save for as long as one
		stray document sat in a retired state."""
		self.assertEqual(
			SWITCHED_OFF({"assigner_hr_head": 0}, {"assigner_hr_head": 0}), [])

	def test_on_to_on_is_not_caught(self):
		self.assertEqual(
			SWITCHED_OFF({"assigner_hr_head": 1}, {"assigner_hr_head": 1}), [])

	def test_off_to_on_is_not_caught(self):
		"""Switching a step back on strands nothing."""
		self.assertEqual(
			SWITCHED_OFF({"assigner_hr_head": 0}, {"assigner_hr_head": 1}), [])

	def test_several_at_once(self):
		self.assertEqual(
			SWITCHED_OFF(
				{"a": 1, "b": 1, "c": 1},
				{"a": 0, "b": 1, "c": 0}),
			["a", "c"])

	def test_a_step_new_in_this_save_is_not_caught(self):
		"""It has no history, so nothing can be waiting in it."""
		self.assertEqual(SWITCHED_OFF({}, {"assigner_hr_head": 0}), [])

	def test_a_step_removed_in_this_save_is_not_caught(self):
		"""Deleting a row is a different act from switching it off, and it does
		not reach this guard -- the row is simply gone."""
		self.assertEqual(SWITCHED_OFF({"assigner_hr_head": 1}, {}), [])

	def test_the_order_is_stable(self):
		self.assertEqual(
			SWITCHED_OFF({"z": 1, "a": 1}, {"z": 0, "a": 0}), ["a", "z"])

	def test_a_first_save_switches_nothing_off(self):
		"""`get_doc_before_save()` returns None on insert, which arrives here as
		an empty mapping."""
		self.assertEqual(SWITCHED_OFF(None, {"assigner_hr_head": 0}), [])


class TestTheRefusalExplainsItself(unittest.TestCase):
	"""`_()` needs a site to look translations up in, and this is about how the
	sentence is put together rather than about translating it -- so the translator
	is the identity here and the composition is what gets asserted."""

	def setUp(self):
		patch = mock.patch.object(approvals, "_", lambda text: text)
		patch.start()
		self.addCleanup(patch.stop)

	def MESSAGE(self, blocked):
		return approvals.busy_step_message(blocked)

	def test_it_names_the_step(self):
		self.assertIn("Assigner: HR Head",
			self.MESSAGE([("Assigner: HR Head", "Pending HR Head", 4)]))

	def test_it_gives_the_count(self):
		self.assertIn("4", self.MESSAGE([("Assigner: HR Head", "Pending HR Head", 4)]))

	def test_it_says_what_to_do(self):
		"""Somebody stopped by this needs the way through, not just the refusal."""
		text = self.MESSAGE([("Assigner: HR Head", "Pending HR Head", 4)])
		self.assertIn("Approve or reject", text)

	def test_it_lists_every_blocked_step(self):
		text = self.MESSAGE([
			("Assigner: HR Head", "Pending HR Head", 4),
			("Actuals: Farm Manager", "Pending Farm Manager", 7)])
		self.assertIn("Assigner: HR Head", text)
		self.assertIn("Actuals: Farm Manager", text)
		self.assertIn("7", text)

	def test_one_step_reads_as_one_not_as_a_list(self):
		"""The common case is a single step, and a bulleted list of one reads
		like a bug."""
		text = self.MESSAGE([("Assigner: HR Head", "Pending HR Head", 1)])
		self.assertNotIn("\n", text.strip())

	def test_a_single_waiting_document_is_singular(self):
		text = self.MESSAGE([("Assigner: HR Head", "Pending HR Head", 1)])
		self.assertIn("1 document is", text)

	def test_several_waiting_documents_are_plural(self):
		text = self.MESSAGE([("Assigner: HR Head", "Pending HR Head", 4)])
		self.assertIn("4 documents are", text)


class TestTheGuardIsWiredIn(unittest.TestCase):
	def test_saving_settings_runs_the_check(self):
		import inspect

		source = inspect.getsource(approvals.validate_configuration)
		self.assertIn("validate_switching_off", source)

	def test_the_check_uses_the_tested_rule(self):
		import inspect

		source = inspect.getsource(approvals.validate_switching_off)
		self.assertIn("steps_switched_off", source)

	def test_it_reads_the_previous_state_of_the_document(self):
		"""Comparing against what was stored is the whole mechanism; without it
		the guard cannot tell a step being switched off from one already off."""
		import inspect

		source = inspect.getsource(approvals.validate_switching_off)
		self.assertIn("get_doc_before_save", source)

	def test_it_runs_before_the_farm_coverage_check(self):
		"""Stranding work is worse than misconfiguring it, so it is reported
		first -- otherwise a farm-coverage complaint hides the real problem."""
		import inspect

		source = inspect.getsource(approvals.validate_configuration)
		self.assertLess(source.index("validate_switching_off"),
			source.index("would strand a farm"))


if __name__ == "__main__":
	unittest.main()
