"""Work confirmed after its week went to payroll can still be sent for that week.

Reported from live, 12 Oct 2026: sending 21-27 September for Endebess skipped
seven workers with hrms' "Additional Salary for this salary component with
Overwrite Salary Structure Amount enabled already exists for this date". The
week had been sent on 3 October; WMAC-321113 (22-26 September) was confirmed
on 5 October. Task Pay overwrites the structure amount, so hrms allows one
Additional Salary per worker per pay date, and the late days could never be
sent for 27 September.

The send now re-sends the week whole: the earlier run's Additional Salary is
cancelled (on_additional_salary_cancel drops the still-Unpaid run and frees
its rows) and the freed rows go out with the late ones as one payment for the
same date -- but only while payroll has not consumed it.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_late_work_tops_up_its_week -v
"""

import os
import re
import types
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def source():
	with open(os.path.join(HERE, "api", "payment.py")) as handle:
		return handle.read()


def helper(fake_frappe):
	"""release_sent_week_for_topup() out of the ported module, bound to a fake frappe."""
	src = source()
	start = src.index("def release_sent_week_for_topup(")
	end = src.index("\ndef ", start + 1)
	scope = {"frappe": fake_frappe}
	exec(src[start:end], scope)
	return scope["release_sent_week_for_topup"]


class Row(dict):
	__getattr__ = dict.get


class FakeFrappe:
	def __init__(self, existing, slips=(), runs=None):
		self.existing = [Row(a) for a in existing]
		self.slips = dict(slips)
		self.runs = {k: Row(v) for k, v in (runs or {}).items()}
		self.cancelled = []
		frappe = self
		self.db = types.SimpleNamespace(
			get_all=lambda doctype, filters=None, fields=None: list(frappe.existing),
			sql=lambda q, args, as_dict=False: (
				[Row(name=frappe.slips[args[0]])] if args[0] in frappe.slips else []),
			get_value=lambda doctype, name, fields, as_dict=False: frappe.runs.get(name),
		)

	def get_doc(self, doctype, name):
		frappe = self
		doc = types.SimpleNamespace(flags=types.SimpleNamespace())
		doc.cancel = lambda: frappe.cancelled.append(name)
		return doc


WEEK = ("2026-09-21", "2026-09-27")
RUN = {"workflow_state": "Unpaid", "period_from": "2026-09-21", "period_to": "2026-09-27"}
SENT = {"name": "HR-ADS-26-10-00014", "ref_doctype": "Work Management Payment",
	"ref_docname": "WMPAY-512207"}


def call(fake):
	return helper(fake)("400289", "Task Pay", "2026-09-27", *WEEK)


class TestTheHelper(unittest.TestCase):
	def test_nothing_sent_yet_changes_nothing(self):
		fake = FakeFrappe([])
		self.assertEqual(call(fake), {})
		self.assertEqual(fake.cancelled, [])

	def test_an_unpaid_run_is_reopened(self):
		fake = FakeFrappe([SENT], runs={"WMPAY-512207": RUN})
		self.assertEqual(call(fake), {"released": ["WMPAY-512207"]})
		self.assertEqual(fake.cancelled, ["HR-ADS-26-10-00014"])

	def test_a_week_payroll_already_paid_is_left_alone(self):
		fake = FakeFrappe([SENT], slips={"HR-ADS-26-10-00014": "Sal Slip/400289/00010"},
			runs={"WMPAY-512207": RUN})
		out = call(fake)
		self.assertIn("Sal Slip/400289/00010", out["block"])
		self.assertEqual(fake.cancelled, [])

	def test_a_paid_run_is_left_alone(self):
		fake = FakeFrappe([SENT], runs={"WMPAY-512207": dict(RUN, workflow_state="Paid")})
		self.assertIn("Paid", call(fake)["block"])
		self.assertEqual(fake.cancelled, [])

	def test_an_additional_salary_from_elsewhere_is_left_alone(self):
		fake = FakeFrappe([{"name": "HR-ADS-26-10-00999", "ref_doctype": None, "ref_docname": None}])
		self.assertIn("not raised by Work Management", call(fake)["block"])
		self.assertEqual(fake.cancelled, [])

	def test_a_run_wider_than_the_window_is_left_alone(self):
		"""Its freed rows outside the window would be left unsent."""
		fake = FakeFrappe([SENT], runs={"WMPAY-512207": dict(RUN, period_from="2026-09-14")})
		self.assertIn("wider than", call(fake)["block"])
		self.assertEqual(fake.cancelled, [])


class TestBothSendsUseIt(unittest.TestCase):
	"""The single and the bulk send each reopen the week inside their savepoint and
	re-read it before building the payment."""

	def section(self, action, prefix):
		src = source()
		start = src.index('action == "' + action + '":')
		end = src.index("elif action ==", start + 1)
		body = src[start:end]
		sp = body.index("frappe.db.savepoint(" + prefix + "_savepoint)")
		return body[sp:body.index('frappe.new_doc("Work Management Payment")', sp)]

	def check(self, action, prefix):
		body = self.section(action, prefix)
		self.assertIn("release_sent_week_for_topup(", body)
		self.assertRegex(body, r"rollback\(save_point=" + prefix + r"_savepoint\)")
		self.assertRegex(body, r"agg = frappe\.db\.sql\(" + prefix + r"_agg_sql")

	def test_the_single_send(self):
		self.check("pay_worker_submit", "wm")

	def test_the_bulk_send(self):
		self.check("pay_bulk_submit", "bw")


if __name__ == "__main__":
	unittest.main()
