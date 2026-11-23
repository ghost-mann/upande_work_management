"""Actuals > Missing work: the tab that lists present task workers with no actuals
and clears them (enter the work, add to a crew, or give a reason)."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "public" / "js" / "work-actuals.js").read_text()


class TestTab(unittest.TestCase):
	def test_tab_registered(self):
		self.assertIn('["missing","Missing work"]', JS)
		self.assertIn('"missing"', JS[JS.index("function showTab"):JS.index("function showTab") + 300])

	def test_panel_created_by_the_script(self):
		self.assertIn('id="p-missing"', JS.replace("p.id=\"p-missing\"", 'id="p-missing"'))

	def test_calls_exist(self):
		for s in ('action:"mw_list"', 'action:"mw_excuse"', 'action:"mw_unexcuse"', '"wm_missing_work"',
				'action:"a_add_crew"', "for_check:", "until:", "backdate_reason:"):
			self.assertIn(s, JS)

	def test_deep_link_params(self):
		for p in ('q.get("tab")', 'q.get("assignment")', 'q.get("date")', 'q.get("emp")',
				'q.get("farm")', 'q.get("from")', 'q.get("to")'):
			self.assertIn(p, JS)

	def test_enter_work_focuses_the_cell(self):
		self.assertIn('input[data-emp="', JS)
		self.assertIn("function openEntry(", JS)

	def test_onasg_returns_its_promise(self):
		i = JS.index("function onAsg(")
		self.assertIn("return call({action:\"act_detail\",assignment:ST.asg})", JS[i:i + 1200])

	def test_reasons_come_from_the_server(self):
		self.assertIn("d.reasons", JS)

	def test_other_needs_a_note_in_the_browser_too(self):
		self.assertIn('reason==="Other"', JS)

	def test_server_strings_escaped(self):
		i = JS.index("function renderMissing(")
		body = JS[i:JS.index("\n  }\n", i)]
		self.assertIn("esc(r.employee_name", body)
		self.assertIn("esc(taskName(c.task_name))", body)


if __name__ == "__main__":
	unittest.main()
