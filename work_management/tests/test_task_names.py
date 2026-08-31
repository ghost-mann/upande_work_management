"""Screens show a task's subject, not its docname.

Every screen printed the Task's *docname*. That looked fine for years because of
how tasks happened to be named -- on live the docnames ARE the subjects (`FIELD
IRRIGATION`, `Gryomowing`, `Boundary Slashing: Weeding`), and the older tasks on
the v16 site are the same. But that site's Task autoname is
`TASK-.YYYY.-.#####`, so every task created from now on shows as
`TASK-2026-00031` on the master plan, the dashboard and everywhere else.

The docname was never the right thing to print. `subject` is. Rather than thread
a subject through the eleven places that emit a task -- each of which would need
its own lookup -- one action returns a {docname: subject} map, each screen fetches
it once, and every render resolves through it, falling back to the docname so a
site whose tasks are named by subject is unaffected.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_task_names -v
"""

import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(relpath):
	with open(os.path.join(HERE, relpath)) as handle:
		return handle.read()


class TestTheEndpointOffersTheMap(unittest.TestCase):
	def test_the_dashboard_api_answers_task_names(self):
		self.assertIn('action == "task_names"', read(os.path.join("api", "dashboard.py")))

	def test_it_reads_the_subject_and_keys_by_docname(self):
		source = read(os.path.join("api", "dashboard.py"))
		# generous window: the block leads with a long comment explaining why the
		# map exists at all, and a window that stops inside it tests nothing
		block = source[source.index('action == "task_names"'):][:2500]
		self.assertIn("subject", block)
		self.assertIn('out["task_names"]', block)


class TestTheScreensResolveThroughIt(unittest.TestCase):
	SCREENS = (
		os.path.join("public", "js", "work-management-dashboard.js"),
		os.path.join("public", "js", "work-planner.js"),
	)

	def test_each_screen_defines_the_resolver(self):
		for relpath in self.SCREENS:
			self.assertIn("function taskName(", read(relpath), relpath)

	def test_the_resolver_falls_back_to_the_docname(self):
		"""A site whose tasks are named by subject must look exactly as it did."""
		for relpath in self.SCREENS:
			source = read(relpath)
			block = source[source.index("function taskName("):][:300]
			self.assertRegex(block, r"\|\|\s*\w+", relpath)

	def test_no_render_site_prints_a_bare_task_docname(self):
		"""The forms that were showing IDs. Each must go through taskName()."""
		bare = re.compile(r'esc\((\w+)\.task(?:\s*\|\|\s*"")?\)')
		offenders = []
		for relpath in self.SCREENS:
			for num, line in enumerate(read(relpath).splitlines(), 1):
				if bare.search(line) and "taskName" not in line:
					offenders.append(f"{os.path.basename(relpath)}:{num}")
		self.assertEqual(offenders, [], "\n".join(offenders))

	def test_the_resolver_is_actually_used(self):
		"""A helper nothing calls is how this regresses quietly."""
		for relpath in self.SCREENS:
			self.assertGreater(read(relpath).count("taskName("), 2, relpath)
