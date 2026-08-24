# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Guards on keeping the desk surfaces attached to this app.

Frappe skips a standard JSON when the record in the database has a `modified`
newer than the one in the file (frappe/modules/import_file.py). A Work
Management workspace built in the desk therefore beats the one this app ships,
and the surviving record keeps its own module and app -- typically Projects and
erpnext. Every desk surface is derived from those two fields:

  * bootinfo.app_data joins Workspace.module to Module Def.app_name, so the app
    ends up with no workspaces and an empty route;
  * create_desktop_icons_from_workspace() files the icon under the wrong app;
  * get_workspaces() raises PermissionError for anyone without the other app's
    module, so the workspace disappears entirely.

The repair decision is pure, so it is tested here without a site::

    ./env/bin/python -m unittest work_management.tests.test_desk_sync -v
"""

import unittest

from work_management import desk


def record(module=desk.MODULE, app=desk.APP):
	return {"name": desk.WORKSPACE, "module": module, "app": app}


class TestWorkspaceRepairDecision(unittest.TestCase):
	def test_a_correctly_attributed_populated_workspace_is_left_alone(self):
		self.assertIsNone(desk.workspace_repair_reason(record(), link_count=10))

	def test_a_missing_workspace_is_repaired(self):
		self.assertEqual(desk.workspace_repair_reason(None, link_count=0), "missing")

	def test_a_workspace_owned_by_another_module_is_repaired(self):
		"""The live site's workspace was built in the desk under Projects."""
		self.assertEqual(
			desk.workspace_repair_reason(record(module="Projects"), link_count=10),
			"module",
		)

	def test_a_workspace_attributed_to_another_app_is_repaired(self):
		self.assertEqual(
			desk.workspace_repair_reason(record(app="erpnext"), link_count=10),
			"app",
		)

	def test_a_workspace_with_no_links_is_repaired(self):
		"""A skipped import leaves the record present but empty."""
		self.assertEqual(desk.workspace_repair_reason(record(), link_count=0), "empty")

	def test_a_blank_app_counts_as_wrong_attribution(self):
		self.assertEqual(desk.workspace_repair_reason(record(app=None), link_count=5), "app")

	def test_a_workspace_missing_cards_the_app_ships_is_resynced(self):
		"""Bumping `modified` in the JSON is easy to forget; this does not rely on it."""
		self.assertEqual(
			desk.workspace_repair_reason(record(), link_count=9, shipped_links=14),
			"stale",
		)

	def test_a_workspace_matching_what_the_app_ships_is_left_alone(self):
		self.assertIsNone(
			desk.workspace_repair_reason(record(), link_count=14, shipped_links=14)
		)

	def test_link_counts_are_only_compared_when_the_shipped_count_is_known(self):
		self.assertIsNone(desk.workspace_repair_reason(record(), link_count=3))

	def test_module_is_checked_before_links(self):
		"""Reporting the most fundamental problem makes the log useful."""
		self.assertEqual(
			desk.workspace_repair_reason(record(module="Projects"), link_count=0),
			"module",
		)


class TestShippedDefinitions(unittest.TestCase):
	def test_the_shipped_workspace_json_is_where_the_repair_looks_for_it(self):
		self.assertTrue(desk.WORKSPACE_JSON.exists(), desk.WORKSPACE_JSON)

	def test_the_shipped_sidebar_json_is_where_the_repair_looks_for_it(self):
		self.assertTrue(desk.SIDEBAR_JSON.exists(), desk.SIDEBAR_JSON)

	def test_the_shipped_workspace_claims_this_module_and_app(self):
		"""If the file itself is mis-attributed, repairing to it fixes nothing."""
		import json

		shipped = json.loads(desk.WORKSPACE_JSON.read_text())
		self.assertEqual(shipped["module"], desk.MODULE)
		self.assertEqual(shipped["app"], desk.APP)
		self.assertEqual(shipped["name"], desk.WORKSPACE)

	def test_the_shipped_workspace_has_links_to_restore(self):
		import json

		shipped = json.loads(desk.WORKSPACE_JSON.read_text())
		self.assertGreater(desk.shipped_link_count(shipped), 0)

	def test_repairing_to_the_shipped_file_settles(self):
		"""A repair that never satisfies its own rule would run on every migrate."""
		import json

		shipped = json.loads(desk.WORKSPACE_JSON.read_text())
		count = desk.shipped_link_count(shipped)
		settled = {
			"name": desk.WORKSPACE,
			"module": shipped["module"],
			"app": shipped["app"],
		}
		self.assertIsNone(
			desk.workspace_repair_reason(settled, link_count=count, shipped_links=count)
		)


if __name__ == "__main__":
	unittest.main()
