"""Amount and date sanity (2026-11-12): quantity caps, no future work, the plan
cap at every approval, desk saves re-derive amounts, plans priced by date.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest work_management.tests.test_amount_sanity -v
"""

import importlib
import sys
import types
import unittest

from work_management.tests.test_one_worker_one_day import Row, source


def block(module, action):
	src = source(module)
	start = src.index('    elif action == "' + action + '"')
	end = src.find("\n    elif action", start + 1)
	return src[start:end if end > 0 else len(src)]


class Doc(Row):
	__setattr__ = dict.__setitem__


def hook(today="2026-11-12", locked=None):
	fake = types.ModuleType("frappe")

	class Stop(Exception):
		pass

	def throw(msg, *a, **k):
		raise Stop(msg)

	fake.throw = throw
	fake._ = lambda s: s
	fake.utils = types.SimpleNamespace(today=lambda: today)
	fake.db = types.SimpleNamespace(
		sql=lambda q, a=None: ([("WMPC-1", "2026-10-01", "2026-10-31")] if (locked and "Payroll Check" in q) else []),
		exists=lambda dt, name=None: True)
	saved = sys.modules.get("frappe")
	sys.modules["frappe"] = fake
	import work_management.duplicate_guard as guard
	importlib.reload(guard)
	return guard, Stop, saved


def restore(saved):
	if saved is not None:
		sys.modules["frappe"] = saved
	else:
		del sys.modules["frappe"]


def record(rows, **kw):
	d = Doc(name="WMAC-1", docstatus=0, workflow_state="Draft", rate=48.375, farm="Endebess",
		from_date="2026-10-01", to_date="2026-10-31", flags=Row(), employees=[Doc(r) for r in rows])
	d.update(kw)
	d.get = lambda k, dflt=None: dict.get(d, k, dflt)
	return d


class TestTheDeskHook(unittest.TestCase):
	def test_a_typed_amount_is_rederived(self):
		guard, Stop, saved = hook()
		try:
			d = record([{"employee": "E1", "work_date": "2026-10-02", "actual_quantity": 8, "amount": 3870, "count_in_payroll": 1}])
			guard.validate_actuals(d)
			self.assertEqual(d.employees[0].amount, 387.0)
			self.assertEqual(d.total_payment, 387.0)
		finally:
			restore(saved)

	def test_wage_rounding_within_one_percent_is_kept(self):
		guard, Stop, saved = hook()
		try:
			d = record([{"employee": "E1", "work_date": "2026-10-02", "actual_quantity": 8, "amount": 388.5, "count_in_payroll": 1}])
			guard.validate_actuals(d)
			self.assertEqual(d.employees[0].amount, 388.5)
		finally:
			restore(saved)

	def test_future_and_outside_dates_are_refused(self):
		for day in ("2026-11-20", "2026-09-30"):
			guard, Stop, saved = hook()
			try:
				d = record([{"employee": "E1", "work_date": day, "actual_quantity": 8, "amount": 387, "count_in_payroll": 1}],
					to_date="2026-11-30")
				with self.subTest(day=day), self.assertRaises(Stop):
					guard.validate_actuals(d)
			finally:
				restore(saved)

	def test_a_locked_check_refuses_desk_edits(self):
		guard, Stop, saved = hook(locked=True)
		try:
			d = record([{"employee": "E1", "work_date": "2026-10-02", "actual_quantity": 8, "amount": 387, "count_in_payroll": 1}])
			with self.assertRaises(Stop):
				guard.validate_actuals(d)
		finally:
			restore(saved)


class TestTheScreenPath(unittest.TestCase):
	def test_quantity_caps_and_future_dates(self):
		b = block("actuals", "act_submit")
		self.assertIn("that day has not happened yet", b)
		self.assertIn("x the daily target of", b)
		self.assertIn('out["needs_qty_reason"] = 1', b)
		self.assertIn("row.qty_flag =", b)
		self.assertIn("d.flags.wm_screen = 1", b)

	def test_the_plan_cap_counts_records_with_the_farm_manager(self):
		b = block("actuals", "act_submit")
		self.assertIn("ac.workflow_state IN ('Pending Farm Manager','Pending HR Head','Pending GM','CONFIRMED')", b)

	def test_every_approval_rechecks_the_plan_cap(self):
		src = source("actuals")
		self.assertIn("or wmg_cap_err(docname)", src)
		for action in ("act_fm_approve", "act_hr_approve", "act_gm_approve"):
			with self.subTest(action=action):
				self.assertIn("wmg_doc_err(nm)", block("actuals", action))


class TestPlansArePricedByDate(unittest.TestCase):
	def test_planner_reads_the_rate_period_for_its_dates(self):
		b = block("planner", "submit")
		self.assertIn("tinfo = wmg_task_terms(task, from_date)", b)
		self.assertIn("cap_tinfo = wmg_task_terms(task, from_date)", b)
		self.assertIn("Split the plan at the change", b)
		self.assertIn("The plan ends before it starts.", b)
		self.assertIn("wmg_backdate_err(from_date)", b)


if __name__ == "__main__":
	unittest.main()
