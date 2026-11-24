"""A payroll check's farm cards add up to its total (2026-11-24).

WMPC-1553785 said 9,801 worker-days, KES 3,775,720.23, while its farm cards added
to KES 3,797,169.23: the per-farm count took unstamped rows of salaried staff
(Vale supervisors, an HR clerk) that farm approval never puts into a check,
because they are not task workers (TW_ONLY). The cards now count the rows a
farm's approval would take."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestFarmCards(unittest.TestCase):
	def body(self):
		py = (ROOT / "api" / "payment.py").read_text()
		i = py.index('action == "chk_detail"')
		return py[i:py.index('action == "chk_fix_dup"')]

	def test_unstamped_rows_must_be_task_workers(self):
		b = self.body()
		i = b.index("SELECT ac.farm, COUNT(*) n")
		q = b[i:b.index("GROUP BY ac.farm", i)]
		self.assertIn("IFNULL(we.payment_ref, '') = ''\"\"\" + TW_ONLY + \"\"\"))", q)


if __name__ == "__main__":
	unittest.main()
