# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""The same worker-day cannot be captured twice, or past the day's hours.

30 Oct on Altura, back-filled on 5 Nov: Michael Njoroge Maina paid 3 x 8 h on
one task, five Bed Making workers in WMAC-01956 and WMAC-01972, Simon Ngari
Gichingiri 16 h at 250. Nothing stopped any of it. The rule is
work_management/day_guard.py:

    refused   same employee + date on the same assignment, or the same task and
              block, in another Draft / pending / CONFIRMED document (paid rows
              count); and hour-based rows over Settings' max_hours_per_day
    flagged   more than one day's standard on a date (8 h + 1 bed) -- saved, and
              listed in Payment -> Discrepancies

    bench --site kentrout.local run-tests --app work_management \\
        --module work_management.tests.test_the_same_day_twice
"""

import os
import unittest

import frappe

from work_management import day_guard
from work_management.tests import pipeline
from work_management.tests.pipeline import call

ACT = "Work Management Actuals"
PLAN = "Work Management Planner"
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(APP)


def row(emp, day, qty, **kw):
	r = {"employee": emp, "employee_name": emp, "work_date": day, "qty": qty,
		"assignment": "ASG-1", "task": "T-1", "block": "B-1", "uom": "Nos", "doc": None}
	r.update(kw)
	return r


class TestTheRule(unittest.TestCase):
	"""No site needed: rows in, findings out."""

	D = "2026-10-30"

	def kinds(self, found):
		return sorted(f["kind"] for f in found)

	def test_the_same_assignment_twice_is_refused_and_names_the_other(self):
		found = day_guard.conflicts([row("E1", self.D, 1)],
			[row("E1", self.D, 1, doc="WMAC-01956", state="CONFIRMED")])
		self.assertEqual(self.kinds(found), ["duplicate"])
		self.assertIn("WMAC-01956", found[0]["message"])
		self.assertIn("same assignment", found[0]["message"])

	def test_the_same_task_and_block_on_another_assignment_is_refused(self):
		found = day_guard.conflicts([row("E1", self.D, 1, assignment="ASG-2")],
			[row("E1", self.D, 1, doc="WMAC-01956", state="Pending Approval")])
		self.assertEqual(self.kinds(found), ["duplicate"])
		self.assertIn("same task and block", found[0]["message"])

	def test_a_paid_row_counts(self):
		found = day_guard.conflicts([row("E1", self.D, 1)],
			[row("E1", self.D, 1, doc="WMAC-1", state="CONFIRMED", paid=1)])
		self.assertIn("paid", found[0]["message"])

	def test_another_block_of_the_same_task_is_not_a_duplicate(self):
		self.assertEqual(day_guard.conflicts([row("E1", self.D, 1, assignment="ASG-2")],
			[row("E1", self.D, 1, block="B-2", doc="WMAC-1")]), [])

	def test_another_date_or_worker_is_not_a_duplicate(self):
		self.assertEqual(day_guard.conflicts([row("E1", self.D, 1)],
			[row("E1", "2026-10-31", 1, doc="X"), row("E2", self.D, 1, doc="Y")]), [])

	def test_twice_inside_one_document_is_refused(self):
		found = day_guard.conflicts([row("E1", self.D, 1), row("E1", self.D, 2)], [])
		self.assertEqual(self.kinds(found), ["duplicate"])

	def test_zero_quantities_are_ignored(self):
		self.assertEqual(day_guard.conflicts([row("E1", self.D, 0)],
			[row("E1", self.D, 1, doc="X")]), [])

	def test_three_eights_on_one_date_is_refused(self):
		h = dict(uom="Hours", task="T-38")
		others = [row("E1", self.D, 8, doc="WMAC-01962", assignment="A1", block="B1", **h),
			row("E1", self.D, 8, doc="WMAC-01963", assignment="A2", block="B2", **h)]
		found = day_guard.conflicts([row("E1", self.D, 8, assignment="A3", block="B3", **h)],
			others, 8)
		self.assertEqual(self.kinds(found), ["hours"])
		self.assertIn("24", found[0]["message"])
		self.assertIn("WMAC-01962", found[0]["message"])

	def test_four_and_four_passes(self):
		h = dict(uom="Hour")
		self.assertEqual(day_guard.conflicts([row("E1", self.D, 4, assignment="A2", block="B2", **h)],
			[row("E1", self.D, 4, doc="X", **h)], 8), [])

	def test_the_ceiling_is_the_setting(self):
		h = dict(uom="hrs")
		new = [row("E1", self.D, 6, assignment="A2", block="B2", **h)]
		other = [row("E1", self.D, 4, doc="X", **h)]
		self.assertEqual(day_guard.conflicts(new, other, 10), [])
		self.assertEqual(self.kinds(day_guard.conflicts(new, other, 8)), ["hours"])

	def test_eight_hours_and_a_bed_passes_and_is_one_standard_too_many(self):
		new = [row("E1", self.D, 1, uom="Bed", task="T-30", daily_target=1)]
		other = [row("E1", self.D, 8, uom="Hours", task="T-38", block="B9", assignment="A9",
			daily_target=8, doc="X")]
		self.assertEqual(day_guard.conflicts(new, other, 8), [])
		share = day_guard.standard_share(new + other)
		self.assertAlmostEqual(share[("E1", self.D)], 2.0)
		self.assertTrue(day_guard.over_one_standard(share[("E1", self.D)]))

	def test_a_split_day_is_one_standard(self):
		rows = [row("E1", self.D, 4, daily_target=8), row("E1", self.D, 0.5, daily_target=1)]
		self.assertFalse(day_guard.over_one_standard(day_guard.standard_share(rows)[("E1", self.D)]))


class TestItIsWiredEverywhere(unittest.TestCase):
	"""Source checks: every path that writes rows or confirms them asks."""

	def src(self, *parts):
		with open(os.path.join(APP, *parts)) as f:
			return f.read()

	def test_the_controller_runs_it(self):
		self.assertIn("day_guard.validate(self)", self.src(
			"work_management", "doctype", "work_management_actuals", "work_management_actuals.py"))

	def test_submit_approve_and_close_ask_it(self):
		src = self.src("api", "actuals.py")
		self.assertIn("day_guard.check(dg_ctx, dg_cells)", src)
		self.assertGreaterEqual(src.count("day_guard.refusal_for_document("), 2)
		self.assertIn("day_guard.grid_context(", src)

	def test_the_old_overridable_check_is_gone(self):
		self.assertNotIn("double pay\")", self.src("api", "actuals.py"))
		self.assertNotIn("dup_reasons", self.src("api", "actuals.py"))

	def test_the_grid_warns_before_submit(self):
		js = self.src("public", "js", "work-actuals.js")
		self.assertIn("function dayGuardScan(a)", js)
		self.assertIn("!dgScan.blocks.length", js)

	def test_the_payment_column_is_not_called_a_rate(self):
		js = self.src("public", "js", "work-payment.js")
		self.assertIn(">Avg / unit</th>", js)

	def test_closed_short_and_short_day_have_their_own_rows(self):
		src = self.src("api", "payment.py")
		at = src.index('{"key": "closed_short"')
		self.assertIn('"rows": b_closed}', src[at:at + 900])
		at = src.index('{"key": "short_day"')
		self.assertIn('"rows": b_short}', src[at:at + 900])


class SiteCase(pipeline.SiteTestCase, unittest.TestCase):
	"""Two plans on one task, crews overlapping -- the 30 Oct shape."""

	def setUp(self):
		super().setUp()
		self.settings(att_block_absent=0, att_block_leave=0, att_block_noscan_actuals=0,
			att_block_off=0, block_self_approval=0, allow_split_day=1, max_hours_per_day=8)
		self.a = pipeline.Pipeline(days=1)
		self.a.master_plan()

	def second(self, other_block=False, quantity=None):
		b = pipeline.Pipeline(days=1)
		b.mp = self.a.mp
		if other_block:
			b.block = self.spare_block()
		b.plan(quantity=quantity or 4)
		b.assignment()
		return b

	def spare_block(self):
		name = frappe.db.sql("""SELECT name FROM `tabWarehouse` WHERE is_group = 0 AND disabled = 0
			AND IFNULL(custom_farm, '') = '' ORDER BY name LIMIT 1""", pluck=True)[0]
		frappe.db.set_value("Warehouse", name, "custom_farm", self.a.farm, update_modified=False)
		return name

	def one_cell(self, p, qty, emp=None):
		return (emp or p.workers[0]) + "~" + p.days()[0] + "~" + str(qty)

	def plain(self, p, uom, target):
		frappe.db.set_value(PLAN, p.pl, {"uom": uom, "daily_target": target}, update_modified=False)


class TestTheScreenRefuses(SiteCase):
	def test_the_same_crew_date_and_task_twice_is_refused_naming_the_first(self):
		self.a.plan(quantity=4)
		self.a.assignment()
		self.a.actuals(submit=True, qty=2)
		first = self.a.act
		b = self.second()
		out = b.actuals(submit=True, qty=2, check=False)
		self.assertTrue(out.get("error"), out)
		self.assertIn(first, out["error"])
		self.assertTrue(out.get("day_conflicts"))
		self.assertFalse(frappe.db.exists(ACT, {"assignment": b.asg}))

	def test_there_is_no_override(self):
		self.a.plan(quantity=4)
		self.a.assignment()
		self.a.actuals(submit=False, qty=2)
		b = self.second()
		out = b.actuals(submit=False, qty=2, att_override=1, check=False)
		self.assertIn(self.a.act, out.get("error") or "")

	def test_a_paid_first_copy_still_counts(self):
		self.a.plan(quantity=4)
		self.a.assignment()
		self.a.actuals(submit=False, qty=2)
		frappe.db.sql("UPDATE `tabWork Actuals Employee` SET paid = 1 WHERE parent = %s", self.a.act)
		frappe.db.set_value(ACT, self.a.act, "workflow_state", "CONFIRMED", update_modified=False)
		out = self.second().actuals(submit=False, qty=2, check=False)
		self.assertIn(self.a.act, out.get("error") or "")

	def test_a_rejected_first_copy_does_not(self):
		self.a.plan(quantity=4)
		self.a.assignment()
		self.a.actuals(submit=False, qty=2)
		frappe.db.set_value(ACT, self.a.act, "workflow_state", "Rejected", update_modified=False)
		self.second().actuals(submit=False, qty=2)

	def test_the_desk_cannot_add_it_in_draft_either(self):
		self.a.plan(quantity=4)
		self.a.assignment()
		self.a.actuals(submit=False, qty=2)
		b = self.second()
		doc = frappe.get_doc({"doctype": ACT, "assignment": b.asg, "employees": [{
			"employee": b.workers[0], "work_date": b.days()[0], "actual_quantity": 1,
			"count_in_payroll": 1}]})
		with self.assertRaises(frappe.ValidationError) as cm:
			doc.insert(ignore_permissions=True)
		self.assertIn(self.a.act, str(cm.exception))


class TestApprovalAsksAgain(SiteCase):
	"""A duplicate written before the guard -- or past it -- is not approved."""

	def legacy_pair(self):
		self.a.plan(quantity=4)
		self.a.assignment()
		self.a.actuals(submit=True, qty=2)
		b = self.second()
		doc = frappe.get_doc({"doctype": ACT, "assignment": b.asg,
			"employees": [{"employee": w, "work_date": b.days()[0], "actual_quantity": 2,
				"count_in_payroll": 1} for w in b.workers]})
		doc.flags.skip_day_guard = True
		doc.insert(ignore_permissions=True)
		frappe.db.set_value(ACT, doc.name, "workflow_state",
			frappe.db.get_value(ACT, self.a.act, "workflow_state"), update_modified=False)
		return b, doc.name

	def test_single_approve_is_refused(self):
		b, dup = self.legacy_pair()
		step = frappe.db.get_value(ACT, dup, "workflow_state")
		stage = [s["key"] for s in day_guard_chain() if s["state"] == step][0]
		out = call(pipeline.endpoints().act, action="act_approve", name=dup, stage=stage)
		self.assertIn(self.a.act, out.get("error") or "", out)
		self.assertEqual(frappe.db.get_value(ACT, dup, "workflow_state"), step)

	def test_bulk_approve_is_refused_per_document(self):
		b, dup = self.legacy_pair()
		step = frappe.db.get_value(ACT, dup, "workflow_state")
		stage = [s["key"] for s in day_guard_chain() if s["state"] == step][0]
		out = call(pipeline.endpoints().act, action="act_approve_bulk", names=[dup], stage=stage)
		self.assertEqual(out.get("ok"), [])
		self.assertEqual(len(out.get("failed") or []), 1)
		self.assertIn(self.a.act, out["failed"][0]["why"])

	def test_the_approver_cannot_edit_it_in_place_either(self):
		b, dup = self.legacy_pair()
		out = b.actuals(submit=False, qty=2, edit_doc=dup, check=False)
		self.assertIn(self.a.act, out.get("error") or "")


def day_guard_chain():
	from work_management import approvals

	return approvals.effective_chain(document_type=ACT)


class TestHours(SiteCase):
	def hourly_pair(self, qa, qb):
		self.a.plan(quantity=qa)
		self.plain(self.a, "Hour", 8)
		self.a.assignment()
		self.a.actuals(submit=False, rows=self.one_cell(self.a, qa))
		b = self.second(other_block=True, quantity=qb)
		self.plain(b, "Hour", 8)
		return b

	def test_eight_and_eight_is_refused(self):
		b = self.hourly_pair(8, 8)
		out = b.actuals(submit=False, rows=self.one_cell(b, 8), check=False)
		self.assertIn("16", out.get("error") or "")
		self.assertIn(self.a.act, out.get("error") or "")

	def test_four_and_four_passes(self):
		b = self.hourly_pair(4, 4)
		b.actuals(submit=False, rows=self.one_cell(b, 4))


class TestTheMixedDayIsFlagged(SiteCase):
	def test_eight_hours_and_a_bed_saves_and_shows_in_discrepancies(self):
		self.a.plan(quantity=8)
		self.plain(self.a, "Hour", 8)
		self.a.assignment()
		self.a.actuals(submit=True, rows=self.one_cell(self.a, 8))
		b = self.second(other_block=True, quantity=1)
		self.plain(b, "Nos", 1)
		b.actuals(submit=True, rows=self.one_cell(b, 1))
		from work_management.api.payment import wm_payment

		out = call(wm_payment, action="pay_discrepancies",
			from_date=self.a.days()[0], to_date=self.a.days()[0])
		check = [c for c in out["checks"] if c["key"] == "multi_standard"][0]
		hit = [r for r in check["rows"] if r["employee"] == self.a.workers[0]]
		self.assertEqual(len(hit), 1, check)
		self.assertIn("more than one day's standard on " + self.a.days()[0], hit[0]["what"])
		self.assertIn(self.a.act, hit[0]["actuals"])
		self.assertIn(b.act, hit[0]["actuals"])


class TestTheGridIsTold(SiteCase):
	def test_act_detail_carries_the_other_documents(self):
		self.a.plan(quantity=4)
		self.a.assignment()
		self.a.actuals(submit=True, qty=2)
		b = self.second()
		out = call(pipeline.endpoints().act, action="act_detail", assignment=b.asg)
		cells = out["detail"]["day_guard"]["cells"]
		key = b.workers[0] + "~" + b.days()[0]
		self.assertEqual(cells[key][0]["doc"], self.a.act)
		self.assertEqual(cells[key][0]["same"], "same task and block")


class TestTheConsoleReport(SiteCase):
	"""The read-only report runs in the System Console sandbox and finds a pair."""

	def test_it_runs_sandboxed_and_lists_the_pair(self):
		from unittest import mock

		from frappe.utils import safe_exec

		TestApprovalAsksAgain.legacy_pair(self)
		with open(os.path.join(REPO, "scripts", "console_duplicate_day_report.py")) as f:
			script = f.read()
		with mock.patch.object(safe_exec, "is_safe_exec_enabled", lambda: True):
			frappe.local.debug_log = []
			safe_exec.safe_exec(script)
			log = "\n".join(str(x) for x in frappe.local.debug_log)
		self.assertIn("SAME WORK TWICE", log)
		self.assertIn(self.a.act, log)
