"""A farm with no cost project must say where to set one.

`no project is mapped for farm: Lokitela` is true and useless. It sent someone to
ask a developer instead of opening Settings, which is the only evidence a message
needs that it has failed.

Every other refusal in this app names the fix -- "Plan within those dates, or
widen the master plan's period to cover them", "add an approver, or leave one
approver's Farm empty to cover every farm". This one did not, so it is held to
the same standard here.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_cost_project_message -v

Reads the generated api module, because the message lives in the mirror script
that module is ported from.
"""

import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ported(module):
    with open(os.path.join(HERE, "api", module + ".py")) as handle:
        return handle.read()


class TestTheMessageNamesTheFix(unittest.TestCase):
    def setUp(self):
        src = ported("masterplan")
        marker = "pt_farm"
        start = src.index(marker)
        self.block = src[start:start + 2200]

    def test_it_still_names_the_farm(self):
        """Which farm is the first thing the reader needs."""
        self.assertIn("str(pt_farm)", self.block)

    def test_it_says_where_a_cost_project_is_set(self):
        """The whole point: the reader can act without asking anyone."""
        self.assertIn("Work Management Settings", self.block)

    def test_it_names_the_table_within_settings(self):
        """Settings has eleven sections; naming the page is not enough."""
        self.assertIn("Farms", self.block)

    def test_it_says_what_the_cost_project_is_for(self):
        """Otherwise it reads as a demand rather than an explanation."""
        self.assertIn("task", self.block.lower())

    def test_the_bare_old_wording_is_gone(self):
        self.assertNotIn("no project is mapped for farm: ", ported("masterplan"))
