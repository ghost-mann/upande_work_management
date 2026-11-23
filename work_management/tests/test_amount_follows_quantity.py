# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""A day-row's money follows its quantity, whatever path saves it.

WMAC-02035 on Altura: submitted with 14 rows of 1 unit at 400 each, then
edited in the desk two minutes later -- every row 1 -> 0, nothing else -- while
it sat pending approval. The Actuals controller was empty, so the amounts stayed
at 400, the document was approved, and KES 5,600 went to payroll for no work.

Two rules now hold in the controller, not in the screen:

    every save re-prices        amount = round(qty x unit x multiplier, 2) for a
                                payroll row, 0 otherwise, and the totals are
                                re-summed -- desk, screen or script alike
    the chain freezes the rows  once a document has left Draft/Rejected, a change
                                to its day-rows is refused; corrections go back
                                through reject -> resubmit. The approver's
                                edit-in-place on the actuals screen stays, since
                                it re-prices from the grid.

and `scripts/console_reprice_actuals.py` repairs what was written before:
dry-run by default, unpaid rows only.

    bench --site kentrout.local run-tests --app work_management \\
        --module work_management.tests.test_amount_follows_quantity
"""

import os
import unittest
from unittest import mock

import frappe

from work_management import actuals_pay
from work_management.tests import pipeline
from work_management.tests.pipeline import call

ACT = "Work Management Actuals"
ROW = "Work Actuals Employee"
SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
	os.path.abspath(__file__)))), "scripts", "console_reprice_actuals.py")


class TestTheRule(unittest.TestCase):
	"""No site needed: the arithmetic itself."""

	def test_qty_times_unit(self):
		self.assertEqual(actuals_pay.row_amount(1, 400, 1, 1), 400)
		self.assertEqual(actuals_pay.row_amount(3, 13.114754, 1, 1), 39.34)

	def test_zero_quantity_is_worth_nothing(self):
		self.assertEqual(actuals_pay.row_amount(0, 400, 1, 1), 0)

	def test_the_holiday_multiplier_applies(self):
		self.assertEqual(actuals_pay.row_amount(2, 100, 1, 2), 400)

	def test_no_stored_multiplier_is_x1(self):
		self.assertEqual(actuals_pay.row_amount(2, 100, 1, None), 200)
		self.assertEqual(actuals_pay.row_amount(2, 100, 1, 0), 200)

	def test_outside_payroll_is_zero(self):
		self.assertEqual(actuals_pay.row_amount(5, 100, 0, 1), 0)


class SiteCase(pipeline.SiteTestCase, unittest.TestCase):
	def setUp(self):
		super().setUp()
		self.settings(att_block_absent=0, att_block_leave=0, att_block_noscan_actuals=0,
			att_block_off=0, block_self_approval=0)
		self.p = pipeline.Pipeline()
		self.p.master_plan()
		self.p.plan()
		self.p.assignment()

	def submitted(self):
		self.p.actuals(submit=True)
		self.assertNotIn(frappe.db.get_value(ACT, self.p.act, "workflow_state"),
			("Draft", "Rejected"))
		return frappe.get_doc(ACT, self.p.act)

	def unit(self, doc):
		return actuals_pay.unit_value(doc.rate, doc.planner_request)

	def assertConsistent(self, name):
		doc = frappe.get_doc(ACT, name)
		unit = self.unit(doc)
		total = 0
		for r in doc.employees:
			want = actuals_pay.row_amount(r.actual_quantity, unit, r.count_in_payroll,
				r.holiday_multiplier)
			self.assertAlmostEqual(frappe.utils.flt(r.amount), want, places=2,
				msg="row " + str(r.idx) + " qty " + str(r.actual_quantity))
			if r.count_in_payroll:
				total += frappe.utils.flt(r.amount)
		self.assertAlmostEqual(frappe.utils.flt(doc.total_payment), total, places=2)
		self.assertAlmostEqual(frappe.utils.flt(doc.total_actual_qty),
			sum(frappe.utils.flt(r.actual_quantity) for r in doc.employees), places=4)
		return doc


class TestPendingDocumentsAreFrozen(SiteCase):
	def test_the_screen_writes_consistent_amounts(self):
		doc = self.submitted()
		self.assertTrue(any(r.count_in_payroll for r in doc.employees),
			"fixture needs a payroll worker")
		self.assertConsistent(doc.name)

	def test_a_desk_quantity_edit_on_a_pending_document_is_refused(self):
		doc = self.submitted()
		before = [(r.actual_quantity, r.amount) for r in doc.employees]
		for r in doc.employees:
			r.actual_quantity = 0
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		self.assertEqual([(r.actual_quantity, r.amount) for r in frappe.get_doc(ACT, doc.name).employees],
			before)

	def test_adding_or_removing_a_row_is_refused(self):
		doc = self.submitted()
		doc.employees = doc.employees[1:]
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		doc = frappe.get_doc(ACT, self.p.act)
		doc.append("employees", {"employee": self.p.workers[0], "work_date": self.p.from_date,
			"actual_quantity": 1})
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_a_note_can_still_be_added(self):
		doc = self.submitted()
		doc.employees[0].note = "rain from 2pm"
		doc.save()
		self.assertEqual(frappe.db.get_value(ROW, doc.employees[0].name, "note"), "rain from 2pm")

	def test_the_approvers_edit_in_place_still_works_and_reprices(self):
		doc = self.submitted()
		self.p.actuals(submit=False, edit_doc=doc.name, qty=1)
		doc = self.assertConsistent(doc.name)
		self.assertTrue(all(frappe.utils.flt(r.actual_quantity) == 1 for r in doc.employees))

	def test_reject_then_correct_in_the_desk_reprices(self):
		doc = self.submitted()
		self.assertFalse(call(self.p.ep.act, action="act_reject", name=doc.name,
			reason="wrong qty").get("error"))
		doc = frappe.get_doc(ACT, doc.name)
		self.assertEqual(doc.workflow_state, "Rejected")
		for r in doc.employees:
			r.actual_quantity = 0
		doc.employees[0].actual_quantity = 1
		doc.save()
		doc = self.assertConsistent(doc.name)
		self.assertEqual(frappe.utils.flt(doc.total_actual_qty), 1)
		zero = [r for r in doc.employees if not frappe.utils.flt(r.actual_quantity)]
		self.assertTrue(zero and all(frappe.utils.flt(r.amount) == 0 for r in zero))

	def test_a_paid_rows_quantity_cannot_change_even_in_draft(self):
		self.p.actuals(submit=False)
		doc = frappe.get_doc(ACT, self.p.act)
		self.assertEqual(doc.workflow_state, "Draft")
		frappe.db.set_value(ROW, doc.employees[0].name, "paid", 1)
		doc = frappe.get_doc(ACT, doc.name)
		doc.employees[0].actual_quantity = 9
		with self.assertRaises(frappe.ValidationError):
			doc.save()


class TestTheConsoleRepair(SiteCase):
	def run_script(self, dry_run):
		from frappe.utils import safe_exec as se

		code = open(SCRIPT, encoding="utf-8").read()
		if not dry_run:
			self.assertEqual(code.count("\nDRY_RUN = True\n"), 1)
			code = code.replace("\nDRY_RUN = True\n", "\nDRY_RUN = False\n")
		frappe.local.debug_log = []
		with mock.patch.object(se, "is_safe_exec_enabled", lambda: True):
			se.safe_exec(code, script_filename="System Console")
		return "\n".join(frappe.local.debug_log)

	def test_dry_run_reports_and_apply_fixes_only_unpaid(self):
		doc = self.submitted()
		bad, paid = doc.employees[0], doc.employees[1]
		# WMAC-02035, written behind the controller's back the way it was live
		frappe.db.set_value(ROW, bad.name, "actual_quantity", 0)
		frappe.db.set_value(ROW, paid.name, {"actual_quantity": 0, "paid": 1})
		paid_amount = frappe.utils.flt(paid.amount)

		out = self.run_script(dry_run=True)
		self.assertIn(doc.name + " | " + str(bad.idx) + " |", out.split("PAID - NOT TOUCHED")[0])
		self.assertIn("PAID - NOT TOUCHED", out)
		self.assertIn(doc.name + " | " + str(paid.idx) + " |", out)
		self.assertGreater(frappe.utils.flt(frappe.db.get_value(ROW, bad.name, "amount")), 0,
			"dry run must not write")

		self.run_script(dry_run=False)
		self.assertEqual(frappe.utils.flt(frappe.db.get_value(ROW, bad.name, "amount")), 0)
		self.assertEqual(frappe.utils.flt(frappe.db.get_value(ROW, paid.name, "amount")), paid_amount)
		total = frappe.db.sql("""SELECT SUM(amount) FROM `tabWork Actuals Employee`
			WHERE parent = %s AND count_in_payroll = 1""", doc.name)[0][0]
		self.assertAlmostEqual(frappe.utils.flt(frappe.db.get_value(ACT, doc.name, "total_payment")),
			frappe.utils.flt(total), places=2)
		self.assertNotIn(doc.name + " | " + str(bad.idx) + " |",
			self.run_script(dry_run=True).split("PAID - NOT TOUCHED")[0])
