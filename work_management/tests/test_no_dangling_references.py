"""Every name this app calls on its own modules must exist.

`taxonomy.apply_business_unit_visibility` was deleted with the farm doctype, and
the call to it in Work Management Settings' on_update was not. Nothing caught it:
no test exercises that controller, and the searches that found the other
references were for the *doctype name*, which that line does not contain. It
reached a person as `AttributeError: module 'work_management.taxonomy' has no
attribute 'apply_business_unit_visibility'` on the Save button.

So this reads the app the way the interpreter would, and fails on a call to
something that is not there -- without a site, and without running the code::

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_no_dangling_references -v

Two shapes are checked, because both have bitten:

  - `module.attribute` in any of the app's own Python, where `module` is one of
    this app's modules imported at the top of that file
  - the dotted paths in hooks.py -- after_install, after_migrate, before_migrate,
    doc_events, scheduler_events, override_whitelisted_methods -- which Frappe
    resolves by string at runtime, so a stale one fails during migrate on a
    customer's site rather than here
"""

import ast
import glob
import importlib
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = "work_management"


def app_sources():
	"""Every Python file this app ships, except the tests themselves."""
	for path in glob.glob(os.path.join(HERE, "**", "*.py"), recursive=True):
		rel = os.path.relpath(path, HERE)
		if rel.startswith("tests" + os.sep):
			continue
		yield rel, path


def imported_app_modules(tree):
	"""{local name: dotted module} for this app's modules imported in one file.

	Covers `from work_management import taxonomy` and
	`from work_management.api import config`, which is how this app imports its
	own modules everywhere. An `import work_management.taxonomy` would not be
	found, and there are none.
	"""
	found = {}
	for node in ast.walk(tree):
		if not isinstance(node, ast.ImportFrom) or not node.module:
			continue
		if node.module != PACKAGE and not node.module.startswith(PACKAGE + "."):
			continue
		for alias in node.names:
			target = f"{node.module}.{alias.name}"
			try:
				importlib.import_module(target)
			except ImportError:
				continue  # a name, not a module -- a function or a constant
			found[alias.asname or alias.name] = target
	return found


class TestEveryCallResolves(unittest.TestCase):
	def test_no_call_names_a_function_its_module_has_not_got(self):
		missing = []
		for rel, path in app_sources():
			with open(path) as handle:
				try:
					tree = ast.parse(handle.read())
				except SyntaxError as exc:
					self.fail(f"{rel} does not parse: {exc}")
			modules = imported_app_modules(tree)
			if not modules:
				continue
			for node in ast.walk(tree):
				if not isinstance(node, ast.Attribute):
					continue
				if not isinstance(node.value, ast.Name):
					continue
				dotted = modules.get(node.value.id)
				if not dotted:
					continue
				module = importlib.import_module(dotted)
				if not hasattr(module, node.attr):
					missing.append(
						f"{rel}:{node.lineno} calls {node.value.id}.{node.attr}(), "
						f"which {dotted} has not got"
					)
		self.assertEqual(missing, [], "\n" + "\n".join(missing))


class TestEveryHookResolves(unittest.TestCase):
	"""Frappe resolves these by string at migrate time, on someone else's site."""

	KEYS = ("after_install", "before_install", "after_migrate", "before_migrate",
		"after_uninstall", "before_uninstall")

	def dotted_paths(self):
		from work_management import hooks

		paths = []
		for key in self.KEYS:
			value = getattr(hooks, key, None)
			if isinstance(value, str):
				paths.append((key, value))
			elif isinstance(value, (list, tuple)):
				paths.extend((key, item) for item in value if isinstance(item, str))
		for key in ("doc_events", "scheduler_events"):
			for outer in (getattr(hooks, key, None) or {}).values():
				if isinstance(outer, dict):
					for item in outer.values():
						if isinstance(item, str):
							paths.append((key, item))
						elif isinstance(item, (list, tuple)):
							paths.extend((key, i) for i in item if isinstance(i, str))
				elif isinstance(outer, (list, tuple)):
					paths.extend((key, i) for i in outer if isinstance(i, str))
		paths.extend(
			("override_whitelisted_methods", value)
			for value in (getattr(hooks, "override_whitelisted_methods", None) or {}).values()
		)
		return paths

	def test_every_hook_path_names_something_that_exists(self):
		missing = []
		for key, dotted in self.dotted_paths():
			if not dotted.startswith(PACKAGE + "."):
				continue
			module_name, _, attr = dotted.rpartition(".")
			try:
				module = importlib.import_module(module_name)
			except ImportError as exc:
				missing.append(f"{key}: {dotted} -- no module {module_name} ({exc})")
				continue
			if not hasattr(module, attr):
				missing.append(f"{key}: {dotted} -- {module_name} has no {attr}")
		self.assertEqual(missing, [], "\n" + "\n".join(missing))

	def test_it_is_actually_looking_at_something(self):
		"""A guard that finds nothing to check is not a guard."""
		self.assertGreater(len(self.dotted_paths()), 10)


class TestRetiredDoctypeLinksAreRepointedEveryMigrate(unittest.TestCase):
	"""A link to a doctype this app retired must be repaired, not left 404ing.

	`move_farms_to_upande_core` deleted the farm doctype. The step that repoints
	the navigation at Upande Core's `Farm` was added to that patch a commit
	later -- and Frappe records a patch by name and never runs it again, so on a
	site that migrated in between, the repointing can never arrive. Its Setup
	workspace keeps a "Farms" link aimed at a doctype that is gone, and clicking
	it is `DocType Work Management Farm not found`.

	So the repair lives in desk.sync(), which runs at every after_migrate and is
	idempotent, and the patch calls the same function rather than carrying a
	second copy of it.
	"""

	def test_the_retired_map_names_the_farm_doctype(self):
		from work_management import desk

		self.assertEqual(desk.RETIRED.get("Work Management Farm"), "Farm")

	def test_a_link_to_a_retired_doctype_is_repointed(self):
		from work_management import desk

		rows = [{"name": "a", "link_to": "Work Management Farm"}]
		self.assertEqual(desk.plan_retired_repoint(rows), [("a", "Farm")])

	def test_a_link_already_pointing_at_the_replacement_is_left_alone(self):
		from work_management import desk

		self.assertEqual(desk.plan_retired_repoint([{"name": "a", "link_to": "Farm"}]), [])

	def test_a_link_to_anything_else_is_left_alone(self):
		from work_management import desk

		rows = [{"name": "a", "link_to": "Work Management Section"}, {"name": "b", "link_to": None}]
		self.assertEqual(desk.plan_retired_repoint(rows), [])

	def test_sync_performs_the_repointing(self):
		"""It has to be in sync(), because that is what after_migrate calls."""
		import inspect

		from work_management import desk

		self.assertIn("repoint_retired_links", inspect.getsource(desk.sync))

	def test_the_patch_delegates_rather_than_carrying_its_own_copy(self):
		source = read_app("patches/v1_0/move_farms_to_upande_core.py")
		self.assertIn("repoint_retired_links", source)

	def test_stale_options_are_dropped_after_the_doctype_goes_not_before(self):
		"""Ordering matters: the check is "does the target still exist?".

		drop_stale_link_options() only deletes an `options` override whose target
		doctype is missing. Called before the delete, the target is still there
		and it does nothing at all -- which is how it was first written.
		"""
		source = read_app("patches/v1_0/move_farms_to_upande_core.py")
		self.assertLess(
			source.index('delete_doc("DocType", OLD'),
			source.index("drop_stale_link_options()"),
		)


def read_app(relpath):
	with open(os.path.join(HERE, relpath)) as handle:
		return handle.read()
