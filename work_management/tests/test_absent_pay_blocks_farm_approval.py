"""With "never record work on a day marked Absent" on, pay on an Absent day is a
"block" issue: the server already refused the farm's approval, but the farm card
still said "(check, not blocking)" and counted days that also had a Present record."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestFarmCard(unittest.TestCase):
	def setUp(self):
		self.py = (ROOT / "api" / "payment.py").read_text()
		self.js = (ROOT / "public" / "js" / "work-payment.js").read_text()

	def test_detail_says_whether_absent_pay_blocks(self):
		i = self.py.index('action == "chk_detail"')
		body = self.py[i:self.py.index('action == "chk_fix_dup"')]
		self.assertIn('out["absent_blocks"]', body)
		self.assertIn("field = 'att_absent_never'", body)

	def test_count_skips_days_that_also_have_present(self):
		i = self.py.index('action == "chk_detail"')
		body = self.py[i:self.py.index('action == "chk_fix_dup"')]
		self.assertIn("pp.status IN ('Present', 'Half Day', 'Work From Home')", body)

	def test_card_follows_the_setting(self):
		self.assertIn("!(d.absent_blocks && f.absent_paid)", self.js)
		self.assertIn("(must be fixed before approval)", self.js)

	def test_the_server_still_blocks(self):
		self.assertIn('"absent_paid": ("block" if frappe.db.sql(', self.py)


if __name__ == "__main__":
	unittest.main()
