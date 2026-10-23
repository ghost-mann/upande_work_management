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
