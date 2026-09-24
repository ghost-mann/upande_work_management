# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""The Worker Task Day report is offered on the screens its readers live on.

It was reachable only by searching the desk, and the people who want it daily
never go there. The client: "Can we have the worker task report right here as
the first one, or like a button to the report."

    FIRST under the Command Centre's activity window, before the analysis cards.
    ON THE WINDOW being looked at: the filters the report has (from_date,
        to_date, farm) are carried when the page has set them, and left out --
        not guessed -- when it has not.
    ONLY FOR SOMEBODY IT WILL OPEN FOR: the screens ask Frappe's own two
        questions (report_access.can_open), never a list of roles.
    AND, smaller, on the Payment screen's Audit tab, where pay questions are
        asked and this report is the answer.

And the dashboard legend stops describing the shipped chain ("FM → HR → GM")
on a site whose chain is something else.

    bench --site <site> run-tests --app work_management \\
        --module work_management.tests.test_the_worker_task_day_report_is_offered
"""

import json
import os
import re
import shutil
import subprocess
import unittest
from unittest import mock

import frappe

from work_management import report_access
from work_management.api import config
from work_management.tests.test_a_note_per_worker_day import js_function
from work_management.tests.test_the_screens_speak_the_configured_chain import (
	SHIPPED_ROLES,
	live_code,
)

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
	with open(os.path.join(APP, *parts), encoding="utf-8") as handle:
		return handle.read()


DASH = read("public", "js", "work-management-dashboard.js")
PAY = read("public", "js", "work-payment.js")


def node(src, expr):
	return subprocess.run(["node", "-e", src + "\nprocess.stdout.write(String(" + expr + "));"],
		capture_output=True, text=True, check=True).stdout


class TestTheDashboardOffersIt(unittest.TestCase):
	def setUp(self):
		self.render = js_function(DASH, "render")

	def test_the_card_is_drawn_only_when_the_report_will_open(self):
		"""Inside the render function, gated on the server's permission answer."""
		self.assertIn("(D.worker_task_day ? wtdCard() : '')", self.render)

	def test_it_is_the_first_thing_under_the_activity_window(self):
		at = self.render.index("(D.worker_task_day ? wtdCard() : '')")
		self.assertLess(self.render.index("Activity across the pipeline"), at)
		self.assertLess(self.render.index('<div class="explain">'), at)
		self.assertLess(at, self.render.index("Planned value &amp; delivery"))
		self.assertLess(at, self.render.index("Trends &amp; analytics"))

	def test_it_says_what_it_answers(self):
		card = js_function(DASH, "wtdCard")
		self.assertIn("Worker × task × day — what each person did, their target, and "
			"their clock times", card)

	def test_it_opens_the_report_in_a_new_tab(self):
		card = js_function(DASH, "wtdCard")
		self.assertIn('target="_blank"', card)
		self.assertIn("wtdUrl(activityWindow())", card)
		self.assertIn('var WTD_ROUTE="/app/query-report/Worker Task Day";', DASH)

	def test_the_link_follows_the_window_after_render(self):
		load = js_function(DASH, "load")
		self.assertLess(load.index("render(D);"), load.index("syncWtd();"))

	def test_the_activity_window_is_wired(self):
		"""Its presets were drawn and never wired; the link reads what they set."""
		self.assertIn("wireActivityWindow();", js_function(DASH, "boot"))

	def test_the_server_answers_with_frappes_own_check(self):
		src = read("api", "dashboard.py")
		at = src.index('elif action == "dash":')
		block = src[at:src.index('elif action == "burndown":', at)]
		self.assertIn('out["worker_task_day"] = report_access.can_open()', block)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestTheUrlCarriesTheWindow(unittest.TestCase):
	def url(self, win):
		src = js_function(DASH, "wtdUrl")
		return node('var WTD_ROUTE="/app/query-report/Worker Task Day";\n' + src,
			"wtdUrl(" + json.dumps(win) + ")")

	def test_date_range_and_farm(self):
		self.assertEqual(self.url({"from": "2026-09-01", "to": "2026-09-24", "farm": "Altura"}),
			"/app/query-report/Worker%20Task%20Day"
			"?from_date=2026-09-01&to_date=2026-09-24&farm=Altura")

	def test_nothing_set_carries_nothing(self):
		"""The report then falls back to its own default -- not a guessed one."""
		self.assertEqual(self.url({}), "/app/query-report/Worker%20Task%20Day")

	def test_an_unset_farm_is_left_out(self):
		out = self.url({"from": "2026-09-01", "to": "2026-09-24"})
		self.assertNotIn("farm=", out)
		self.assertIn("from_date=2026-09-01&to_date=2026-09-24", out)

	def test_a_farm_is_encoded(self):
		self.assertIn("farm=KenTrout%20Farm", self.url({"farm": "KenTrout Farm"}))


class TestThePaymentAuditOffersIt(unittest.TestCase):
	def setUp(self):
		self.html = read("www", "work-payment.html")

	def test_the_link_sits_in_the_audit_toolbar_hidden_until_allowed(self):
		at = self.html.index('id="p-audit"')
		panel = self.html[at:self.html.index('id="au-farmchips"', at)]
		self.assertIn('id="au-wtd" target="_blank"', panel)
		self.assertIn('style="display:none', panel[panel.index('id="au-wtd"'):])

	def test_it_is_shown_on_the_servers_answer(self):
		block = js_function(PAY, "loadAudit")
		self.assertIn('wtd.style.display=d.worker_task_day?"":"none"', block)

	def test_the_server_answers_with_frappes_own_check(self):
		src = read("api", "payment.py")
		at = src.index('elif action == "pay_audit":')
		self.assertIn('out["worker_task_day"] = report_access.can_open()', src[at:at + 8000])

	@unittest.skipUnless(shutil.which("node"), "node is not installed")
	def test_one_farm_chip_is_carried_several_are_not(self):
		src = js_function(PAY, "auWtdUrl")
		stub = ('var V={"au-from":{value:"2026-09-01"},"au-to":{value:"2026-09-24"}};'
			"function el(i){return V[i];} var AU={farms:%s};\n")
		one = node(stub % '{"Altura":1}' + src, "auWtdUrl()")
		two = node(stub % '{"Altura":1,"Kitale":1}' + src, "auWtdUrl()")
		self.assertIn("from_date=2026-09-01&to_date=2026-09-24&farm=Altura", one)
		self.assertNotIn("farm=", two)


class TestCanOpenAsksFrappe(unittest.TestCase):
	"""The two checks frappe.desk.query_report makes before running it."""

	def check(self, exists=True, permitted=True, report_perm=True, disabled=0):
		doc = mock.Mock(disabled=disabled, ref_doctype="Work Management Actuals")
		doc.is_permitted.return_value = permitted
		db = mock.MagicMock()
		db.exists.return_value = exists
		# Swapped and put back by hand: mock.patch.object on werkzeug's Local
		# thinks `db` is not its own attribute and DELETES it on exit, which
		# leaves every later test in a site run with frappe.db = None.
		saved = getattr(frappe.local, "db", None)
		frappe.local.db = db
		try:
			with mock.patch.object(frappe, "get_cached_doc", return_value=doc), \
					mock.patch.object(frappe, "has_permission", return_value=report_perm) as perm:
				out = report_access.can_open()
		finally:
			frappe.local.db = saved
		return out, perm

	def test_both_yes_is_yes(self):
		out, perm = self.check()
		self.assertTrue(out)
		perm.assert_called_once_with("Work Management Actuals", "report")

	def test_not_in_the_reports_roles(self):
		self.assertFalse(self.check(permitted=False)[0])

	def test_no_report_permission_on_its_doctype(self):
		self.assertFalse(self.check(report_perm=False)[0])

	def test_a_disabled_report(self):
		self.assertFalse(self.check(disabled=1)[0])

	def test_no_report_at_all(self):
		self.assertFalse(self.check(exists=False)[0])

	def test_it_never_names_a_role(self):
		src = read("report_access.py")
		body = src[src.index("def can_open("):src.index("def after_migrate(")]
		code = re.sub(r'""".*?"""', "", body, flags=re.S)
		self.assertNotIn("get_roles", code)
		for role in SHIPPED_ROLES:
			self.assertNotIn(role, code)


class TestTheLegendSpeaksTheConfiguredChain(unittest.TestCase):
	def explain_blocks(self):
		src = live_code("work-management-dashboard.js")
		out, at = [], 0
		while True:
			at = src.find('class="explain"', at)
			if at < 0:
				return out
			end = src.find("'</div>'", at)
			out.append(src[at:end])
			at = end

	def test_no_legend_names_a_shipped_role(self):
		blocks = self.explain_blocks()
		self.assertTrue(blocks)
		for block in blocks:
			for role in SHIPPED_ROLES:
				self.assertNotIn(role, block)

	def test_no_legend_names_one_by_its_initials(self):
		"""`FM → HR → GM` slipped past the role-name check by being initials."""
		for block in self.explain_blocks():
			self.assertEqual(re.findall(r"\b(FM|HR|GM|HOD)\b", block), [], block[:120])

	def test_the_confirmed_line_reads_the_chain(self):
		render = js_function(DASH, "render")
		at = render.index("<b>Confirmed</b>")
		self.assertIn("signoffPath(DT_ACT)", render[at:at + 200])

	@unittest.skipUnless(shutil.which("node"), "node is not installed")
	def test_the_path_is_the_step_names_without_their_prefix(self):
		src = js_function(DASH, "signoffPath")
		out = node('var CHAIN={signoff:{"A":["Work done: Supervisor","Work done: Manager"]}};\n'
			+ src, 'signoffPath("A")')
		self.assertEqual(out, "Supervisor → Manager")

	def test_the_page_is_given_only_the_steps_that_are_on(self):
		rows = [
			{"document_type": "A", "kind": "Submit", "on": 1, "label": "Work done: Record"},
			{"document_type": "A", "kind": "Approval", "on": 1, "label": "Work done: Supervisor"},
			{"document_type": "A", "kind": "Approval", "on": 0, "label": "Work done: People"},
			{"document_type": "A", "kind": "Approval", "on": 1, "label": "Work done: Manager"},
		]
		self.assertEqual(config.screen_chain({"stage_rows": rows})["signoff"],
			{"A": ["Work done: Supervisor", "Work done: Manager"]})


if __name__ == "__main__":
	unittest.main()
