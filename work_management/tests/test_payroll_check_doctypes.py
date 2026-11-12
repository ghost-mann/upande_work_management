"""The payroll check's doctypes, the row column that ties a worker-day to one
check, and the Settings that replace week sign-off.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_payroll_check_doctypes -v
"""

import json
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DT = os.path.join(HERE, "work_management", "doctype")


def doctype(slug):
	with open(os.path.join(DT, slug, slug + ".json")) as handle:
		return json.load(handle)


def field(meta, name):
	for f in meta["fields"]:
		if f["fieldname"] == name:
			return f
	return None


class TestTheCheck(unittest.TestCase):
	def test_statuses(self):
		f = field(doctype("work_management_payroll_check"), "status")
		self.assertEqual(f["options"].split("\n"),
			["Farm Review", "HR Review", "GM Review", "Approved", "Sent", "Cancelled"])

	def test_it_holds_a_farm_table(self):
		meta = doctype("work_management_payroll_check")
		self.assertEqual(field(meta, "farms")["options"], "Work Management Payroll Check Farm")
		self.assertEqual(doctype("work_management_payroll_check_farm")["istable"], 1)

	def test_the_dates_and_top_up_flag(self):
		meta = doctype("work_management_payroll_check")
		for name in ("period_from", "period_to", "is_top_up", "sent_back_reason"):
			with self.subTest(name=name):
				self.assertIsNotNone(field(meta, name))

	def test_the_fix_log(self):
		meta = doctype("work_management_payroll_check_fix")
		self.assertEqual(field(meta, "kind")["options"].split("\n"),
			["duplicate", "paid twice", "draft completed", "rejected deleted", "acknowledged", "zeroed",
			 "recomputed", "edited", "slip mismatch"])
		for name in ("employee", "work_date", "kept_row", "zeroed_row", "amount_before", "reason"):
			with self.subTest(name=name):
				self.assertIsNotNone(field(meta, name))


class TestTheRowColumn(unittest.TestCase):
	def test_a_worker_day_names_its_check(self):
		f = field(doctype("work_actuals_employee"), "payroll_check")
		self.assertIsNotNone(f)
		self.assertEqual(f["fieldtype"], "Data")
		self.assertEqual(f.get("read_only"), 1)
		self.assertEqual(f.get("search_index"), 1)


class TestSettings(unittest.TestCase):
	def setUp(self):
		self.meta = doctype("work_management_settings")

	def test_week_signoff_is_gone(self):
		for name in ("week_signoff_required", "week_signoff_notify", "section_week_signoff"):
			with self.subTest(name=name):
				self.assertIsNone(field(self.meta, name))
		self.assertFalse(os.path.isdir(os.path.join(DT, "work_management_week_signoff")))

	def test_payroll_check_settings(self):
		self.assertEqual(field(self.meta, "payroll_check_required")["default"], "0")
		self.assertEqual(field(self.meta, "max_backdate_days")["default"], "7")
		self.assertIsNotNone(field(self.meta, "payroll_check_notify"))

	def test_the_split_day_switch_is_hidden(self):
		self.assertEqual(field(self.meta, "allow_split_day").get("hidden"), 1)

	def test_config_never_splits_a_day(self):
		with open(os.path.join(HERE, "api", "config.py")) as handle:
			src = handle.read()
		self.assertNotIn('bool(settings.get("allow_split_day"))', src)
		self.assertIn('cfg["allow_split_day"] = False', src)


if __name__ == "__main__":
	unittest.main()
