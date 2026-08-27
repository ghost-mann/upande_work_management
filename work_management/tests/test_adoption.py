"""Guards on adopting doctypes a site already owns as custom ones.

The decisions are pure and tested without a site::

    ./env/bin/python -m unittest work_management.tests.test_adoption -v
"""

import glob
import json
import os
import unittest

from work_management import install


class TestWhatTheAppShips(unittest.TestCase):
	"""Adoption used to work from a hand-written list of nine names, frozen when
	the app had nine doctypes. It ships twenty-one. The twelve added since --
	Farm, Settings, Section and the rest -- had no adoption path at all, so a
	site owning one of them as a custom doctype kept it, and the app's own
	definition never landed.
	"""

	# The nine the old hand-list carried. None of them may be lost.
	ORIGINAL = [
		"Work Actuals Employee", "Work Assignment Employee", "Work Management Actuals",
		"Work Management Assigner", "Work Management Payment", "Work Management Planner",
		"Work Management Task", "Work Payment Line", "Work Planner Block",
	]
	# Added after the list was frozen; these are what the staleness cost.
	# "Work Management Farm" was one of these until farms became Upande Core's
	# records; it is not listed because the app no longer ships it.
	ADDED_SINCE = [
		"Work Management Section", "Work Management Section Block",
		"Work Management Settings", "Work Management Master Plan",
	]

	def test_the_nine_the_old_list_named_are_still_covered(self):
		shipped = install.shipped_doctypes()
		for name in self.ORIGINAL:
			self.assertIn(name, shipped, name)

	def test_the_doctypes_added_since_are_covered_too(self):
		shipped = install.shipped_doctypes()
		for name in self.ADDED_SINCE:
			self.assertIn(name, shipped, f"{name} would keep a site's custom copy")

	def test_it_reads_the_files_rather_than_a_list_someone_maintains(self):
		"""Every name it returns has a folder of its own on disk."""
		here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
		for name in install.shipped_doctypes():
			folder = os.path.join(here, "work_management", "doctype", install.scrub(name))
			self.assertTrue(os.path.isdir(folder), f"{name} -> {folder}")

	def test_it_covers_every_doctype_json_the_app_ships(self):
		here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
		on_disk = set()
		for path in glob.glob(os.path.join(here, "work_management", "doctype", "*", "*.json")):
			with open(path) as handle:
				doc = json.load(handle)
			if doc.get("doctype") == "DocType":
				on_disk.add(doc["name"])
		self.assertEqual(set(install.shipped_doctypes()), on_disk)

	def test_it_does_not_pick_up_json_that_is_not_a_doctype(self):
		"""The app ships workspaces and a sidebar as JSON too."""
		for name in install.shipped_doctypes():
			self.assertNotIn(name, ("Work Management Setup", "Work Planning", "Work Delivery"))


class TestNothingDisappearsWithoutSaying(unittest.TestCase):
	"""Adopting force-imports the app's definition over the site's own copy. A
	custom doctype keeps every field on the DocType record itself, so a field
	the site added and the app does not define comes off the form. The column
	and its data stay in the table, but a reader has to be told."""

	def test_a_field_the_app_does_not_define_is_reported(self):
		self.assertEqual(
			install.extra_fieldnames(["farm", "block", "site_specific_note"], ["farm", "block"]),
			["site_specific_note"],
		)

	def test_a_definition_that_matches_reports_nothing(self):
		self.assertEqual(install.extra_fieldnames(["farm", "block"], ["farm", "block"]), [])

	def test_fields_the_app_adds_are_not_reported_as_losses(self):
		"""The app defining more than the site is the normal upgrade direction."""
		self.assertEqual(install.extra_fieldnames(["farm"], ["farm", "block", "disabled"]), [])

	def test_the_report_is_ordered_so_two_runs_read_the_same(self):
		self.assertEqual(install.extra_fieldnames(["z", "a", "farm"], ["farm"]), ["a", "z"])


class TestHandingTheModuleDefBackToTheInstaller(unittest.TestCase):
	"""`bench install-app work_management` aborted on any site that already had
	these doctypes as custom ones -- which is every site being migrated:

	    DuplicateEntryError: ('Module Def', 'Work Management')

	Adoption is what puts the module there. Force-importing a doctype whose
	module the site has not got makes Frappe create that module on the spot, and
	adoption runs at before_install; frappe.installer.add_module_defs() then
	inserts the app's module with ignore_if_duplicate=False and the install dies
	half done. A fresh site adopts nothing and so never created the module,
	which is why this only ever bit the migration case.
	"""

	def test_the_installer_gets_it_back_when_adoption_made_it(self):
		self.assertTrue(install.should_release_module_def(True, True))

	def test_a_migrate_never_deletes_the_live_module(self):
		"""after_migrate adopts too, and nothing there is about to recreate the
		module. Deleting it then would strand every doctype pointing at it."""
		self.assertFalse(install.should_release_module_def(True, False))

	def test_nothing_to_hand_back_when_it_was_never_created(self):
		self.assertFalse(install.should_release_module_def(False, True))
		self.assertFalse(install.should_release_module_def(False, False))

	def test_before_install_hands_it_back(self):
		"""The order matters: adopt first (which may create the module), then
		release, then let the installer create it as its own."""
		import inspect
		body = inspect.getsource(install.before_install)
		self.assertIn("adopt_existing_custom_doctypes", body)
		self.assertIn("release_module_def", body)
		self.assertLess(body.index("adopt_existing_custom_doctypes"),
		                body.index("release_module_def"))


class TestPatchesOnASiteThatBroughtItsOwnData(unittest.TestCase):
	"""frappe.installer.install_app() calls set_all_patches_as_completed(), so
	installing this app records every patch as done without running any of them.

	On a genuinely fresh site that is right -- there is no legacy data for a
	patch to fix. On a site being migrated onto, it is exactly backwards: the
	site arrives full of v15 data and the patches written to reconcile it are
	marked applied and skipped. Rehearsed on a 16.27 restore of the live site,
	that left 0 Work Management Farm records for 441 planners and 402 assigners
	whose `farm` link had nothing to point at, and 0 sections.
	"""

	def test_a_site_that_adopted_nothing_is_genuinely_fresh(self):
		self.assertFalse(install.should_run_data_patches([]))

	def test_a_site_that_adopted_doctypes_needs_its_patches_run(self):
		self.assertTrue(install.should_run_data_patches(["Work Management Planner"]))

	def test_the_patch_list_is_read_from_patches_txt(self):
		"""Not a second hand-maintained list. A patch added to patches.txt and
		forgotten here would be skipped on every migration."""
		patches = install.data_patches()
		self.assertIn("work_management.patches.v1_0.backfill_farms_in_use", patches)
		self.assertIn("work_management.patches.v1_0.seed_sections_from_cost_centres", patches)

	def test_it_names_every_patch_the_file_carries(self):
		here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
		with open(os.path.join(here, "patches.txt")) as handle:
			wanted = {l.strip() for l in handle
			          if l.strip() and not l.startswith(("#", "["))}
		self.assertEqual(set(install.data_patches()), wanted)

	def test_every_patch_it_names_is_importable(self):
		import importlib
		for patch in install.data_patches():
			module = importlib.import_module(patch)
			self.assertTrue(hasattr(module, "execute"), patch)


class TestCustomFieldsThatShadowShippedOnes(unittest.TestCase):
	"""A site built in the UI carries Custom Fields for fields this app now
	ships as its own. The Custom Field wins in the meta, so the app's
	definition of that field never takes effect -- silently, for good.

	Found by rehearsing the migration: the app added "Completed" to the plan's
	close-state options, the DocField carried it after migrate, and the meta
	still refused the value because a Custom Field of the same fieldname sat on
	top with the old three. 14 fields were shadowed that way on the restore, 9
	on Planner and 5 on Actuals.

	Deleting the Custom Field costs no data. Both definitions describe the same
	column, Frappe's Custom Field.on_trash does not drop columns, and the
	DocField keeps it regardless.
	"""

	def test_a_custom_field_the_app_also_ships_is_shadowing(self):
		self.assertEqual(
			install.shadowed_custom_fields(["custom_close_state", "site_only_field"],
			                               ["custom_close_state", "farm"]),
			["custom_close_state"])

	def test_a_custom_field_the_app_does_not_ship_is_left_alone(self):
		"""Someone's own extra field is theirs. Only fields this app defines are
		taken back."""
		self.assertEqual(
			install.shadowed_custom_fields(["site_only_field"], ["custom_close_state"]), [])

	def test_nothing_to_do_when_the_site_added_nothing(self):
		self.assertEqual(install.shadowed_custom_fields([], ["farm"]), [])

	def test_it_reports_them_in_a_stable_order(self):
		self.assertEqual(
			install.shadowed_custom_fields(["b", "a", "c"], ["c", "b", "a"]), ["a", "b", "c"])

	def test_the_sweep_runs_on_every_migrate(self):
		"""Adoption skips a doctype it already owns, so a site adopted months ago
		would never revisit these. The sweep has to be its own step."""
		here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
		with open(os.path.join(here, "hooks.py")) as handle:
			hooks = handle.read()
		self.assertIn("work_management.install.drop_shadowing_custom_fields", hooks)
