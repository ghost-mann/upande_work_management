"""The worker's "Payment runs including this worker" table lists runs, not days.

It listed one row per Work Payment Line. Every column it shows is run-level --
the run name, its title, its payroll_date and its workflow state -- so a run
covering five days produced five rows that were identical on screen, and the one
value that told them apart, the line's own work date, was never displayed.

Reported from live as repetition: WMPAY-03510 appeared five times, each "Sun 30
Aug · 1 day · 387.00". Nothing was wrong with the data. Alfonce Nacholi worked
25, 26, 27, 28 and 29 August, one day each; "Sun 30 Aug" is the run's payroll
date, printed five times.

So the table is grouped by run and the amounts summed. That matches its own
heading, and it matches the "21 payment runs" tile directly above it, which
counts runs while the table was counting lines. Per-day detail is not lost: the
Work & days tab of the same screen is where a day-row belongs.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_a_run_appears_once_per_worker -v
"""

import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def query():
	"""The runs-for-this-worker SQL out of the ported payment module."""
	with open(os.path.join(HERE, "api", "payment.py")) as handle:
		src = handle.read()
	start = src.index("payment runs that include this worker")
	return src[start:src.index("as_dict=True)", start)]


class TestTheRunsTableIsGroupedByRun(unittest.TestCase):
	def setUp(self):
		self.sql = query()

	def test_it_groups_by_the_run(self):
		self.assertRegex(self.sql, r"GROUP\s+BY\s+p\.name",
			"the query still returns one row per payment line:\n" + self.sql)

	def test_the_money_is_summed(self):
		"""Grouping without summing would report one day's pay for the whole run."""
		self.assertRegex(self.sql, r"SUM\(\s*l\.amount\s*\)")

	def test_the_days_are_summed(self):
		self.assertRegex(self.sql, r"SUM\(\s*l\.days\s*\)")

	def test_no_bare_line_column_survives_the_grouping(self):
		"""A non-aggregated l.* column under GROUP BY is one arbitrary line's value,
		which is how this read as five identical rows in the first place."""
		select = self.sql[self.sql.index("SELECT"):self.sql.index("FROM")]
		bare = re.findall(r"(?<!SUM\()\bl\.(\w+)", re.sub(r"SUM\([^)]*\)", "", select))
		self.assertEqual(bare, [], "ungrouped line columns in the SELECT: " + ", ".join(bare))
