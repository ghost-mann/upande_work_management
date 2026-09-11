"""The same report, at two grains, with a picture on top.

The client: *"a daily summary report that can be displayed, exported via excel
or demonstrated through graphs."*

All three from one report. A second "daily summary" report would be a second
thing to keep in step with this one, and it would drift the first time a column
changed here and not there -- so the grain is a filter and the summary is the
detail rows added up, never a second query. Excel export and print come with the
Script Report surface, and `get_chart`'s fourth return value puts the bars above
the table.

Pure: `summarise_by_day()` and `chart_for()` take rows and return rows, so what
they do can be asserted without a site -- which is how the rest of this report's
suite works. Measured on kentrout.local as well, five detail rows over two days:

    2026-11-02   3 workers  1 task   qty 10   man-days 2.50   KES 100
    2026-11-03   2 workers  1 task   qty  8   man-days 1.25   KES  80

    detail 18.0 / 180.0 / 3.75   summary 18.0 / 180.0 / 3.75

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_the_daily_summary_and_chart -v
"""

import json
import os
import unittest

from work_management.work_management.report.worker_task_day import worker_task_day as report

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT_DIR = os.path.join(HERE, "work_management", "report", "worker_task_day")


def read(name):
	with open(os.path.join(REPORT_DIR, name)) as handle:
		return handle.read()


#: A Monday (8h) and a Saturday (6h), so the man-day ratio is not the same
#: divisor twice and a hardcoded 8 would show.
MONDAY = "2026-10-05"
SATURDAY = "2026-10-10"


def row(**over):
	base = {
		"employee": "HR-EMP-1", "employee_name": "A Worker",
		"work_date": MONDAY, "task": "Weeding", "farm": "KenTrout Farm",
		"actual_quantity": 5.0, "amount": 50.0, "hours": 8.0,
	}
	base.update(over)
	return base


class TestTheRollup(unittest.TestCase):
	def test_one_row_per_day(self):
		out = report.summarise_by_day([row(), row(), row(work_date=SATURDAY)])
		self.assertEqual([r["work_date"] for r in out], [MONDAY, SATURDAY])

	def test_days_come_back_in_order(self):
		out = report.summarise_by_day([row(work_date=SATURDAY), row(work_date=MONDAY)])
		self.assertEqual([r["work_date"] for r in out], [MONDAY, SATURDAY])

	def test_quantities_and_money_add_up(self):
		out = report.summarise_by_day([row(actual_quantity=5, amount=50),
			row(actual_quantity=3, amount=30)])
		self.assertEqual(out[0]["actual_quantity"], 8)
		self.assertEqual(out[0]["amount"], 80)

	def test_workers_are_counted_distinctly(self):
		"""A worker on three tasks in one day is one worker."""
		out = report.summarise_by_day([
			row(employee="A", task="t1"), row(employee="A", task="t2"),
			row(employee="B", task="t1")])
		self.assertEqual(out[0]["workers"], 2)

	def test_and_so_are_tasks(self):
		out = report.summarise_by_day([
			row(employee="A", task="t1"), row(employee="A", task="t2"),
			row(employee="B", task="t1")])
		self.assertEqual(out[0]["tasks"], 2)

	def test_man_days_are_measured_not_counted(self):
		"""A day split between two tasks is one day. Counting rows would make it
		two, which is the whole reason split_day.py exists."""
		out = report.summarise_by_day([row(hours=4), row(hours=4)])
		self.assertEqual(out[0]["man_days"], 1.0)

	def test_against_the_right_standard_day(self):
		"""Saturday is six hours here, so six hours on a Saturday is a whole
		man-day and six on a Monday is not."""
		sat = report.summarise_by_day([row(work_date=SATURDAY, hours=6)])
		mon = report.summarise_by_day([row(work_date=MONDAY, hours=6)])
		self.assertEqual(sat[0]["man_days"], 1.0)
		self.assertEqual(mon[0]["man_days"], 0.75)

	def test_no_hours_recorded_is_a_whole_day(self):
		"""Which is what every row written before the field existed means."""
		out = report.summarise_by_day([row(hours=None)])
		self.assertEqual(out[0]["man_days"], 1.0)

	def test_nothing_in_nothing_out(self):
		self.assertEqual(report.summarise_by_day([]), [])

	def test_the_summary_is_the_detail_added_up(self):
		"""The property that makes one report safe to serve both grains."""
		rows = [row(actual_quantity=5, amount=50, hours=8),
			row(actual_quantity=3, amount=30, hours=4),
			row(work_date=SATURDAY, actual_quantity=2, amount=20, hours=6)]
		out = report.summarise_by_day(rows)
		self.assertEqual(sum(r["actual_quantity"] for r in out),
			sum(r["actual_quantity"] for r in rows))
		self.assertEqual(sum(r["amount"] for r in out), sum(r["amount"] for r in rows))
		self.assertAlmostEqual(sum(r["man_days"] for r in out),
			sum(report._man_days(r) for r in rows), places=2)


class TestTheChart(unittest.TestCase):
	def test_it_plots_one_bar_per_day(self):
		chart = report.chart_for([row(), row(work_date=SATURDAY)], {}, daily=False)
		self.assertEqual(chart["type"], "bar")
		self.assertEqual(chart["data"]["labels"], [MONDAY, SATURDAY])

	def test_quantity_is_the_default(self):
		chart = report.chart_for([row(actual_quantity=5), row(actual_quantity=3)], {})
		self.assertEqual(chart["data"]["datasets"][0]["values"], [8.0])

	def test_the_dataset_is_switchable(self):
		rows = [row(actual_quantity=5, amount=50, hours=4)]
		self.assertEqual(
			report.chart_for(rows, {"dataset": "amount"})["data"]["datasets"][0]["values"],
			[50.0])
		self.assertEqual(
			report.chart_for(rows, {"dataset": "mandays"})["data"]["datasets"][0]["values"],
			[0.5])

	def test_an_unknown_dataset_falls_back_to_quantity(self):
		chart = report.chart_for([row(actual_quantity=5)], {"dataset": "nonsense"})
		self.assertEqual(chart["data"]["datasets"][0]["values"], [5.0])

	def test_the_dataset_is_named_on_the_series(self):
		chart = report.chart_for([row()], {"dataset": "amount"})
		self.assertIn("Amount", chart["data"]["datasets"][0]["name"])

	def test_money_is_formatted_as_money(self):
		self.assertEqual(report.chart_for([row()], {"dataset": "amount"})["fieldtype"],
			"Currency")
		self.assertEqual(report.chart_for([row()], {"dataset": "qty"})["fieldtype"], "Float")

	def test_no_rows_means_no_chart(self):
		"""Rather than an empty frame, which reads as a broken chart."""
		self.assertIsNone(report.chart_for([], {}))

	def test_it_sums_the_same_way_at_either_grain(self):
		"""The bars must not move when the table's grain changes."""
		rows = [row(actual_quantity=5), row(actual_quantity=3),
			row(work_date=SATURDAY, actual_quantity=2)]
		detail = report.chart_for(rows, {}, daily=False)
		summary = report.chart_for(report.summarise_by_day(rows), {}, daily=True)
		self.assertEqual(detail["data"]["labels"], summary["data"]["labels"])
		self.assertEqual(detail["data"]["datasets"][0]["values"],
			summary["data"]["datasets"][0]["values"])

	def test_man_days_sum_correctly_at_either_grain(self):
		"""The one dataset that is a ratio rather than a column."""
		rows = [row(hours=4), row(hours=4), row(work_date=SATURDAY, hours=6)]
		detail = report.chart_for(rows, {"dataset": "mandays"}, daily=False)
		summary = report.chart_for(report.summarise_by_day(rows),
			{"dataset": "mandays"}, daily=True)
		self.assertEqual(detail["data"]["datasets"][0]["values"],
			summary["data"]["datasets"][0]["values"])


class TestTheReportServesBothGrains(unittest.TestCase):
	def test_execute_returns_a_chart(self):
		"""Frappe reads the fourth return value as the chart."""
		src = read("worker_task_day.py")
		self.assertIn("return _columns(), rows, None, chart_for(", src)
		self.assertIn("return _summary_columns(), summary, None, chart_for(", src)

	def test_the_grouping_is_a_filter(self):
		src = read("worker_task_day.py")
		self.assertIn('filters.get("group_by")', src)

	def test_the_summary_is_rolled_up_rather_than_re_queried(self):
		"""A second query is a second thing to keep in step."""
		src = read("worker_task_day.py")
		at = src.index('if str(filters.get("group_by")')
		block = src[at:at + 400]
		self.assertIn("summarise_by_day(rows)", block)
		self.assertNotIn("frappe.db.sql", block)

	def test_the_detail_grain_is_unchanged(self):
		src = read("worker_task_day.py")
		self.assertIn("return _columns(), rows, None,", src)

	def test_the_summary_has_its_own_columns(self):
		names = [c["fieldname"] for c in report.SUMMARY_COLUMNS]
		for field in ("work_date", "workers", "tasks", "actual_quantity",
				"man_days", "amount"):
			with self.subTest(field=field):
				self.assertIn(field, names)

	def test_the_summary_columns_are_translated(self):
		self.assertTrue(all("label" in c for c in report._summary_columns()))

	def test_both_filters_are_offered(self):
		js = read("worker_task_day.js")
		self.assertIn('fieldname: "group_by"', js)
		self.assertIn('fieldname: "dataset"', js)

	def test_detail_is_the_default_grouping(self):
		"""Nobody's existing view changes when this ships."""
		js = read("worker_task_day.js")
		at = js.index('fieldname: "group_by"')
		self.assertIn('default: "Detail"', js[at:at + 500])

	def test_the_three_datasets_are_offered(self):
		js = read("worker_task_day.js")
		at = js.index('fieldname: "dataset"')
		block = js[at:at + 500]
		for value in ("qty", "amount", "mandays"):
			with self.subTest(value=value):
				self.assertIn('value: "%s"' % value, block)

	def test_the_offered_datasets_are_the_ones_the_server_knows(self):
		js = read("worker_task_day.js")
		at = js.index('fieldname: "dataset"')
		block = js[at:at + 500]
		for key in report.DATASETS:
			with self.subTest(key=key):
				self.assertIn('value: "%s"' % key, block)

	def test_it_is_still_a_script_report(self):
		"""Which is where the excel export and the print view come from."""
		meta = json.loads(read("worker_task_day.json"))
		self.assertEqual(meta["report_type"], "Script Report")


if __name__ == "__main__":
	unittest.main()
