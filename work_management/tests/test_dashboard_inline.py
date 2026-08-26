"""The dashboard's inlined section helpers must agree with sections.py.

A Server Script has no __import__, so the live dashboard cannot import
work_management.sections. The helpers are therefore inlined in the mirror
script that both the live copy and api/dashboard.py are generated from -- which
buys identical behaviour in both worlds at the price of a second copy of the
arithmetic. This is the guard on that price: it lifts the inlined code out of
the shipped module and runs it against the same fixtures as the original.

    ./env/bin/python -m unittest work_management.tests.test_dashboard_inline -v
"""

import inspect
import textwrap
import unittest

from work_management import sections
from work_management.api import dashboard


def _inlined():
	"""The inlined helpers, lifted out of the shipped dashboard module and
	executed on their own so the real code is what gets tested."""
	lines = inspect.getsource(dashboard.wm_dashboard).splitlines(True)
	first = next(i for i, l in enumerate(lines) if "WMSEC_UNASSIGNED =" in l)
	last = next(i for i, l in enumerate(lines)
		if 'action = frappe.form_dict.get("action")' in l)
	# whole lines, then dedent: the port indents the entire body by four spaces
	block = textwrap.dedent("".join(lines[first:last]))
	namespace = {"frappe": None}
	exec(compile(block, "<inlined>", "exec"), namespace)
	return namespace


class TestTheInlinedCopyStillAgrees(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.ns = _inlined()

	MAPPING = {"A1": "BLOCK A", "A2": "BLOCK A", "B7": "BLOCK B"}
	ROWS = [
		{"block": "A1", "farm": "Saboti", "labour_spend": 100.0, "gl_spend": 200.0,
		 "qty": 10.0, "worker_days": 8.0, "trend": [{"w": "2026-08-03", "pay": 60.0}]},
		{"block": "A2", "farm": "Saboti", "labour_spend": 50.0, "gl_spend": 0.0,
		 "qty": 5.0, "worker_days": 2.0, "trend": [{"w": "2026-08-03", "pay": 40.0}]},
		{"block": "Z9", "farm": "Vale", "labour_spend": 25.0, "gl_spend": 10.0,
		 "qty": 2.0, "worker_days": 2.0, "trend": []},
	]

	def test_the_unassigned_sentinel_is_the_same_string(self):
		self.assertEqual(self.ns["WMSEC_UNASSIGNED"], sections.UNASSIGNED)

	def test_the_rollup_produces_the_same_buckets(self):
		mine = self.ns["wmsec_roll_up"](self.ROWS, self.MAPPING)
		theirs = sections.roll_up(self.ROWS, self.MAPPING)
		self.assertEqual([r["key"] for r in mine], [r["key"] for r in theirs])
		for a, b in zip(mine, theirs):
			for field in ("blocks", "labour_spend", "gl_spend", "qty", "worker_days",
					"farm", "cost_per_unit", "cost_per_wd", "labour_share", "trend"):
				self.assertEqual(a[field], b[field], f"{a['key']}.{field}")

	def test_the_drill_down_condition_is_the_same(self):
		for key in ("BLOCK A", "BLOCK B", sections.UNASSIGNED):
			self.assertEqual(
				self.ns["wmsec_group_condition"]("ac.block_section", key, self.MAPPING),
				sections.group_condition("ac.block_section", key, self.MAPPING), key)

	def test_the_edge_cases_agree_too(self):
		"""A section holding nothing, and a site with no sections at all."""
		self.assertEqual(
			self.ns["wmsec_group_condition"]("ac.block_section", "BLOCK A", {}),
			sections.group_condition("ac.block_section", "BLOCK A", {}))
		self.assertEqual(
			self.ns["wmsec_group_condition"]("ac.block_section", sections.UNASSIGNED, {}),
			sections.group_condition("ac.block_section", sections.UNASSIGNED, {}))

	def test_the_block_list_is_the_same(self):
		for key in ("BLOCK A", sections.UNASSIGNED):
			self.assertEqual(self.ns["wmsec_blocks_of"](key, self.MAPPING),
				sections.blocks_of(key, self.MAPPING), key)

	def test_an_empty_input_agrees(self):
		self.assertEqual(self.ns["wmsec_roll_up"]([], {}), sections.roll_up([], {}))
