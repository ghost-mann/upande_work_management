"""Every screen that prints a task prints what it is called.

`taskName()` was added because a site whose Task autoname is a series hands back
`TASK-2026-00131` from every read, and the subject -- FERTILIZER APPLICATION --
is what a person recognises. On live 238 of the site's tasks are named that way,
and all 85 that the work screens reference need the map.

It went in on two screens. Its commit said five, and the desk follow-up repeated
that: *"taskName() fixed the five web screens."* It had not. `work-actuals.js`,
`work-assigner.js` and `work-payment.js` carried no `taskName` at all -- 18, 14
and 27 raw `.task` references -- so the actuals list, the assigner's plan picker,
every payment table and every CSV export still printed ids. A reader reported it
as work missing from v16.

A claim in a commit message is not coverage. This is coverage: it reads the five
screens and holds each one to the rule, so a sixth screen, or a new table on an
old screen, cannot quietly print an id again.

Three things are deliberately NOT resolved, and the test allows them:

  grouping keys   `kk = (r.task||"") + "|" + ...` keys on the docname because
                  that is the identity; two distinct tasks may share a subject.
  filter values   an `<option>` value stays the docname, since the filter
                  compares it against the row's own `task`. Only the label moves.
  task_kpi        a different field entirely -- the standard, not the task.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_every_screen_names_its_tasks -v
"""

import os
import re
import unittest

JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public", "js")

SCREENS = ("work-management-dashboard", "work-planner", "work-actuals",
	"work-assigner", "work-payment")

# `esc(x.task)`, `esc(x.task||"")`, `esc(x.task||"—")` -- a task rendered into
# markup. `\b` after `task` keeps `task_kpi` and `task_subject` out, since `_` is
# a word character, and requiring the close paren keeps `esc(d.task.subject)` out.
RENDERS_RAW = re.compile(r"""esc\(\s*\w+\.task\b\s*(?:\|\|\s*["'][^"']*["']\s*)?\)""")

# the same, already resolved
RENDERS_NAMED = re.compile(r"esc\(\s*taskName\(")


def source(screen):
	with open(os.path.join(JS, screen + ".js")) as handle:
		return handle.read()


class TestTheScreensAreThere(unittest.TestCase):
	def test_each_screen_file_exists(self):
		for screen in SCREENS:
			with self.subTest(screen=screen):
				self.assertTrue(os.path.exists(os.path.join(JS, screen + ".js")))


class TestNoScreenPrintsATaskId(unittest.TestCase):
	def test_no_task_is_rendered_unresolved(self):
		"""The fault itself: a task rendered straight into markup."""
		offenders = []
		for screen in SCREENS:
			for match in RENDERS_RAW.finditer(source(screen)):
				offenders.append("%s.js: %s" % (screen, match.group(0)))
		self.assertEqual(offenders, [], "\n".join(
			["a task is being printed as its docname, not its subject:"] + offenders))

	def test_every_screen_that_shows_a_task_has_the_helper(self):
		for screen in SCREENS:
			text = source(screen)
			if not RENDERS_NAMED.search(text):
				continue
			with self.subTest(screen=screen):
				self.assertIn("function taskName(", text,
					"%s resolves task names without defining taskName()" % screen)
				self.assertIn("var TASK_NAMES", text,
					"%s defines no TASK_NAMES for taskName() to read" % screen)

	def test_the_helper_falls_back_to_the_docname(self):
		"""A site whose tasks ARE named by subject gets an empty map, and must
		look exactly as it did rather than showing blanks."""
		for screen in SCREENS:
			text = source(screen)
			match = re.search(r"function taskName\(t\)\{([^}]*)\}", text)
			if not match:
				continue
			with self.subTest(screen=screen):
				self.assertIn("|| t ||", match.group(1),
					"%s's taskName() does not fall back to the docname" % screen)


class TestTheMapIsActuallyFetched(unittest.TestCase):
	"""Defining the helper and never filling it would leave every screen showing
	ids while passing every assertion above."""

	def test_each_screen_asks_for_the_map(self):
		for screen in SCREENS:
			text = source(screen)
			if "function taskName(" not in text:
				continue
			with self.subTest(screen=screen):
				self.assertIn('action:"task_names"', text,
					"%s never fetches the task_names map" % screen)
				self.assertIn("wm_dashboard", text,
					"%s must fetch task_names from wm_dashboard, which serves it" % screen)

	def test_the_fetch_cannot_break_the_screen(self):
		"""Unreadable task names are a nuisance; a screen that will not open is
		not. Every fetch of the map carries its own catch."""
		for screen in SCREENS:
			text = source(screen)
			at = text.find('action:"task_names"')
			if at < 0:
				continue
			with self.subTest(screen=screen):
				window = text[at:at + 400]
				self.assertIn(".catch(", window,
					"%s lets a failed task_names fetch reach the screen" % screen)


class TestTheIdentityKeysAreLeftAlone(unittest.TestCase):
	"""The other way to get this wrong: resolving a subject where the docname is
	the identity, which merges two tasks that happen to share a name."""

	def test_grouping_keys_still_key_on_the_docname(self):
		text = source("work-payment")
		keys = re.findall(r'var kk=\([^;]+;', text)
		self.assertTrue(keys, "work-payment.js groups by no key; has it been rewritten?")
		for key in keys:
			with self.subTest(key=key[:48]):
				self.assertNotIn("taskName(", key,
					"a grouping key resolved to the subject -- two tasks sharing a "
					"subject would be merged into one row")

	def test_a_filter_option_keeps_the_docname_as_its_value(self):
		for screen in ("work-actuals", "work-assigner"):
			text = source(screen)
			for match in re.finditer(r"o\.value=([^;]+);\s*o\.textContent=([^;]+);", text):
				value, label = match.group(1), match.group(2)
				if "task" not in (value + label).lower() and "taskName" not in label:
					continue
				with self.subTest(screen=screen):
					self.assertNotIn("taskName(", value,
						"%s sets an option value to the subject; the filter compares "
						"it against the row's task docname" % screen)


class TestTheServerSideStillServesIt(unittest.TestCase):
	def test_the_dashboard_serves_task_names(self):
		from work_management.api import dashboard
		import inspect

		text = inspect.getsource(dashboard.wm_dashboard)
		self.assertIn('action == "task_names"', text)
		self.assertIn('out["task_names"]', text)

	def test_it_drops_rows_that_would_say_nothing(self):
		"""A subject equal to the docname is left out -- the screens fall back to
		the docname anyway, so sending it is pure weight. On a site named by
		subject that empties the map, which is the right answer there."""
		from work_management.api import dashboard
		import inspect

		text = inspect.getsource(dashboard.wm_dashboard)
		self.assertRegex(text, r"tn\.subject\s*!=\s*tn\.name")
		self.assertIn('"is_group": 0', text)


if __name__ == "__main__":
	unittest.main()
