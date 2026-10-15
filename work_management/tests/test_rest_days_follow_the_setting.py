"""A rest day is locked only when "Check weekly offs / holidays" says so.

Live, WMA-01295 (GH-3, Sunday 11 Oct 2026): two workers on "Sunday Week Off
2026" came in on their Sunday, and with `att_block_off` switched OFF their
supervisor still could not key the work. The setting was honoured where the
entry is accepted (act_submit) and nowhere the entry is typed: the grid's
cellActive() returned false on every rest day unconditionally.

Approved leave is a different thing and stays locked whatever this setting says.

    bench --site kentrout.local run-tests --app work_management \\
        --module work_management.tests.test_rest_days_follow_the_setting
"""

import json
import os
import shutil
import subprocess
import unittest

import frappe

from work_management.tests import pipeline

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(APP, "public", "js", "work-actuals.js")


def js_function(src, name):
	at = src.index("  function %s(" % name)
	return src[at:src.index("\n  function ", at + 10)]


class TestTheGridFollowsTheSetting(unittest.TestCase):
	"""cellActive() itself, run under node with the real source."""

	def run_cell(self, block_off, off=(), leave=()):
		node = shutil.which("node") or shutil.which("nodejs")
		if not node:
			self.skipTest("node is not installed")
		with open(JS) as handle:
			src = handle.read()
		body = "\n".join(js_function(src, n) for n in ("offDay", "leaveDay", "offBlocks", "cellActive"))
		script = "var ST={detail:{block_off:%d}};\n%s\nvar w=%s;\nconsole.log(JSON.stringify(%s.map(function(d){ return cellActive(w,d); })));" % (
			block_off, body,
			json.dumps({"employee": "E1", "off_dates": list(off), "leave_dates": list(leave)}),
			json.dumps(["2026-10-10", "2026-10-11", "2026-10-12"]))
		res = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
		self.assertEqual(res.returncode, 0, res.stderr)
		return json.loads(res.stdout)

	def test_a_rest_day_is_editable_with_the_check_off(self):
		self.assertEqual(self.run_cell(0, off=["2026-10-11"]), [True, True, True])

	def test_a_rest_day_is_locked_with_the_check_on(self):
		self.assertEqual(self.run_cell(1, off=["2026-10-11"]), [True, False, True])

	def test_approved_leave_is_locked_either_way(self):
		for flag in (0, 1):
			with self.subTest(block_off=flag):
				self.assertEqual(self.run_cell(flag, leave=["2026-10-12"]), [True, True, False])

	def test_the_server_tells_the_screen(self):
		with open(os.path.join(APP, "api", "actuals.py")) as handle:
			api = handle.read()
		detail = api[api.index('elif action == "act_detail":'):api.index('elif action == "act_submit":')]
		self.assertIn('a["block_off"]', detail)
		self.assertIn('"att_block_off"', detail)


class TestTheEntryIsAcceptedOnARestDay(pipeline.SiteTestCase, unittest.TestCase):
	"""act_detail and act_submit on a site, with a worker whose holiday list has
	the middle day of the plan as a weekly off."""

	def setUp(self):
		super().setUp()
		# only the rest-day check is under test; the others stay out of its way
		self.settings(att_block_absent=0, att_block_leave=0, att_block_noscan_actuals=0, att_block_off=0)
		self.p = pipeline.Pipeline()
		self.off = self.p.days()[1]
		hl = frappe.get_doc({
			"doctype": "Holiday List",
			"holiday_list_name": "WM rest-day test " + frappe.generate_hash(length=6),
			"from_date": frappe.utils.add_days(self.off, -30),
			"to_date": frappe.utils.add_days(self.off, 30),
			"holidays": [{"holiday_date": self.off, "description": "Sunday", "weekly_off": 1}],
		}).insert(ignore_permissions=True)
		self.worker = self.p.workers[0]
		frappe.db.set_value("Employee", self.worker, "holiday_list", hl.name)
		self.p.master_plan()
		self.p.plan()
		self.p.assignment()

	def detail(self):
		out = pipeline.call(self.p.ep.act, action="act_detail", assignment=self.p.asg)
		return out["detail"]

	def test_the_rest_day_is_still_marked(self):
		w = [x for x in self.detail()["workers"] if x["employee"] == self.worker][0]
		self.assertIn(self.off, w["off_dates"])

	def test_with_the_check_off_the_day_is_saved_and_submitted(self):
		self.assertEqual(self.detail()["block_off"], 0)
		out = self.p.actuals(att_override=0)
		self.assertFalse(out.get("needs_att_override"), out.get("att_conflicts"))
		self.assertEqual(self.p.state("Work Management Actuals", self.p.act), "Pending Approval")
		self.assertTrue(frappe.db.exists("Work Actuals Employee",
			{"parent": self.p.act, "employee": self.worker, "work_date": self.off}))

	def test_with_the_check_on_the_day_needs_an_override(self):
		self.settings(att_block_off=1)
		self.assertEqual(self.detail()["block_off"], 1)
		out = self.p.actuals(att_override=0, check=False)
		self.assertTrue(out.get("needs_att_override"))
		reasons = [r for c in out["att_conflicts"] if c["employee"] == self.worker for r in c["reasons"]]
		self.assertIn("off day / holiday on " + self.off, reasons)
