// Copyright (c) 2026, Upande Ltd and contributors
// For license information, please see license.txt

// Adds "Download pay breakdown" to the Payroll Entry list menu. hrms ships its
// own listview_settings for Payroll Entry, so extend them and chain onload.
// Shared with payroll_entry.js / payroll_entry_list.js; whichever loads first
// defines it. The server checks the range and read permission on every entry.
window.work_management_pay_breakdown =
	window.work_management_pay_breakdown ||
	function (from_date, to_date) {
		const d = new frappe.ui.Dialog({
			title: __("Download pay breakdown"),
			fields: [
				{ fieldname: "from_date", fieldtype: "Date", label: __("From"), reqd: 1, default: from_date },
				{ fieldname: "to_date", fieldtype: "Date", label: __("To"), reqd: 1, default: to_date },
			],
			primary_action_label: __("Download"),
			primary_action(values) {
				// The same rules as the server, checked here so a bad range shows
				// a message instead of opening a tab with an error page.
				const problem = !values.from_date || !values.to_date
					? __("Give both a From and a To date.")
					: values.from_date > values.to_date
						? __("From must be on or before To.")
						: frappe.datetime.get_day_diff(values.to_date, values.from_date) + 1 > 92
							? __("Pick at most {0} days.", [92])
							: null;
				if (problem) {
					frappe.msgprint({ title: __("Check the dates"), message: problem, indicator: "red" });
					return;
				}
				window.open(
					"/api/method/work_management.payroll_pack.download_breakdown?" + $.param(values)
				);
				d.hide();
			},
		});
		d.show();
	};

(function () {
	const base = frappe.listview_settings["Payroll Entry"] || {};
	const prev = base.onload;
	base.onload = function (listview) {
		prev && prev.call(this, listview);
		listview.page.add_menu_item(__("Download pay breakdown"), () =>
			window.work_management_pay_breakdown(
				frappe.datetime.add_days(frappe.datetime.get_today(), -27),
				frappe.datetime.get_today()
			)
		);
	};
	frappe.listview_settings["Payroll Entry"] = base;
})();
