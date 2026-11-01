import unittest

from work_management.team_leaders import (
	master_plan_kpis,
	quality_split,
	resolve_leader,
	stand_in_errors,
	weekly_kpis,
)

COVER = [
	{"team_leader": "otieno", "stand_in": "chebet", "from_date": "2026-11-03", "to_date": "2026-11-10"},
	{"team_leader": "otieno", "stand_in": "wanjiru", "from_date": "2026-11-05", "to_date": "2026-11-06"},
]


class ResolveLeader(unittest.TestCase):
	def test_owner_outside_any_cover(self):
		self.assertEqual(resolve_leader("otieno", "2026-11-02", COVER), "otieno")
		self.assertEqual(resolve_leader("otieno", "2026-11-11", COVER), "otieno")

	def test_stand_in_inside_dates_inclusive(self):
		self.assertEqual(resolve_leader("otieno", "2026-11-03", COVER), "chebet")
		self.assertEqual(resolve_leader("otieno", "2026-11-10", COVER), "chebet")

	def test_the_later_starting_cover_wins_where_they_overlap(self):
		self.assertEqual(resolve_leader("otieno", "2026-11-05", COVER), "wanjiru")

	def test_cover_for_someone_else_is_ignored(self):
		self.assertEqual(resolve_leader("kamau", "2026-11-05", COVER), "kamau")

	def test_no_owner_means_no_leader(self):
		self.assertIsNone(resolve_leader(None, "2026-11-05", COVER))


class StandInErrors(unittest.TestCase):
	def test_clean_rows(self):
		self.assertEqual(stand_in_errors(COVER, {"otieno"}), [])

	def test_each_problem_is_named(self):
		rows = [
			{"team_leader": "otieno", "stand_in": "otieno", "from_date": "2026-11-01", "to_date": "2026-11-02"},
			{"team_leader": "otieno", "stand_in": "x", "from_date": "2026-11-05", "to_date": "2026-11-01"},
			{"team_leader": "kamau", "stand_in": "x", "from_date": "2026-11-01", "to_date": "2026-11-02"},
			{"team_leader": "otieno", "stand_in": "", "from_date": "2026-11-01", "to_date": "2026-11-02"},
		]
		errs = stand_in_errors(rows, {"otieno"})
		self.assertEqual(len(errs), 4)
		self.assertIn("themselves", errs[0])
		self.assertIn("before", errs[1])
		self.assertIn("leads no activity", errs[2])
		self.assertIn("needs", errs[3])


class Kpis(unittest.TestCase):
	def test_weekly(self):
		k = weekly_kpis(planned_md=10, earned_md=8, actual_md=10,
		                planned_cost=5000, earned_cost=4000, actual_cost=4000)
		self.assertEqual(k["completion"], 80.0)
		self.assertEqual(k["efficiency"], 80.0)
		self.assertEqual(k["cost_efficiency"], 100.0)

	def test_nothing_planned_is_none_not_zero(self):
		k = weekly_kpis(0, 0, 0, 0, 0, 0)
		self.assertIsNone(k["completion"])
		self.assertIsNone(k["efficiency"])

	def test_master_plan_backlog(self):
		k = master_plan_kpis(target_qty=200, target_md=20, rate=50, done_qty=150, actual_md=12, actual_cost=7500)
		self.assertEqual(k["progress"], 75.0)
		self.assertEqual(k["backlog_qty"], 50)
		self.assertEqual(k["backlog_md"], 5)
		self.assertEqual(k["backlog_cost"], 2500)
		self.assertEqual(k["efficiency"], 125.0)

	def test_over_delivery_leaves_no_negative_backlog(self):
		k = master_plan_kpis(100, 10, 5, 130, 13, 650)
		self.assertEqual(k["backlog_qty"], 0)

	def test_quality_split(self):
		q = quality_split(["1 - Good"] * 8 + ["2 - Fair"] + ["3 - Rework"] + [None])
		self.assertEqual(q["scored"], 10)
		self.assertEqual((q["good"], q["fair"], q["rework"]), (80.0, 10.0, 10.0))

	def test_quality_split_empty(self):
		self.assertIsNone(quality_split([])["rework"])


if __name__ == "__main__":
	unittest.main()
