// Copyright (c) 2026, Upande Ltd and contributors
// For license information, please see license.txt

// Task pay breakdown (Excel) for a date range of Kaitet payrolls.
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

frappe.ui.form.on("Payroll Entry", {
	refresh(frm) {
		if (frm.doc.company === "Kaitet Ltd." && frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Download pay breakdown"), () =>
				window.work_management_pay_breakdown(frm.doc.start_date, frm.doc.end_date)
			);
		}
	},
});
