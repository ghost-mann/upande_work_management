# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Guards on the desk surfaces the app ships.

The workspace, the v16 sidebar and the apps-screen entry are static JSON and a
hooks entry, so nothing fails loudly when a doctype is renamed out from under
them — the link just stops working. These tests read the app's own doctype
folders and check every link still points at something real.

No site and no database needed::

    ./env/bin/python -m unittest work_management.tests.test_desk_artifacts -v
"""

import json
import os
import re
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(APP)

WORKSPACE = os.path.join(
	APP, "work_management", "workspace", "work_management", "work_management.json"
)
SIDEBAR = os.path.join(APP, "workspace_sidebar", "work_management.json")
HOOKS = os.path.join(APP, "hooks.py")

# Core doctypes the desk surfaces are allowed to link. Task earns its place:
# the Task list is where rates are edited day to day.
CORE_DOCTYPES = {"Task"}

# The five screens are www routes, not desk pages, so they can only be reached
# by URL. Anything claiming to be one of these must match a real .html file.
SCREENS = {
	"/work-management", "/work-planner", "/work-assigner", "/work-actuals", "/work-payment",
}


def app_doctypes():
	"""Every doctype this app defines, and whether it is a child table."""
	found = {}
	root = os.path.join(APP, "work_management", "doctype")
	for entry in os.listdir(root):
		path = os.path.join(root, entry, f"{entry}.json")
		if not os.path.exists(path):
			continue
		with open(path) as handle:
			doc = json.load(handle)
		found[doc["name"]] = bool(doc.get("istable"))
	return found


def load(path):
	with open(path) as handle:
		return json.load(handle)


class TestWorkspace(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.workspace = load(WORKSPACE)
		cls.doctypes = app_doctypes()

	def test_it_is_a_standard_public_workspace_for_this_module(self):
		self.assertEqual(self.workspace["module"], "Work Management")
		self.assertEqual(self.workspace["app"], "work_management")
		self.assertEqual(self.workspace["public"], 1)

	def test_every_doctype_link_names_a_doctype_the_app_defines(self):
		for link in self.workspace["links"]:
			if link["type"] != "Link" or link["link_type"] != "DocType":
				continue
			self.assertIn(link["link_to"], set(self.doctypes) | CORE_DOCTYPES, link["label"])

	def test_no_child_table_is_linked(self):
		"""A child table has no list view, so a link to one goes nowhere."""
		for link in self.workspace["links"]:
			if link["type"] != "Link" or link["link_type"] != "DocType":
				continue
			self.assertFalse(
				self.doctypes.get(link["link_to"], False),
				f"{link['link_to']} is a child table and cannot be linked",
			)

	def test_every_linkable_doctype_appears_somewhere(self):
		"""The whole point of the cards: nothing the app defines is unreachable."""
		linked = {
			link["link_to"] for link in self.workspace["links"]
			if link["type"] == "Link" and link["link_type"] == "DocType"
		}
		linkable = {name for name, is_child in self.doctypes.items() if not is_child}
		self.assertEqual(linkable - linked, set(), "not reachable from the workspace")

	def test_card_breaks_count_the_links_that_follow_them(self):
		counts, current = {}, None
		for link in self.workspace["links"]:
			if link["type"] == "Card Break":
				current = link["label"]
				counts[current] = [link["link_count"], 0]
			else:
				counts[current][1] += 1
		for card, (declared, actual) in counts.items():
			self.assertEqual(declared, actual, f"{card}: link_count is wrong")

	def test_content_blocks_reference_cards_and_shortcuts_that_exist(self):
		content = json.loads(self.workspace["content"])
		cards = {
			link["label"] for link in self.workspace["links"] if link["type"] == "Card Break"
		}
		shortcuts = {row["label"] for row in self.workspace["shortcuts"]}
		for block in content:
			if block["type"] == "card":
				self.assertIn(block["data"]["card_name"], cards)
			elif block["type"] == "shortcut":
				self.assertIn(block["data"]["shortcut_name"], shortcuts)

	def test_every_card_and_shortcut_is_placed_in_the_content(self):
		content = json.loads(self.workspace["content"])
		placed_cards = {b["data"]["card_name"] for b in content if b["type"] == "card"}
		placed_shortcuts = {b["data"]["shortcut_name"] for b in content if b["type"] == "shortcut"}
		cards = {
			link["label"] for link in self.workspace["links"] if link["type"] == "Card Break"
		}
		shortcuts = {row["label"] for row in self.workspace["shortcuts"]}
		self.assertEqual(cards - placed_cards, set(), "card defined but never shown")
		self.assertEqual(shortcuts - placed_shortcuts, set(), "shortcut defined but never shown")

	def test_content_block_ids_are_unique(self):
		ids = [block["id"] for block in json.loads(self.workspace["content"])]
		self.assertEqual(len(ids), len(set(ids)))

	def test_screen_shortcuts_point_at_pages_that_exist(self):
		for shortcut in self.workspace["shortcuts"]:
			self.assertEqual(shortcut["type"], "URL", shortcut["label"])
			self.assertIn(shortcut["url"], SCREENS, shortcut["label"])
			page = os.path.join(APP, "www", shortcut["url"].lstrip("/") + ".html")
			self.assertTrue(os.path.exists(page), f"{shortcut['url']} has no www template")


class TestSidebar(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.sidebar = load(SIDEBAR)
		cls.doctypes = app_doctypes()

	def test_it_is_a_standard_sidebar_for_this_app(self):
		self.assertEqual(self.sidebar["doctype"], "Workspace Sidebar")
		self.assertEqual(self.sidebar["app"], "work_management")
		self.assertEqual(self.sidebar["module"], "Work Management")
		self.assertEqual(self.sidebar["standard"], 1)

	def test_it_lives_beside_the_package_where_v16_looks_for_it(self):
		"""v16 scans <app>/workspace_sidebar; v15 never looks, so this is inert there."""
		self.assertTrue(SIDEBAR.endswith(os.path.join("workspace_sidebar", "work_management.json")))

	def test_every_doctype_item_names_a_doctype_the_app_defines(self):
		for item in self.sidebar["items"]:
			if item["type"] != "Link" or item["link_type"] != "DocType":
				continue
			self.assertIn(item["link_to"], set(self.doctypes) | CORE_DOCTYPES, item["label"])
			self.assertFalse(
				self.doctypes.get(item["link_to"], False),
				f"{item['link_to']} is a child table",
			)

	def test_url_items_point_at_pages_that_exist(self):
		for item in self.sidebar["items"]:
			if item.get("link_type") != "URL" or item["type"] != "Link":
				continue
			self.assertIn(item["url"], SCREENS, item["label"])

	def test_the_workspace_link_names_this_workspace(self):
		workspace_items = [
			item for item in self.sidebar["items"] if item.get("link_type") == "Workspace"
		]
		self.assertTrue(workspace_items)
		for item in workspace_items:
			self.assertEqual(item["link_to"], load(WORKSPACE)["name"])

	def test_section_breaks_are_followed_by_children(self):
		items = self.sidebar["items"]
		for index, item in enumerate(items):
			if item["type"] != "Section Break":
				continue
			following = items[index + 1 : index + 2]
			self.assertTrue(following, f"{item['label']} is the last item")
			self.assertEqual(following[0]["child"], 1, f"{item['label']} has no children")

	def test_every_item_has_a_label(self):
		for item in self.sidebar["items"]:
			self.assertTrue(item.get("label"), item)


class TestAppsScreen(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		with open(HOOKS) as handle:
			cls.hooks = handle.read()

	def test_the_apps_screen_entry_is_declared(self):
		self.assertIn("add_to_apps_screen", self.hooks)
		self.assertIn('"name": "work_management"', self.hooks)
		self.assertIn('"title": "Work Management"', self.hooks)

	def test_its_route_is_one_of_the_screens(self):
		route = re.search(r'"route": "([^"]+)"', self.hooks).group(1)
		self.assertIn(route, SCREENS)

	def test_its_logo_file_is_shipped(self):
		logo = re.search(r'"logo": "([^"]+)"', self.hooks).group(1)
		prefix = "/assets/work_management/"
		self.assertTrue(logo.startswith(prefix), logo)
		self.assertTrue(
			os.path.exists(os.path.join(APP, "public", logo[len(prefix):])),
			f"{logo} is not in the app",
		)

	def test_its_permission_callback_is_importable(self):
		target = re.search(r'"has_permission": "([^"]+)"', self.hooks).group(1)
		module, _, function = target.rpartition(".")
		path = os.path.join(REPO, *module.split(".")) + ".py"
		self.assertTrue(os.path.exists(path), path)
		with open(path) as handle:
			self.assertIn(f"def {function}(", handle.read())

	def test_the_app_no_longer_carries_a_workflow_fixture(self):
		"""Workflows are generated; a fixture would fight the generator."""
		self.assertNotIn('{"dt": "Workflow",', self.hooks)
		self.assertFalse(os.path.exists(os.path.join(APP, "fixtures", "workflow.json")))


if __name__ == "__main__":
	unittest.main()
