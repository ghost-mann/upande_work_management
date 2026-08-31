"""Naming a farm you are not offered does not get you its data.

Narrowing the pickers closes the half of the leak a person sees. It does not
close the half they can type: every one of these screens reads its farm from the
query string, so `?farm=Endebess` from somebody restricted to Saboti was answered
in full even after the picker stopped offering Endebess. A picker cannot defend
an API; only the API can.

So each script refuses a named farm that is not in `FARMS` -- the project's farm
list, already narrowed to the farms this person is permitted wherever the site
has asked for that. One guard per script, ahead of the dispatch, so no action can
be added later that quietly skips it.

Two properties worth being explicit about:

  * a request naming no farm is not refused. That is a request across everything
    the caller may see, and `FARMS` already bounds it -- refusing it would break
    every screen's default view for everybody.
  * a site with no farms configured refuses nothing. `FARMS` is empty there, and
    an empty list means "not configured", not "permitted nothing"; the pickers
    are empty anyway, so there is nothing to defend and a guard that fired would
    just break a fresh install.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_farm_parameter_guard -v
"""

import importlib
import inspect
import textwrap
import unittest

# every ported screen that reads a farm from the request
MODULES = (
	("dashboard", "wm_dashboard"),
	("planner", "wm_planner"),
	("masterplan", "wm_masterplan"),
	("assigner", "wm_assigner"),
	("actuals", "wm_actuals"),
	("payment", "wm_payment"),
)

START = "FARM_ASKED ="
END = "if FARM_DENIED:"


def entrypoint(module_name, function_name):
	module = importlib.import_module("work_management.api." + module_name)
	return getattr(module, function_name)


def guard_source(module_name, function_name):
	lines = inspect.getsource(entrypoint(module_name, function_name)).splitlines(True)
	first = next(i for i, l in enumerate(lines) if START in l)
	last = next(i for i, l in enumerate(lines) if END in l)
	return textwrap.dedent("".join(lines[first:last]))


class FakeFormDict(dict):
	pass


def run_guard(module_name, function_name, farm, farms):
	"""Execute the shipped guard with a given request and farm list."""

	class FakeFrappe:
		form_dict = FakeFormDict({"farm": farm} if farm is not None else {})

	namespace = {"frappe": FakeFrappe, "FARMS": farms}
	exec(compile(guard_source(module_name, function_name), "<guard>", "exec"), namespace)
	return namespace["FARM_DENIED"]


PROJECT_FARMS = ["Saboti", "Lokitela", "Vale", "Endebess"]


class TestEveryScreenCarriesTheGuard(unittest.TestCase):
	def test_the_guard_is_present(self):
		for module_name, function_name in MODULES:
			with self.subTest(module=module_name):
				self.assertIn(START, inspect.getsource(
					entrypoint(module_name, function_name)))

	def test_the_guard_runs_before_any_action(self):
		"""Ahead of the dispatch, so an action added later cannot skip it."""
		for module_name, function_name in MODULES:
			with self.subTest(module=module_name):
				source = inspect.getsource(entrypoint(module_name, function_name))
				guard_at = source.index("FARM_DENIED = ")
				first_branch = source.index("elif action ==")
				self.assertLess(guard_at, first_branch)

	def test_a_refusal_short_circuits_the_dispatch(self):
		"""The guard must be the `if` and the first action the `elif`, or a
		refused request would be answered anyway."""
		for module_name, function_name in MODULES:
			with self.subTest(module=module_name):
				source = inspect.getsource(entrypoint(module_name, function_name))
				self.assertIn("if FARM_DENIED:", source)
				self.assertIn('out["error"] = FARM_DENIED', source)


class TestWhatTheGuardRefuses(unittest.TestCase):
	def check(self, farm, farms, refused):
		for module_name, function_name in MODULES:
			with self.subTest(module=module_name, farm=farm):
				denied = run_guard(module_name, function_name, farm, farms)
				self.assertEqual(bool(denied), refused)

	def test_a_farm_outside_the_list_is_refused(self):
		self.check("Endebess", ["Saboti"], True)

	def test_a_farm_inside_the_list_is_allowed(self):
		self.check("Saboti", ["Saboti"], False)

	def test_every_project_farm_is_allowed_when_nothing_is_narrowed(self):
		for farm in PROJECT_FARMS:
			self.check(farm, PROJECT_FARMS, False)

	def test_naming_no_farm_is_allowed(self):
		"""The default view of every screen. Refusing this would break all of
		them for everybody."""
		self.check(None, ["Saboti"], False)

	def test_an_empty_farm_parameter_is_allowed(self):
		self.check("", ["Saboti"], False)

	def test_whitespace_is_not_a_farm(self):
		self.check("   ", ["Saboti"], False)

	def test_a_site_with_no_farms_configured_refuses_nothing(self):
		"""Empty FARMS means unconfigured, not "permitted nothing". A guard that
		fired here would break a fresh install, where the pickers are empty
		anyway and there is nothing to defend."""
		self.check("Saboti", [], False)

	def test_the_comparison_is_exact(self):
		"""No prefix or case tricks: `sab` must not reach Saboti's data."""
		self.check("sab", ["Saboti"], True)
		self.check("saboti", ["Saboti"], True)
		self.check("Saboti ", ["Saboti"], False)  # trimmed, then matched


class TestTheRefusalSaysWhatToDo(unittest.TestCase):
	def test_it_names_the_farm_that_was_refused(self):
		denied = run_guard("dashboard", "wm_dashboard", "Endebess", ["Saboti"])
		self.assertIn("Endebess", denied)

	def test_it_does_not_leak_the_farms_they_may_not_see(self):
		"""The message must not list the project's other farms -- that would
		hand back exactly the information the guard exists to withhold."""
		denied = run_guard("dashboard", "wm_dashboard", "Kapkolia", PROJECT_FARMS)
		for farm in PROJECT_FARMS:
			self.assertNotIn(farm, denied)

	def test_it_tells_somebody_how_to_fix_it(self):
		"""A person who should have that farm needs to know what to ask for."""
		denied = run_guard("dashboard", "wm_dashboard", "Endebess", ["Saboti"])
		self.assertIn("permitted", denied.lower())

	def test_the_message_is_the_same_on_every_screen(self):
		messages = {run_guard(m, f, "Endebess", ["Saboti"]) for m, f in MODULES}
		self.assertEqual(len(messages), 1, "the six screens disagree: %s" % messages)


if __name__ == "__main__":
	unittest.main()
