"""Guards on the task-worker rule and on spotting rows it no longer agrees with.

Pure: settings text and employee fields in, verdicts out. No site::

    ./env/bin/python -m unittest work_management.tests.test_payroll_rule -v
"""

import unittest

from work_management import payroll_rule as rule


class TestReadingTheConfiguredLists(unittest.TestCase):
	"""These are free-text boxes whose contents are interpolated into SQL. A
	newline in one of them once took the whole list down silently and stopped
	315 task workers being payable, so how the text is read is the part that
	has actually broken in production.
	"""

	def test_a_comma_separated_list_is_read(self):
		self.assertEqual(rule.parse_list("Contract, Permanent"), {"Contract", "Permanent"})

	def test_a_newline_separated_list_is_read_too(self):
		"""The regression that stopped 315 people being paid."""
		self.assertEqual(rule.parse_list("Task Worker\nSecurity Guard"),
			{"Task Worker", "Security Guard"})

	def test_a_windows_newline_is_read_too(self):
		self.assertEqual(rule.parse_list("Task Worker\r\nSecurity Guard"),
			{"Task Worker", "Security Guard"})

	def test_padding_is_trimmed(self):
		self.assertEqual(rule.parse_list("  Contract  ,  Permanent "), {"Contract", "Permanent"})

	def test_an_empty_box_reads_as_nothing(self):
		self.assertEqual(rule.parse_list(""), set())
		self.assertEqual(rule.parse_list(None), set())

	def test_a_value_that_could_break_out_of_the_sql_is_dropped(self):
		"""Dropped on its own -- never taking the rest of the list with it."""
		self.assertEqual(rule.parse_list("Contract, Rob'; drop table--, Permanent"),
			{"Contract", "Permanent"})

	def test_the_punctuation_a_job_title_really_uses_is_kept(self):
		self.assertEqual(rule.parse_list("Cook / Cleaner, Director's Aide, Fixed-Term"),
			{"Cook / Cleaner", "Director's Aide", "Fixed-Term"})


class TestWhoQualifies(unittest.TestCase):
	"""Any one of the three lists is enough -- they are ORed, not ANDed."""

	RULE = {"employment_type": {"Contract"},
		"designation": {"Task Worker", "Security Guard"},
		"custom_category": {"Value Adder"}}

	def test_the_employment_type_alone_qualifies(self):
		self.assertTrue(rule.qualifies({"employment_type": "Contract"}, self.RULE))

	def test_the_designation_alone_qualifies(self):
		"""626 people are carried by this and nothing else."""
		self.assertTrue(rule.qualifies(
			{"employment_type": "Task Worker", "designation": "Task Worker"}, self.RULE))

	def test_the_category_alone_qualifies(self):
		self.assertTrue(rule.qualifies(
			{"employment_type": "Permanent", "custom_category": "Value Adder"}, self.RULE))

	def test_matching_nothing_does_not_qualify(self):
		self.assertFalse(rule.qualifies(
			{"employment_type": "Permanent", "designation": "Supervisor",
			 "custom_category": "Team Leader"}, self.RULE))

	def test_a_missing_field_is_not_a_match(self):
		self.assertFalse(rule.qualifies({}, self.RULE))

	def test_an_empty_rule_never_qualifies_anyone(self):
		"""Fail closed. A blank or unusable Settings must not pay everyone."""
		self.assertFalse(rule.qualifies({"employment_type": "Contract"},
			{"employment_type": set(), "designation": set(), "custom_category": set()}))


class TestSpottingRowsTheRuleNoLongerAgreesWith(unittest.TestCase):
	"""count_in_payroll is decided once, when the row is written, and never
	revisited. Change an employee's classification or the lists in Settings and
	every row already recorded keeps the old answer -- silently, at zero. This
	is what nobody had: a way to see that it happened.
	"""

	RULE = {"employment_type": {"Contract"}, "designation": set(), "custom_category": set()}
	PEOPLE = {"400617": {"employment_type": "Contract"},
		"400001": {"employment_type": "Permanent"}}

	def row(self, employee, flag):
		return {"name": f"r-{employee}-{flag}", "employee": employee, "count_in_payroll": flag}

	def test_a_row_left_out_of_payroll_whose_employee_now_qualifies_is_reported(self):
		found = rule.disagreements([self.row("400617", 0)], self.RULE, self.PEOPLE)
		self.assertEqual([r["employee"] for r in found], ["400617"])
		self.assertEqual(found[0]["stored"], 0)
		self.assertEqual(found[0]["expected"], 1)

	def test_a_row_in_payroll_whose_employee_no_longer_qualifies_is_reported(self):
		"""The other direction matters too -- that one is money going out."""
		found = rule.disagreements([self.row("400001", 1)], self.RULE, self.PEOPLE)
		self.assertEqual(found[0]["expected"], 0)

	def test_rows_the_rule_still_agrees_with_are_not_reported(self):
		rows = [self.row("400617", 1), self.row("400001", 0)]
		self.assertEqual(rule.disagreements(rows, self.RULE, self.PEOPLE), [])

	def test_an_employee_the_lookup_does_not_know_is_left_alone(self):
		"""Not guessed at: a deleted employee is a different problem."""
		self.assertEqual(rule.disagreements([self.row("999", 0)], self.RULE, {}), [])
