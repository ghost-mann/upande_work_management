"""Asking whether a table exists has to go through table_exists().

`frappe.db.get_tables()` returns raw table names -- `tabWM Farm`, prefix and
all. So a bare doctype name is never a member of it, and

    if OLD_CHILD not in frappe.db.get_tables():
            return

is a guard that returns every single time, on every site. That is what
`merge_farms_in_use_into_farms` shipped with: the patch that carries the
farms-in-use picker into the one farms table could not carry a row anywhere, and
said nothing about it, because returning early is also what it correctly does on
a site that never had the picker. Its own docstring notes the picker's rows are
the only source of the answer and cannot be re-derived once its child doctype is
deleted -- so a silent no-op there loses the answer for good.

`frappe.db.table_exists(doctype)` is the API that adds the prefix, and
`has_table` is its alias. Nothing in this app should reach for the raw list to
answer a question about one doctype.

This is a cheap test for an expensive class of bug: the mistake is invisible at
the call site, it type-checks, it runs, and it silently answers "no".

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_table_existence_checks -v
"""

import ast
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def python_sources():
	"""Every .py file the app ships, as (repo-relative path, source)."""
	out = []
	for root, dirs, names in os.walk(HERE):
		dirs[:] = [d for d in dirs if d not in ("__pycache__", "node_modules", "public")]
		for name in sorted(names):
			if not name.endswith(".py"):
				continue
			path = os.path.join(root, name)
			with open(path) as handle:
				out.append((os.path.relpath(path, HERE), handle.read()))
	return sorted(out)


def is_get_tables_call(node):
	"""True for a call to `<anything>.get_tables(...)`."""
	return (
		isinstance(node, ast.Call)
		and isinstance(node.func, ast.Attribute)
		and node.func.attr == "get_tables"
	)


def membership_tests_against_get_tables(source):
	"""Line numbers where `x in <...>.get_tables()` is used, `not in` included.

	The comparators are what matters: `in` and `not in` are the two ways this
	mistake is written, and `ast.Compare` carries both the same way.
	"""
	found = []
	for node in ast.walk(ast.parse(source)):
		if not isinstance(node, ast.Compare):
			continue
		for op, comparator in zip(node.ops, node.comparators):
			if isinstance(op, (ast.In, ast.NotIn)) and is_get_tables_call(comparator):
				found.append(node.lineno)
	return sorted(set(found))


class TestNobodyAsksTheRawTableList(unittest.TestCase):
	def test_no_shipped_module_tests_membership_of_get_tables(self):
		offenders = []
		for path, source in python_sources():
			for line in membership_tests_against_get_tables(source):
				offenders.append(f"{path}:{line}")
		self.assertEqual(
			offenders,
			[],
			"get_tables() returns prefixed names, so a bare doctype name is never "
			"in it and this guard always fires. Use frappe.db.table_exists(doctype):\n  "
			+ "\n  ".join(offenders),
		)

	def test_the_patch_that_had_this_bug_now_uses_table_exists(self):
		"""Named explicitly, so the fix cannot be quietly reverted."""
		path = os.path.join(
			HERE, "patches", "v1_0", "merge_farms_in_use_into_farms.py"
		)
		with open(path) as handle:
			source = handle.read()
		self.assertIn("frappe.db.table_exists(OLD_CHILD)", source)
		self.assertEqual(membership_tests_against_get_tables(source), [])


class TestTheDetectorItself(unittest.TestCase):
	"""The test above is only worth having if it can actually see the mistake."""

	def test_it_catches_not_in(self):
		self.assertEqual(
			membership_tests_against_get_tables(
				"if OLD not in frappe.db.get_tables():\n\tpass\n"
			),
			[1],
		)

	def test_it_catches_in(self):
		self.assertEqual(
			membership_tests_against_get_tables(
				"if OLD in frappe.db.get_tables():\n\tpass\n"
			),
			[1],
		)

	def test_it_catches_a_cached_local(self):
		self.assertEqual(
			membership_tests_against_get_tables(
				"if OLD in self.db.get_tables(cached=False):\n\tpass\n"
			),
			[1],
		)

	def test_it_leaves_table_exists_alone(self):
		self.assertEqual(
			membership_tests_against_get_tables(
				"if not frappe.db.table_exists(OLD):\n\tpass\n"
			),
			[],
		)

	def test_it_leaves_an_iteration_over_the_list_alone(self):
		"""Walking every table is a fair use of get_tables(); only membership lies."""
		self.assertEqual(
			membership_tests_against_get_tables(
				"for table in frappe.db.get_tables():\n\tprint(table)\n"
			),
			[],
		)
