"""A worker released after their assignment ended is free from its last day.

Actuals entered on the 17th for a crew assigned on the 13th released the crew with
left_date = the 17th, and every busy check read that as "on the 13th's assignment
until the 17th" -- so Vale's whole workforce showed "assigned elsewhere" for the
17th. The busy checks now stop at the assignment's end whatever the left date says,
and the two releases that run when actuals finish a plan never write a date past it.
"""

import re
import unittest
from pathlib import Path

API = Path(__file__).resolve().parents[1] / "api"
UNCAPPED = "AND COALESCE(CASE WHEN IFNULL(we.status,'Active') = 'Left' THEN we.left_date END, a.to_date) >= %s"
CAPPED = "AND LEAST(COALESCE(CASE WHEN IFNULL(we.status,'Active') = 'Left' THEN we.left_date END, a.to_date), a.to_date) >= %s"


class TestBusyChecksStopAtTheAssignmentEnd(unittest.TestCase):
	def test_no_busy_check_reads_a_left_date_past_the_end(self):
		for name in ("assigner.py", "actuals.py"):
			src = (API / name).read_text()
			self.assertNotIn(UNCAPPED, src, name)

	def test_every_busy_check_is_capped(self):
		self.assertEqual((API / "assigner.py").read_text().count(CAPPED), 5)
		self.assertEqual((API / "actuals.py").read_text().count(CAPPED), 2)


class TestActualsReleasesStopAtTheAssignmentEnd(unittest.TestCase):
	def test_both_releases_cap_the_date(self):
		src = (API / "actuals.py").read_text()
		for loop in ("for fr in free_r:", "for fr in freerows:"):
			i = src.index(loop)
			body = src[i:i + 900]
			self.assertIn("if fr.td and str(fr.td) < str(rel_day):", body, loop)
			self.assertIn('"left_date", rel_day,', body, loop)
			sel = src[src.rindex("SELECT we.name row_id", 0, i):i]
			self.assertIn("a2.to_date td", sel, loop)

	def test_the_cap_itself(self):
		def rel(today, td):
			rel_day = today
			if td and str(td) < str(rel_day):
				rel_day = str(td)
			return rel_day

		self.assertEqual(rel("2026-11-17", "2026-11-13"), "2026-11-13")
		self.assertEqual(rel("2026-11-17", "2026-11-20"), "2026-11-17")
		self.assertEqual(rel("2026-11-17", None), "2026-11-17")


if __name__ == "__main__":
	unittest.main()
