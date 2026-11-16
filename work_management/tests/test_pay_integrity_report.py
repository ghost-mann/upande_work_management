"""The clean-up workbook is read-only and has its eight sheets.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest work_management.tests.test_pay_integrity_report -v
"""

import importlib
import os
import sys
import tempfile
import types
import unittest


class TestTheWorkbook(unittest.TestCase):
	def test_it_writes_eight_sheets_and_a_summary_without_writing_data(self):
		fake = types.ModuleType("frappe")
		seen = []

		def sql(q, *a, **k):
			seen.append(q)
			return []

		fake.db = types.SimpleNamespace(sql=sql)
		fake.utils = types.SimpleNamespace(today=lambda: "2026-11-12")
		saved = sys.modules.get("frappe")
		sys.modules["frappe"] = fake
		try:
			import work_management.pay_integrity_report as rep
			importlib.reload(rep)
			path = os.path.join(tempfile.mkdtemp(), "x.xlsx")
			rep.run(path)
			from openpyxl import load_workbook
			names = load_workbook(path).sheetnames
			self.assertEqual(len(names), 9)
			self.assertEqual(names[0], "Summary")
			for q in seen:
				head = q.strip().split()[0].upper()
				self.assertIn(head, ("SELECT", "SET"))
		finally:
			if saved is not None:
				sys.modules["frappe"] = saved
			else:
				del sys.modules["frappe"]


if __name__ == "__main__":
	unittest.main()
