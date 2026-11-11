// Copyright (c) 2026, Upande Ltd and contributors
// For license information, please see license.txt

// The greenhouse a plan budgets is one of its farm's locations -- the same
// Warehouses the planner's block picker offers (custom_farm), groups included,
// since a greenhouse that holds blocks is a group.
frappe.ui.form.on("Work Management Master Plan", {
	setup(frm) {
		frm.set_query("greenhouse", () => ({
			filters: { custom_farm: frm.doc.farm || "", disabled: 0 },
		}));
	},
	farm(frm) {
		// a greenhouse on the previous farm is not this farm's
		if (frm.doc.greenhouse) frm.set_value("greenhouse", "");
	},
});
