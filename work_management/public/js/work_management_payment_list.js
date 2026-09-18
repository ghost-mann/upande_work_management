// Copyright (c) 2026, Upande Ltd and contributors
// For license information, please see license.txt

// Frappe hides the native bulk Cancel entirely once a doctype has a workflow
// (list_view.js checks !frappe.model.has_workflow before offering it) - the
// workflow's own transitions are meant to be the only path to Cancelled, and
// letting a raw docstatus cancel bypass that would skip on_payment_update()'s
// cleanup (freeing actuals rows, cancelling the linked Additional Salary).
// This calls that same plain-save path server-side, just looped over the
// selection, so Cancel belongs in the Actions menu without reimplementing
// the rule - see work_management_payment.py's bulk_cancel().
frappe.listview_settings["Work Management Payment"] =
	frappe.listview_settings["Work Management Payment"] || {};

Object.assign(frappe.listview_settings["Work Management Payment"], {
	onload(listview) {
		listview.page.add_actions_menu_item(
			__("Cancel"),
			() => {
				const docnames = listview.get_checked_items(true);
				if (!docnames.length) return;
				frappe.confirm(
					__("Cancel {0} payment(s)? Anyone already Cancelled is left as-is.", [
						docnames.length,
					]),
					() => {
						frappe.call({
							method:
								"work_management.work_management.doctype.work_management_payment.work_management_payment.bulk_cancel",
							args: { docnames },
							freeze: true,
							freeze_message: __("Cancelling..."),
						}).then((r) => {
							const { cancelled, skipped } = r.message || {};
							listview.clear_checked_items();
							listview.refresh();
							if (skipped && skipped.length) {
								frappe.msgprint({
									title: __("Some payments were skipped"),
									indicator: "orange",
									message: skipped
										.map((s) => `${s.name}: ${s.reason}`)
										.join("<br>"),
								});
							}
							if (cancelled && cancelled.length) {
								frappe.show_alert({
									message: __("{0} payment(s) cancelled", [cancelled.length]),
									indicator: "green",
								});
							}
						});
					}
				);
			},
			false
		);
	},
});
