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

	def test_crew_button_starts_at_an_open_worker(self):
		# "Enter work for N" must not land on a worker who already has a reason
		i = JS.index("function renderMissing(")
		body = JS[i:JS.index("function wireMissing(", i)]
		self.assertIn("firstOpen.employee", body)
		self.assertNotIn("g.rows[0].employee", body)

	def test_picker_offers_only_assignments_that_take_entries(self):
		i = JS.index("function renderMissing(")
		body = JS[i:JS.index("function wireMissing(", i)]
		self.assertIn("(d.assignments||[])", body)
		self.assertNotIn("ST.asgList", body)

	def test_no_second_load_for_the_farm(self):
		i = JS.index("function loadMissing(")
		self.assertNotIn("r.farm!==MW.farm", JS[i:JS.index("function renderMissing(")])
		self.assertIn("MW.farm=d.farm||", JS[i:JS.index("function renderMissing(")])

	def test_reasons_come_from_the_server(self):
		self.assertIn("d.reasons", JS)

	def test_other_needs_a_note_in_the_browser_too(self):
		self.assertIn('reason==="Other"', JS)

	def test_server_strings_escaped(self):
		i = JS.index("function renderMissing(")
		body = JS[i:JS.index("function wireMissing(", i)]
		self.assertIn("esc(r.employee_name", body)
		self.assertIn("esc(taskName(c.task_name))", body)


if __name__ == "__main__":
	unittest.main()


class TestFriendlyLayout(unittest.TestCase):
	"""2026-11-23: the tab redone to be easier to read and use (james@)."""

	def setUp(self):
		i = JS.index("function loadMissing(")
		self.ui = JS[i:JS.index("function deepLink(")]

	def test_styles_injected_once(self):
		self.assertIn('id="mw-style"', JS.replace("st.id=\"mw-style\"", 'id="mw-style"'))

	def test_farm_buttons_with_counts(self):
		self.assertIn("data-mw-farm", self.ui)
		self.assertIn("d.farm_counts", self.ui)

	def test_summary_card_says_what_is_waiting(self):
		self.assertIn("mw-sum", self.ui)
		self.assertIn("d.open_check", self.ui)

	def test_days_open_and_close(self):
		self.assertIn('<details class="mw-day"', self.ui)

	def test_friendly_dates(self):
		self.assertIn("function mwDay(", JS)

	def test_reason_buttons_on_the_row(self):
		self.assertIn("data-mw-reason", self.ui)
		self.assertNotIn('id="mw-reason"', self.ui)

	def test_bulk_bar_for_ticked_workers(self):
		self.assertIn('id="mw-bulk"', self.ui)

	def test_friendly_all_clear(self):
		self.assertIn("Nothing to clear", self.ui)
