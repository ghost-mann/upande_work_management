"""No pay on a day marked Absent, whenever the Absent arrives.

Verified end to end on webstore.localhost (live slice): submitting an Absent zeroes
the day's unpaid pay and logs a Payroll Check Fix; cancelling it restores the pay;
a Half Day / Present record that day protects it. These pin the wiring."""

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "absent_pay.py").read_text()


class TestWiring(unittest.TestCase):
	def test_hooks(self):
		h = (ROOT / "hooks.py").read_text()
		self.assertIn('"on_submit": "work_management.absent_pay.on_attendance_submit"', h)
		self.assertIn('"on_cancel": "work_management.absent_pay.on_attendance_cancel"', h)
		self.assertIn('"work_management.absent_pay.sweep"', h)

	def test_functions_exist(self):
		names = {n.name for n in ast.parse(SRC).body if isinstance(n, ast.FunctionDef)}
		for f in ("enabled", "is_absent", "zero_day", "restore_day", "on_attendance_submit",
				"on_attendance_cancel", "sweep"):
			self.assertIn(f, names)


class TestRules(unittest.TestCase):
	def test_gated_on_the_setting(self):
		self.assertIn("field = 'att_absent_never'", SRC)
		for fn in ("on_attendance_submit", "sweep"):
			body = SRC[SRC.index("def " + fn):]
			self.assertIn("enabled()", body[:400], fn)

	def test_paid_pay_is_never_touched(self):
		self.assertGreaterEqual(SRC.count("IFNULL(we.paid, 0) = 0 AND IFNULL(we.payment_ref, '') = ''"), 2)

	def test_present_that_day_wins(self):
		self.assertGreaterEqual(SRC.count("pp.status IN ('Present', 'Half Day', 'Work From Home')"), 2)

	def test_quantity_is_kept_and_change_logged(self):
		body = SRC[SRC.index("def zero_day"):SRC.index("def restore_day")]
		self.assertIn('{"amount": 0, "custom_reviewed": 0}', body)
		self.assertNotIn('"actual_quantity": 0', body)
		self.assertIn('"Work Management Payroll Check Fix"', body)
		self.assertIn('fx.issue = ISSUE', body)

	def test_a_day_restored_by_hand_is_never_zeroed_again(self):
		body = SRC[SRC.index("def zero_day"):SRC.index("def restore_day")]
		self.assertIn("fx.reason LIKE %s", body)
		self.assertIn('"%" + RESTORED + "%"', body)
		self.assertIn('RESTORED = "Restored by management"', SRC)

	def test_restore_only_undoes_its_own_zeroing(self):
		body = SRC[SRC.index("def restore_day"):SRC.index("def on_attendance_submit")]
		self.assertIn("startswith(TAG)", body)
		self.assertIn("row.payment_ref", body)


if __name__ == "__main__":
	unittest.main()
