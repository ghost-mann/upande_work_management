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

	def test_deep_link_params(self):
		for p in ('q.get("tab")', 'q.get("assignment")', 'q.get("date")', 'q.get("emp")',
				'q.get("farm")', 'q.get("from")', 'q.get("to")'):
			self.assertIn(p, JS)

	def test_onasg_returns_its_promise(self):
		i = JS.index("function onAsg(")
		self.assertIn("return call({action:\"act_detail\",assignment:ST.asg})", JS[i:i + 1200])

class TestGridAndWaiting(unittest.TestCase):
	"""Part 2 (2026-11-23): To clear is a monthly grid like the dashboard's attendance
	sheet; a cell opens a panel with the fixes; Waiting for approval has the steps."""

	def setUp(self):
		i = JS.index("function loadMissing(")
		self.ui = JS[i:JS.index("function deepLink(")]

	def test_styles_injected_once(self):
		self.assertIn('st.id="mw-style"', JS)

	def test_two_sub_tabs(self):
		self.assertIn('data-mw-view="clear"', self.ui)
		self.assertIn('data-mw-view="wait"', self.ui)
		self.assertIn("Waiting for approval", self.ui)

	def test_grid_from_the_server(self):
		self.assertIn('action:"mw_grid"', self.ui)
		self.assertIn("w.cells", self.ui)
		self.assertIn('<table class="mw-grid"', self.ui)

	def test_legend_lists_every_code(self):
		i = JS.index("var MW_CODES={")
		block = JS[i:JS.index("};", i)]
		for code in ("M", "W", "R", "A", "X", "P", "H", "L", "O", "?"):
			self.assertIn('"' + code + '":[', block, code)
		self.assertIn("Object.keys(MW_CODES)", JS)

	def test_farm_buttons_with_counts(self):
		self.assertIn("data-mw-farm", self.ui)
		self.assertIn("d.farm_counts", self.ui)

	def test_cell_opens_the_panel(self):
		self.assertIn("data-mw-cell", self.ui)
		self.assertIn("function mwOpen(", self.ui)

	def test_enter_quantity_sends_a_missing_day(self):
		self.assertIn("missing_fix:1", self.ui)
		self.assertIn('action:"act_submit"', self.ui)

	def test_ask_hr(self):
		self.assertIn('action:"mw_ask_hr"', self.ui)

	def test_bulk_reasons(self):
		self.assertIn('id="mw-bulk"', self.ui)
		self.assertIn('action:"mw_excuse"', self.ui)

	def test_waiting_actions(self):
		for a in ('"act_fm_approve"', '"act_hr_approve"', '"act_gm_approve"', 'action:"act_reject"',
				'action:"mw_approve"', 'action:"mw_send_back"', 'action:"mw_waiting"'):
			self.assertIn(a, self.ui)

	def test_farm_manager_scores_quality(self):
		self.assertIn("quality_score", self.ui)

	def test_friendly_dates(self):
		self.assertIn("function mwDay(", JS)

	def test_server_strings_escaped(self):
		for s in ("esc(w.name", "esc(x.employee_name", "esc(x.reason", "esc(taskName(c.task_name))"):
			self.assertIn(s, self.ui)

	def test_friendly_all_clear(self):
		self.assertIn("Nothing to clear", self.ui)


if __name__ == "__main__":
	unittest.main()
