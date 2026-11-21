"""Activity portions are wired through the master plan, the planner and the KPIs.

The sandbox scripts cannot import work_management/portions.py, so they inline
its rules. These tests hold the scripts to the places the rules must be applied.
"""

import os
import re
import unittest

from work_management.tests import mirror

API = os.path.join(os.path.dirname(os.path.dirname(__file__)), "api")


def src(name):
	with open(os.path.join(mirror.SERVER_SCRIPTS, name)) as f:
		return f.read()


def action_block(text, action):
	"""The body of `elif action == "<action>":` up to the next top-level action."""
	m = re.search(r'\n(el)?if action == "' + re.escape(action) + r'"[^\n]*:\n', text)
	if not m:
		return ""
	rest = text[m.end():]
	n = re.search(r'\n(el)?if action == "', rest)
	return rest[: n.start()] if n else rest


@unittest.skipUnless(mirror.present(), "mirror not checked out")
class MasterPlan(unittest.TestCase):
	def setUp(self):
		self.s = src("wm_masterplan.py")

	def test_set_portions_exists_and_is_a_guarded_write(self):
		self.assertTrue(action_block(self.s, "set_portions"))
		self.assertRegex(self.s, r'WMG_WRITES = \{[^}]*"set_portions": ""')

	def test_every_step_forward_checks_the_portions_add_up(self):
		for a in ("submit_for_review", "send_to_gm", "gm_approve", "plans_bulk", "decide_line", "decide_bulk"):
			self.assertIn("MP_PORTIONS_OVER_SQL", action_block(self.s, a), a)

	def test_get_returns_the_portions(self):
		g = action_block(self.s, "get")
		for k in ('out["portions"]', 'out["portion_changes"]', 'out["can_set_portions"]'):
			self.assertIn(k, g)

	def test_set_leaders_restamps_portion_work_with_the_portion_leader(self):
		self.assertIn("portion", action_block(self.s, "set_leaders"))

	def test_save_keeps_portions_in_step_with_the_lines(self):
		sv = action_block(self.s, "save")
		self.assertIn('d.get("portions")', sv)
		self.assertIn("cannot be removed", sv)

	def test_approved_changes_are_logged(self):
		self.assertIn('"portion_changes"', action_block(self.s, "set_portions"))


@unittest.skipUnless(mirror.present(), "mirror not checked out")
class Planner(unittest.TestCase):
	def setUp(self):
		self.s = src("wm_planner.py")

	def test_save_takes_and_caps_a_portion(self):
		sv = action_block(self.s, "submit")
		self.assertIn('frappe.form_dict.get("portion")', sv)
		self.assertIn("is split between team leaders", sv)
		self.assertIn("d.portion", sv)

	def test_the_task_list_offers_portions(self):
		self.assertIn('"portions"', action_block(self.s, "tasks"))


@unittest.skipUnless(mirror.present(), "mirror not checked out")
class Kpis(unittest.TestCase):
	def test_tl_kpis_credits_portion_leaders(self):
		self.assertIn("Work Management Activity Portion", action_block(src("wm_dashboard.py"), "tl_kpis"))


@unittest.skipUnless(mirror.present(), "mirror not checked out")
class Screen(unittest.TestCase):
	def setUp(self):
		with open(os.path.join(mirror.WEB_PAGES, "work-planner.js")) as f:
			self.js = f.read()

	def test_the_master_plan_screen_saves_portions(self):
		self.assertIn('action:"set_portions"', self.js)

	def test_the_request_form_sends_the_portion(self):
		self.assertRegex(self.js, r'portion:\s*[A-Za-z_.]+')


@unittest.skipUnless(mirror.present(), "mirror not checked out")
class ReservedWord(unittest.TestCase):
	"""PORTION is a MariaDB keyword (FOR PORTION OF): the column must be quoted in SQL."""

	def test_every_query_quotes_the_portion_column(self):
		bad = []
		for name in sorted(os.listdir(mirror.SERVER_SCRIPTS)):
			if not name.endswith(".py"):
				continue
			for q in re.findall(r'"""(.*?)"""', src(name), re.S):
				if not re.search(r"\b(SELECT|UPDATE|WHERE)\b", q):
					continue
				for m in re.finditer(r"(?<![`\w])portion(?![`\w])", q):
					bad.append(name + ": ..." + q[max(0, m.start() - 30): m.end() + 10].strip() + "...")
		self.assertEqual(bad, [])
