// Copyright (c) 2026, Upande Ltd and contributors
// For license information, please see license.txt

/* global frappe */

frappe.query_reports["Worker Task Day"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "farm",
			label: __("Farm"),
			fieldtype: "Link",
			options: "Farm",
		},
		{
			fieldname: "employee",
			label: __("Worker"),
			fieldtype: "Link",
			options: "Employee",
		},
		{
			fieldname: "task",
			label: __("Task"),
			fieldtype: "Link",
			options: "Task",
		},
		{
			// THE SAME REPORT IS THE DAILY SUMMARY. A second report would be a
			// second thing to keep in step with this one, and it would drift the
			// first time a column changed here and not there. The rows are the
			// same rows either way -- the summary is them, added up.
			fieldname: "group_by",
			label: __("Group by"),
			fieldtype: "Select",
			options: [
				{ value: "Detail", label: __("Detail — one row per worker, task and day") },
				{ value: "Daily summary", label: __("Daily summary — one row per day") },
			],
			default: "Detail",
		},
		{
			// What the bars plot. Quantity is what the report is named for; the
			// other two answer the next two questions anybody asks of it.
			fieldname: "dataset",
			label: __("Chart shows"),
			fieldtype: "Select",
			options: [
				{ value: "qty", label: __("Actual quantity") },
				{ value: "amount", label: __("Amount (KES)") },
				{ value: "mandays", label: __("Man-days") },
			],
			default: "qty",
		},
		{
			// Confirmed only by default: this report is payroll-adjacent, and
			// quantities still moving through approval would mislead whoever
			// reads it as a record of what happened.
			fieldname: "include_pending",
			label: __("Include actuals still awaiting approval"),
			fieldtype: "Check",
			default: 0,
		},
	],

	onload: function (report) {
		// Said once, where it cannot be missed, because an empty Clock out cell
		// is the report's most confusing feature and the explanation is not
		// something a reader can work out: almost nobody scans out.
		report.page.add_inner_message(
			__("Clock-out shows only where an out-scan exists — most days have an in-scan only, and a blank means no scan was recorded rather than a departure at midnight.")
		);
	},

	formatter: function (value, row, column, data, default_formatter) {
		var out = default_formatter(value, row, column, data);
		if (!data) return out;
		// The summary grouping has none of the columns below -- no clock, no
		// achieved percentage -- so nothing here applies to it.

		// A missing clock reads as an explicit dash, not an empty cell: blank
		// looks like a rendering fault, "—" reads as "nothing was recorded".
		if ((column.fieldname === "clock_in" || column.fieldname === "clock_out") && !value) {
			return '<span style="color:var(--text-muted)">&mdash;</span>';
		}

		// Against the target for the hours actually given, so a half day meeting
		// half the target reads as on target rather than as underperformance.
		if (column.fieldname === "achieved_pct" && value) {
			if (value >= 100) return '<span style="color:var(--green-600)">' + out + "</span>";
			if (value < 60) return '<span style="color:var(--red-600)">' + out + "</span>";
		}

		return out;
	},
};
