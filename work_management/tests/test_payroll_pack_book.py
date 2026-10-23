"""Guards on the payroll approval pack: what an approver sees before pay is released.

Pure: rows in, a pack out. No site::

    ./env/bin/python -m unittest work_management.tests.test_payroll_pack_book -v
"""

import copy
import unittest

from work_management.payroll_pack_book import build_pack, farms_in, filter_farm


def line(wmpay, employee, name, farm, task, days, qty, rate, amount):
	return {"wmpay": wmpay, "employee": employee, "employee_name": name, "farm": farm,
		"task": task, "block": "B1", "work_from": "2026-10-12", "work_to": "2026-10-16",
		"days": days, "qty": qty, "rate": rate, "amount": amount, "entered_by": "a@x.com",
		"fm_approved_by": "fm@x.com", "hr_approved_by": "hr@x.com", "gm_approved_by": "gm@x.com"}


def slip(entry, slip_name, employee, name, wmpay, wm_amount):
	return {"entry": entry, "slip": slip_name, "employee": employee, "employee_name": name,
		"wmpay": wmpay, "wm_amount": wm_amount}


ENTRIES = [
	{"name": "PE1", "start_date": "2026-10-12", "end_date": "2026-10-18", "workflow_state": "Accounts"},
	{"name": "PE2", "start_date": "2026-10-19", "end_date": "2026-10-25", "workflow_state": "Accounts"},
]

# E1 works two farms; E2 is paid 500 for 450 of work; E3 is on two slips; E9 has no work.
LINES = [
	line("P1", "E1", "Alice", "Endebess", "Picking", 3, 30, 10, 300),
	line("P2", "E1", "Alice", "Vale", "Weeding", 2, 20, 10, 200),
	line("P3", "E2", "Bob", "Endebess", "Picking", 4, 45, 10, 450),
	line("P4", "E3", "Carol", "Vale", "Weeding", 2, 40, 10, 400),
	line("P5", "E3", "Carol", "Vale", "Pruning", 3, 55, 10, 550),
]
SLIPS = [
	slip("PE1", "S1", "E1", "Alice", "P1", 300),
	slip("PE1", "S1", "E1", "Alice", "P2", 200),
	slip("PE1", "S2", "E2", "Bob", "P3", 500),
	slip("PE1", "S3", "E3", "Carol", "P4", 400),
	slip("PE2", "S4", "E3", "Carol", "P5", 550),
	slip("PE1", "S9", "E9", "Zed", None, 0),
]
DAYS = {"E1": 4, "E2": 4, "E3": 5, "E9": 1}


def pack(lines=None, slips=None, days=None, days_farm=None):
	return build_pack(copy.deepcopy(ENTRIES), copy.deepcopy(LINES if lines is None else lines),
		copy.deepcopy(SLIPS if slips is None else slips), DAYS if days is None else days, days_farm)


def by_emp(rows):
	return {r["employee"]: r for r in rows}


def kinds(p):
	return {(c["employee"], c["kind"]) for c in p["checks"]}


class TestHeadlineFigures(unittest.TestCase):

	def test_days_worked_counts_calendar_days_not_line_days(self):
		"""E1's lines add to 5 days but they worked 4 calendar days."""
		self.assertEqual(by_emp(pack()["workers"])["E1"]["days_worked"], 4)

	def test_headline_total_is_the_slip_total(self):
		t = pack()["totals"]
		self.assertEqual(t["slip_total"], 1950.0)
		self.assertEqual(t["line_total"], 1900.0)

	def test_man_days_is_the_sum_of_days_worked(self):
		self.assertEqual(pack()["totals"]["man_days"], 14)

	def test_workers_sort_by_first_farm_then_name(self):
		order = [w["employee"] for w in pack()["workers"]]
		self.assertEqual(order, ["E1", "E2", "E3", "E9"])

	def test_entries_carry_their_worker_count_and_amount(self):
		e = {r["name"]: r for r in pack()["entries"]}
		self.assertEqual((e["PE1"]["workers"], e["PE1"]["amount"]), (4, 1400.0))
		self.assertEqual((e["PE2"]["workers"], e["PE2"]["amount"]), (1, 550.0))


class TestChecks(unittest.TestCase):

	def test_a_slip_with_no_work_is_a_check(self):
		p = pack()
		self.assertIn(("E9", "no_work"), kinds(p))
		w = by_emp(p["workers"])["E9"]
		self.assertEqual((w["farms"], w["days_worked"], w["tasks"], w["wm_amount"]), ([], 1, 0, 0))

	def test_slip_and_lines_disagreeing_is_a_check(self):
		p = pack()
		w = by_emp(p["workers"])["E2"]
		self.assertEqual((w["slip_amount"], w["wm_amount"], w["difference"]), (500.0, 450.0, 50.0))
		self.assertIn(("E2", "amount_mismatch"), kinds(p))
		self.assertEqual(w["flag"], "amount_mismatch")

	def test_a_worker_on_two_slips_is_a_check(self):
		self.assertIn(("E3", "two_slips"), kinds(pack()))

	def test_agreeing_amounts_within_a_cent_are_not_flagged(self):
		p = pack(lines=[line("P1", "E1", "Alice", "Vale", "Picking", 1, 1, 100, 100.0)],
			slips=[slip("PE1", "S1", "E1", "Alice", "P1", 100.004)], days={"E1": 1})
		self.assertEqual(p["checks"], [])
		self.assertEqual(by_emp(p["workers"])["E1"]["flag"], "")


class TestFarmPacks(unittest.TestCase):

	def test_a_two_farm_worker_appears_in_each_farm_pack_with_only_that_farms_lines(self):
		p = pack()
		v, e = filter_farm(p, "Vale"), filter_farm(p, "Endebess")
		self.assertIn("E1", by_emp(v["workers"]))
		self.assertIn("E1", by_emp(e["workers"]))
		self.assertTrue(all(r["farm"] == "Vale" for r in v["detail"]))
		self.assertEqual(by_emp(v["workers"])["E1"]["farms"], ["Vale"])

	def test_farm_pack_total_is_that_farms_line_total(self):
		p = pack()
		self.assertEqual(filter_farm(p, "Vale")["totals"]["slip_total"], 1150.0)
		self.assertEqual(filter_farm(p, "Endebess")["totals"]["slip_total"], 750.0)

	def test_farm_pack_checks_only_name_its_own_workers(self):
		v = filter_farm(pack(), "Vale")
		self.assertEqual({c["employee"] for c in v["checks"]}, {"E3"})
		self.assertNotIn("E9", by_emp(v["workers"]))

	def test_a_farm_pack_never_shows_another_farms_amounts(self):
		v = filter_farm(pack(days_farm={("E1", "Vale"): 2, ("E1", "Endebess"): 2}), "Vale")
		w = by_emp(v["workers"])["E1"]
		self.assertEqual((w["wm_amount"], w["slip_amount"], w["difference"], w["flag"], w["tasks"]),
			(200.0, None, None, None, 1))
		self.assertNotIn("E1", {c["employee"] for c in v["checks"]})
		e = {r["name"]: r for r in v["entries"]}
		self.assertEqual((e["PE1"]["workers"], e["PE1"]["amount"]), (2, 600.0))
		self.assertEqual(v["totals"]["by_farm"], {"Vale": {"workers": 2, "days": 7, "amount": 1150.0}})

		def walk(x):
			if isinstance(x, dict):
				for k, val in x.items():
					yield from walk(k)
					yield from walk(val)
			elif isinstance(x, (list, tuple)):
				for val in x:
					yield from walk(val)
			else:
				yield x
		seen = list(walk(v))
		self.assertNotIn("Endebess", seen)
		for secret in (500, 500.0, 300.0, 450.0, 750.0, 1400.0, 1900.0, 1950.0):
			self.assertNotIn(secret, seen)

	def test_farm_days_come_from_days_by_employee_farm(self):
		w = by_emp(filter_farm(pack(days_farm={("E1", "Vale"): 2}), "Vale")["workers"])
		self.assertEqual(w["E1"]["days_worked"], 2)
		self.assertEqual(w["E3"]["days_worked"], 5)  # all on Vale: falls back to whole-person days

	def test_a_two_farm_workers_farm_days_are_none_when_unknown(self):
		w = by_emp(filter_farm(pack(), "Vale")["workers"])
		self.assertIsNone(w["E1"]["days_worked"])
		self.assertEqual(filter_farm(pack(), "Vale")["totals"]["man_days"], 5)

	def test_farms_are_listed_sorted(self):
		self.assertEqual(farms_in(pack()), ["Endebess", "Vale"])


class TestByTask(unittest.TestCase):

	def test_by_task_groups_per_farm_and_task(self):
		rows = {(r["farm"], r["task"]): r for r in pack()["by_task"]}
		self.assertEqual(set(rows), {("Endebess", "Picking"), ("Vale", "Weeding"), ("Vale", "Pruning")})
		picking = rows[("Endebess", "Picking")]
		self.assertEqual((picking["workers"], picking["days"], picking["qty"], picking["amount"]),
			(2, 7, 75, 750.0))
		self.assertEqual(rows[("Vale", "Weeding")]["workers"], 2)


if __name__ == "__main__":
	unittest.main()
