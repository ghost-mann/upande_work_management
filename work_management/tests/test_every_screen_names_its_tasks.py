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


class TestAServerSuppliedLabelIsStillADocname(unittest.TestCase):
	"""The top-tasks chart printed ids, and the rule above could not see it.

	Every other place names a task by rendering `.task` through `taskName()`, and
	RENDERS_RAW catches the ones that do not. This chart renders neither: the
	dashboard endpoint sends `top_tasks` with a field called `label`, the screen
	passes that key straight to the bar renderer, and nothing in the file ever
	mentions `.task` at all.

	But `label` held `ac.task` -- the docname. A field named for the thing it is
	not is exactly the shape a name-resolution test cannot catch, so "What the
	numbers are doing" went on showing TASK-2026-00103 long after the five
	screens were fixed.

	So the endpoint sends `task`, which is what it is, and the screen resolves it
	the same way as everywhere else. The identity stays server-side; only the
	label moves -- the distinction the module docstring already draws.
	"""

	def endpoint(self):
		from work_management.api import dashboard
		import inspect

		return inspect.getsource(dashboard.wm_dashboard)

	def test_the_endpoint_sends_the_docname_under_its_own_name(self):
		text = self.endpoint()
		block = text[text.index('out["top_tasks"]'):][:220]
		self.assertIn('"task"', block,
			"top_tasks still ships the docname under a label key: " + block.split("\n")[0])

	def test_it_does_not_ship_a_label_it_has_not_resolved(self):
		text = self.endpoint()
		block = text[text.index('out["top_tasks"]'):][:220]
		self.assertNotIn('"label": r.label', block)

	def test_the_chart_resolves_the_name_on_the_screen(self):
		"""taskName() is the one place that knows the map."""
		text = source("work-management-dashboard")
		chart = text[text.index("AN.data.top_tasks"):][:400]
		self.assertIn("taskName(", chart,
			"the top-tasks chart still prints whatever the server called a label")


if __name__ == "__main__":
	unittest.main()


class TestTheMapIsInHandBeforeAnythingRenders(unittest.TestCase):
	"""Having taskName() everywhere is worth nothing if TASK_NAMES is still empty
	when the first list is drawn.

	All four screens fired the task_names call and never waited for it:

	    call({action:"task_names"}, "wm_dashboard").then(...)   // not joined
	    call({action:"a_roles"}).then(function(roles){ initAssign(); ... })

	Two independent requests, no ordering between them, and nothing re-renders
	when the slower one lands. Which arrived first decided whether a row read
	"Coffee picking" or "TASK-2026-00155" -- so the screens looked correct on a
	local bench, where the answer is small and instant, and wrong on the deployed
	site, where the Task table is larger and the map is a bigger payload. It was
	reported as the naming fix simply not working.

	The map is now joined to the call the first render already waits on. The
	screen must still open if task_names fails or drags: the call is caught, so
	a failure resolves rather than rejects, and the wait is capped.
	"""

	# planner folds it into the Promise.all it already had; the other three take
	# a named promise and hang the first render off it.
	JOINED = {
		"work-planner": 'call({action:"task_names"}, "wm_dashboard")',
		"work-assigner": "var names = taskNamesReady();",
		"work-actuals": "var names = taskNamesReady();",
		"work-payment": "var names = taskNamesReady();",
	}

	def screen(self, name):
		with open(os.path.join(JS, name + ".js")) as handle:
			return handle.read()

	def test_no_screen_fires_the_call_and_walks_away(self):
		"""The old shape: the call, then a sibling call that renders, unjoined."""
		for name in self.JOINED:
			with self.subTest(screen=name):
				src = self.screen(name)
				self.assertIn(self.JOINED[name], src)

	def test_the_planner_waits_on_it_with_its_other_two(self):
		src = self.screen("work-planner")
		block = src[src.index("Promise.all([ call({action:\"meta\"})"):][:400]
		self.assertIn("task_names", block,
			"the planner's first render must wait on the map, not race it")

	def test_the_other_three_hang_their_first_render_off_the_map(self):
		"""Waiting takes two shapes here: the assigner and actuals return
		names.then(render) out of their roles handler; payment returns the
		promise itself into the next link of its chain. Either is a wait; what
		must not happen is the render running with the promise ignored."""
		for name, first in (("work-assigner", "initAssign();"),
				("work-actuals", "initEnter(); buildTabs();"),
				("work-payment", 'showTab("build");')):
			with self.subTest(screen=name):
				src = self.screen(name)
				after = src[src.index("var names = taskNamesReady();"):]
				render = after.index(first)
				waits = [w for w in ("names.then(", "return names;")
					if w in after[:render]]
				self.assertTrue(waits,
					name + " builds the map promise and renders without waiting on it")

	def test_a_failed_or_slow_map_still_opens_the_screen(self):
		for name in ("work-assigner", "work-actuals", "work-payment"):
			with self.subTest(screen=name):
				src = self.screen(name)
				helper = src[src.index("function taskNamesReady()"):][:600]
				self.assertIn(".catch(function(){})", helper,
					name + ": a failing task_names must resolve, not reject")
				self.assertIn("Promise.race", helper,
					name + ": a slow task_names must be abandoned, not waited on forever")
				self.assertIn("TASK_NAMES_WAIT", helper)

	def test_the_planners_call_is_still_caught(self):
		src = self.screen("work-planner")
		block = src[src.index("Promise.all([ call({action:\"meta\"})"):][:400]
		self.assertIn(".catch(function(){})", block,
			"a failing task_names must not take the planner's boot down with it")
