"""Back-fill of worker-days already paid twice into the payroll-check audit log.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_payroll_check_backfill -v
"""

import importlib
import sys
import types
import unittest


class Row(dict):
	__getattr__ = dict.get


def run_with(rows, logged=(), dry_run=False):
	fake = types.ModuleType("frappe")
	inserted = []

	class Doc(Row):
		__setattr__ = dict.__setitem__

		def insert(self, ignore_permissions=False):
			inserted.append(dict(self))

	fake.db = types.SimpleNamespace(
		sql=lambda q, a=None, as_dict=False: [Row(r) for r in rows],
		exists=lambda dt, f: (f["employee"], f["work_date"]) in set(logged),
		commit=lambda: None)
	fake.new_doc = lambda dt: Doc()
	fake.session = types.SimpleNamespace(user="Administrator")
	fake.utils = types.SimpleNamespace(now=lambda: "2026-11-12 10:00:00", flt=lambda v: float(v or 0))
	saved = sys.modules.get("frappe")
	sys.modules["frappe"] = fake
	try:
		import work_management.payroll_check_backfill as bf
		importlib.reload(bf)
		return bf.run(dry_run=dry_run), inserted
	finally:
		if saved is not None:
			sys.modules["frappe"] = saved
		else:
			del sys.modules["frappe"]


ROWS = [
	{"row": "r1", "doc": "WMAC-1", "emp": "400289", "ename": "A", "d": "2026-09-24", "farm": "Endebess",
	 "qty": 1, "amount": 387, "payment_ref": "WMPAY-1"},
	{"row": "r2", "doc": "WMAC-2", "emp": "400289", "ename": "A", "d": "2026-09-24", "farm": "Endebess",
	 "qty": 1, "amount": 387, "payment_ref": "WMPAY-2"},
]


class TestBackfill(unittest.TestCase):
	def test_only_settled_pay_counts(self):
		"""A copy sitting in a run awaiting accounts is not paid yet (final review)."""
		import work_management
		src = open(work_management.__path__[0] + "/payroll_check_backfill.py").read()
		self.assertNotIn("OR IFNULL(w.payment_ref, '') != ''", src)
		self.assertNotIn("OR IFNULL(we.payment_ref, '') != ''", src)

	def test_one_entry_per_worker_day_paid_twice(self):
		out, ins = run_with(ROWS)
		self.assertEqual(out["logged"], 1)
		self.assertEqual(ins[0]["kind"], "paid twice")
		self.assertEqual(ins[0]["amount_before"], 387)
		self.assertIn("WMPAY-1", ins[0]["payments"])

	def test_backfill_idempotent(self):
		out, ins = run_with(ROWS, logged=[("400289", "2026-09-24")])
		self.assertEqual(out["logged"], 0)
		self.assertEqual(ins, [])

	def test_dry_run_writes_nothing(self):
		out, ins = run_with(ROWS, dry_run=True)
		self.assertEqual(out["found"], 1)
		self.assertEqual(ins, [])


if __name__ == "__main__":
	unittest.main()
