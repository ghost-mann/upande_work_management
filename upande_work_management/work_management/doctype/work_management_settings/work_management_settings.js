// Copyright (c) 2026, Upande Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on("Work Management Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Rate coverage"), () => wm_rates_call(frm, { action: "meta" },
			(r) => {
				frm.set_value("current_daily_wage", r.current_daily_wage || 0);
				wm_rates_show(__("Rate coverage"), [
					[__("Tasks with a rate"), r.tasks_with_rate],
					[__("Tasks covered by a period"), r.tasks_covered],
					[__("Rate periods"), r.periods],
					[__("Current daily wage"), r.current_daily_wage],
					[__("Borderline, awaiting a decision"), r.borderline_pending],
					[__("Last run"), r.last_run ? `${r.last_run.name} · ${r.last_run.status} · delta ${r.last_run.delta}` : __("none")],
				]);
			}), __("Rates"));

		frm.add_custom_button(__("Backfill history (dry run)"), () => wm_rates_call(frm,
			{ action: "backfill", dry_run: 1 },
			(r) => wm_rates_show(__("Backfill — dry run"), [
				[__("History would start"), r.epoch],
				[__("Tasks considered"), r.tasks_considered],
				[__("Periods that would be created"), r.periods_created],
				[__("Already covered"), r.already_covered],
				[__("Wage-derived"), r.classification.derived],
				[__("Borderline (need a decision)"), r.classification.borderline],
				[__("Not wage-derived"), r.classification.not_derived],
			], () => wm_rates_confirm(frm,
				__("Create {0} rate periods starting {1}?", [r.periods_created, r.epoch]),
				{ action: "backfill", dry_run: 0 }))
			), __("Rates"));

		frm.add_custom_button(__("Borderline tasks"), () => wm_rates_call(frm,
			{ action: "borderline" },
			(r) => {
				if (!r.borderline || !r.borderline.length) {
					frappe.msgprint(__("Nothing awaiting a classification decision."));
					return;
				}
				wm_rates_show(__("Borderline — decide once, recorded on the period"),
					r.borderline.map((b) => [
						b.task,
						__("{0} × {1} = {2}/day · {3} unpaid rows", [b.rate, b.daily_target, b.implied_daily_wage, b.rows_since_change]),
					]));
			}), __("Rates"));

		frm.add_custom_button(__("Recalculate (dry run)"), () => {
			if (!frm.doc.rate_recalc_from) {
				frappe.msgprint(__("Set <b>Recalculate From</b> first."));
				return;
			}
			wm_rates_call(frm, {
				action: "recalc",
				dry_run: 1,
				from_date: frm.doc.rate_recalc_from,
				to_date: frm.doc.rate_recalc_to || "",
				farm: frm.doc.rate_recalc_farm || "",
			}, (r) => {
				const rows = [
					[__("Rows examined"), r.rows_examined],
					[__("Rows that would change"), r.rows_to_change],
					[__("Current total"), r.old_total],
					[__("New total"), r.new_total],
					[__("Delta"), r.delta],
					[__("Already sent to accounts"), r.pending_accounts_rows],
				];
				(r.skipped || []).forEach((s) => rows.push([__("Skipped: {0}", [s.task]), `${s.rows} rows — ${s.why}`]));
				wm_rates_show(__("Recalculation — dry run"), rows, () => wm_rates_confirm(frm,
					__("Apply the new rates? {0} rows move by {1}. This writes to unpaid day-rows and rewrites {2} rows already sent to accounts.",
						[r.rows_to_change, r.delta, r.pending_accounts_rows]),
					{
						action: "recalc",
						dry_run: 0,
						from_date: frm.doc.rate_recalc_from,
						to_date: frm.doc.rate_recalc_to || "",
						farm: frm.doc.rate_recalc_farm || "",
					}));
			});
		}, __("Rates"));
	},
});

function wm_rates_call(frm, args, onOk) {
	frappe.call({
		method: "wm_rates",
		args: args,
		freeze: true,
		freeze_message: __("Working…"),
		callback: (res) => {
			const r = res.message || {};
			if (r.error) {
				frappe.msgprint({ title: __("Rates"), message: r.error, indicator: "red" });
				return;
			}
			onOk(r);
		},
	});
}

function wm_rates_show(title, rows, onApply) {
	const body = rows
		.map(([k, v]) => `<tr><td>${frappe.utils.escape_html(String(k))}</td>
			<td class="text-right"><b>${frappe.utils.escape_html(String(v === undefined || v === null ? "—" : v))}</b></td></tr>`)
		.join("");
	const d = new frappe.ui.Dialog({
		title: title,
		size: "large",
		primary_action_label: onApply ? __("Apply for real") : __("Close"),
		primary_action: () => {
			d.hide();
			if (onApply) onApply();
		},
	});
	d.$body.html(`<table class="table table-bordered"><tbody>${body}</tbody></table>`);
	d.show();
}

function wm_rates_confirm(frm, message, args) {
	frappe.confirm(message, () => {
		// chunked: keep calling until the server reports nothing remaining
		const step = (runName) => {
			wm_rates_call(frm, Object.assign({}, args, runName ? { run: runName } : {}), (r) => {
				if (r.remaining > 0) {
					frappe.show_alert({
						message: __("{0} rows applied, {1} to go…", [r.applied_now, r.remaining]),
						indicator: "blue",
					});
					step(r.run);
					return;
				}
				if (r.run) {
					frm.set_value("last_recalc_run", r.run);
					frm.set_value("last_recalc_on", frappe.datetime.now_datetime());
					frm.set_value("last_recalc_by", frappe.session.user);
					frm.set_value("last_recalc_summary",
						__("{0} rows, delta {1}", [r.applied_now || r.rows_to_change, r.delta]));
					frm.save();
				}
				frappe.msgprint({
					title: __("Done"),
					message: r.run
						? __("Run {0} applied. It can be reversed from the Work Rate Recalc Run list.", [r.run])
						: __("Applied."),
					indicator: "green",
				});
			});
		};
		step(null);
	});
}
