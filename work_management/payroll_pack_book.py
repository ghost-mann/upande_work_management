"""The payroll approval pack, worked out from plain rows.

Approvers are asked to release a Payroll Entry on the strength of one headline
figure, with nothing to show who is in it or what they did. This module turns
the rows behind that figure -- the Work Management pay lines, the salary slips
they landed on, and the calendar days each person worked -- into a pack: one row
per worker, the detail lines, a per-task rollup, and a list of checks for the
people an approver should look at twice.

It takes plain dicts and returns plain dicts, with no frappe import, so the rules
can be tested without a site. Loading the rows and rendering them to
Excel or email live elsewhere.

Two figures are kept apart on purpose. `slip_amount` is what payroll will pay;
`wm_amount` is what the work lines add up to. When they differ that is a check,
not something to quietly pick between.
"""

import datetime
import io
from html import escape

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

CENT = 0.01
MONEY = "#,##0.00"
DATE = "yyyy-mm-dd"


def _money(value):
	return round(float(value or 0), 2)


def _farm_key(worker):
	"""Workers with no farm (paid with no work behind it) sort last."""
	farms = worker["farms"]
	return (not farms, farms[0] if farms else "", worker["employee_name"] or "", worker["employee"])


def build_pack(entries, lines, slips, days_by_employee, days_by_employee_farm=None):
	"""Everything an approver needs, from the rows behind a payroll entry.

	`days_by_employee_farm` ({(employee, farm): distinct work days on that farm})
	is optional; it only matters to filter_farm, which must not show a farm
	manager a person's days or pay on another farm.
	"""
	names = {}
	for row in list(lines) + list(slips):
		if row.get("employee_name") and row["employee"] not in names:
			names[row["employee"]] = row["employee_name"]

	by_line = {}
	for row in lines:
		by_line.setdefault(row["employee"], []).append(row)

	slip_amount, slip_names, employees = {}, {}, []
	for row in slips:
		emp = row["employee"]
		if emp not in slip_amount:
			employees.append(emp)
			slip_names[emp] = set()
		slip_amount[emp] = slip_amount.get(emp, 0) + (row.get("wm_amount") or 0)
		slip_names[emp].add(row["slip"])
	# Anyone with lines but no slip in this pack is still worth showing.
	for emp in by_line:
		if emp not in slip_amount:
			employees.append(emp)
			slip_amount[emp] = 0
			slip_names[emp] = set()

	workers, checks = [], []
	for emp in employees:
		own = by_line.get(emp, [])
		wm = _money(sum(r.get("amount") or 0 for r in own))
		paid = _money(slip_amount[emp])
		diff = _money(paid - wm)
		worker_checks = []
		if not own:
			worker_checks.append(("no_work", "Paid on a salary slip with no Work Management work behind it"))
		elif abs(paid - wm) >= CENT:
			worker_checks.append(("amount_mismatch", f"Slip {paid:,.2f} against work {wm:,.2f}"))
		if len(slip_names[emp]) > 1:
			worker_checks.append(("two_slips", "On salary slips " + ", ".join(sorted(slip_names[emp]))))
		name = names.get(emp, "")
		for kind, detail in worker_checks:
			checks.append({"employee": emp, "employee_name": name, "kind": kind, "detail": detail})
		workers.append({
			"employee": emp, "employee_name": name,
			"farms": sorted({r["farm"] for r in own if r.get("farm")}),
			"days_worked": days_by_employee.get(emp, 0),
			"tasks": len({(r.get("farm"), r.get("task")) for r in own}),
			"wm_amount": wm, "slip_amount": paid, "difference": diff,
			"flag": ", ".join(kind for kind, _ in worker_checks),
		})
	workers.sort(key=_farm_key)

	by_task = {}
	for row in lines:
		g = by_task.setdefault((row.get("farm"), row.get("task")),
			{"farm": row.get("farm"), "task": row.get("task"), "_w": set(), "days": 0, "qty": 0, "amount": 0})
		g["_w"].add(row["employee"])
		g["days"] += row.get("days") or 0
		g["qty"] += row.get("qty") or 0
		g["amount"] += row.get("amount") or 0
	task_rows = []
	for key in sorted(by_task, key=lambda k: (k[0] or "", k[1] or "")):
		g = by_task[key]
		task_rows.append({"farm": g["farm"], "task": g["task"], "workers": len(g["_w"]),
			"days": g["days"], "qty": g["qty"], "amount": _money(g["amount"])})

	entry_rows = []
	for entry in entries:
		own = [r for r in slips if r["entry"] == entry["name"]]
		entry_rows.append({**entry, "workers": len({r["employee"] for r in own}),
			"amount": _money(sum(r.get("wm_amount") or 0 for r in own))})

	return {"entries": entry_rows, "workers": workers, "detail": [dict(r) for r in lines],
		"by_task": task_rows, "checks": checks,
		"totals": _totals(workers, lines, _money(sum(slip_amount.values()))),
		"days_by_employee": dict(days_by_employee),
		"days_by_employee_farm": dict(days_by_employee_farm or {}),
		"wmpay_entry": {r["wmpay"]: r["entry"] for r in slips if r.get("wmpay")}}


def _totals(workers, lines, slip_total):
	by_farm = {}
	for row in lines:
		g = by_farm.setdefault(row.get("farm"), {"_w": set(), "days": 0, "amount": 0})
		g["_w"].add(row["employee"])
		g["days"] += row.get("days") or 0
		g["amount"] += row.get("amount") or 0
	return {
		"workers": len(workers),
		"man_days": sum(w["days_worked"] or 0 for w in workers),
		"slip_total": slip_total,
		"line_total": _money(sum(r.get("amount") or 0 for r in lines)),
		"by_farm": {farm: {"workers": len(g["_w"]), "days": g["days"], "amount": _money(g["amount"])}
			for farm, g in by_farm.items()},
	}


def filter_farm(pack, farm):
	"""The same pack cut down to one farm, for that farm's manager.

	Nothing about another farm may be readable here, because a manager could
	subtract it from a whole-person figure. A worker on two farms therefore gets
	a row rebuilt from this farm's lines alone, with the slip figures (which are
	per person, not per farm) left None, and no checks, which quote those figures.
	The headline is the farm's own line total.
	"""
	detail = [r for r in pack["detail"] if r.get("farm") == farm]
	mine = {}
	for r in detail:
		mine.setdefault(r["employee"], []).append(r)
	per_farm_days = pack.get("days_by_employee_farm") or {}
	whole_days = pack.get("days_by_employee") or {}
	workers, sole = [], set()
	for w in pack["workers"]:
		own = mine.get(w["employee"])
		if not own:
			continue
		if w["farms"] == [farm]:
			sole.add(w["employee"])
			row = dict(w)
			row["days_worked"] = per_farm_days.get((w["employee"], farm), whole_days.get(w["employee"], w["days_worked"]))
		else:
			row = {**w, "farms": [farm], "tasks": len({r.get("task") for r in own}),
				"wm_amount": _money(sum(r.get("amount") or 0 for r in own)),
				"days_worked": per_farm_days.get((w["employee"], farm)),
				"slip_amount": None, "difference": None, "flag": None}
		workers.append(row)
	totals = _totals(workers, detail, 0)
	totals["man_days"] = sum(w["days_worked"] for w in workers if w["days_worked"] is not None)
	totals["slip_total"] = totals["line_total"]
	wmpay_entry = pack.get("wmpay_entry") or {}
	entries = []
	for e in pack["entries"]:
		rows = [r for r in detail if wmpay_entry.get(r.get("wmpay")) == e["name"]]
		if rows:
			entries.append({k: v for k, v in e.items() if k not in ("workers", "amount")}
				| {"workers": len({r["employee"] for r in rows}),
				"amount": _money(sum(r.get("amount") or 0 for r in rows))})
	return {"entries": entries, "workers": workers, "detail": detail,
		"by_task": [r for r in pack["by_task"] if r["farm"] == farm],
		"checks": [c for c in pack["checks"] if c["employee"] in sole], "totals": totals}


def farms_in(pack):
	return sorted({r["farm"] for r in pack["detail"] if r.get("farm")})


CHECK_LABELS = {
	"no_work": "Paid with no work behind it",
	"amount_mismatch": "Slip and work amounts differ",
	"two_slips": "On more than one slip",
}

# (heading, getter, kind) where kind is "money", "date" or None.
_SHEETS = [
	("Payrolls", "entries", [
		("Payroll Entry", lambda r: r["name"], None), ("From", lambda r: r["start_date"], "date"),
		("To", lambda r: r["end_date"], "date"), ("State", lambda r: r.get("workflow_state"), None),
		("Workers", lambda r: r["workers"], None), ("KES", lambda r: r["amount"], "money")]),
	("Workers", "workers", [
		("Employee ID", lambda r: r["employee"], None), ("Name", lambda r: r["employee_name"], None),
		("Farm(s)", lambda r: ", ".join(r["farms"]), None), ("Days worked", lambda r: r["days_worked"], None),
		("Tasks", lambda r: r["tasks"], None), ("WM amount", lambda r: r["wm_amount"], "money"),
		("Slip amount", lambda r: r["slip_amount"], "money"), ("Difference", lambda r: r["difference"], "money"),
		("Flag", lambda r: r["flag"], None)]),
	("Detail", "detail", [
		("Employee ID", lambda r: r["employee"], None), ("Name", lambda r: r["employee_name"], None),
		("Farm", lambda r: r.get("farm"), None), ("Task", lambda r: r.get("task"), None),
		("Block", lambda r: r.get("block"), None), ("Work from", lambda r: r.get("work_from"), "date"),
		("Work to", lambda r: r.get("work_to"), "date"), ("Days", lambda r: r.get("days"), None),
		("Qty", lambda r: r.get("qty"), None), ("Rate", lambda r: r.get("rate"), "money"),
		("Amount", lambda r: r.get("amount"), "money"), ("Entered by", lambda r: r.get("entered_by"), None),
		("FM approved by", lambda r: r.get("fm_approved_by"), None),
		("HR approved by", lambda r: r.get("hr_approved_by"), None),
		("GM approved by", lambda r: r.get("gm_approved_by"), None), ("WMPAY", lambda r: r.get("wmpay"), None)]),
	("By task", "by_task", [
		("Farm", lambda r: r["farm"], None), ("Task", lambda r: r["task"], None),
		("Workers", lambda r: r["workers"], None), ("Days", lambda r: r["days"], None),
		("Qty", lambda r: r["qty"], None), ("KES", lambda r: r["amount"], "money")]),
	("Checks", "checks", [
		("Employee ID", lambda r: r["employee"], None), ("Name", lambda r: r["employee_name"], None),
		("Check", lambda r: CHECK_LABELS.get(r["kind"], r["kind"]), None), ("Detail", lambda r: r["detail"], None)]),
]


def _as_date(value):
	if isinstance(value, str):
		try:
			return datetime.date.fromisoformat(value[:10])
		except ValueError:
			return value
	return value


def workbook_bytes(pack):
	"""The pack as an Excel file. Only the five named sheets are written, so the
	pack's internal keys (days_by_employee and friends) can never leak into it.
	None is left as an empty cell: in a farm pack it means "not shown", not zero."""
	wb = Workbook()
	wb.remove(wb.active)
	for title, key, columns in _SHEETS:
		ws = wb.create_sheet(title)
		ws.append([name for name, _, _ in columns])
		for cell in ws[1]:
			cell.font = Font(bold=True)
		for row in pack[key]:
			ws.append([_as_date(get(row)) if kind == "date" else get(row) for _, get, kind in columns])
		for i, (name, _, kind) in enumerate(columns, 1):
			ws.column_dimensions[get_column_letter(i)].width = max(12, len(name) + 4)
			if kind:
				for (cell,) in ws.iter_rows(min_row=2, min_col=i, max_col=i):
					cell.number_format = MONEY if kind == "money" else DATE
		if key == "checks" and not pack[key]:
			ws["A2"] = "No problems found."
		ws.freeze_panes = "A2"
		ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{max(ws.max_row, 2)}"
	out = io.BytesIO()
	wb.save(out)
	return out.getvalue()


def attachment_name(start, end, farm=None):
	name = f"Task-pay-{start}-to-{end}"
	return f"{name}-{farm}.xlsx" if farm else f"{name}.xlsx"


def subject(entry_name, total, revised=False, farm=None, test=False):
	parts = ["Task pay for approval", entry_name] + ([farm] if farm else []) + [f"KES {total:,.0f}"]
	return ("TEST: " if test else "") + ("Revised: " if revised else "") + " \u2014 ".join(parts)


def email_html(pack, entry_name, entry_url, farm=None, farms_without_fm=()):
	"""A short summary, never a per-worker table: Gmail clips mail at about
	100KB and the detail is in the attachment. Every value is escaped."""
	e = escape
	t = pack["totals"]
	starts = [str(x["start_date"]) for x in pack["entries"]]
	ends = [str(x["end_date"]) for x in pack["entries"]]
	period = f"{min(starts)} to {max(ends)}" if starts else ""
	cell = "padding:2px 12px 2px 0;"
	out = ['<div style="font-family:Arial,sans-serif;font-size:14px;color:#222;">']
	out.append(f"<p>{e(entry_name)}{' \u2014 ' + e(farm) if farm else ''}<br>Period: {e(period)}</p>")
	out.append(f'<p style="margin:0;">Workers: <b>{t["workers"]:,}</b><br>'
		f'Man-days: <b>{t["man_days"]:,}</b><br>Total: <b>KES {t["slip_total"]:,.0f}</b></p>')
	if abs(t["slip_total"] - t["line_total"]) >= CENT:
		out.append(f'<p style="margin:8px 0 0;">Work lines add up to KES {t["line_total"]:,.0f}; '
			f'difference KES {t["slip_total"] - t["line_total"]:,.0f}.</p>')
	n = len(pack["checks"])
	if n:
		out.append(f'<p style="color:#b00020;"><b>{n} problem{"s" if n != 1 else ""} found</b> '
			"\u2014 see the Checks sheet.</p>")
	else:
		out.append("<p>No problems found.</p>")
	if not farm and t["by_farm"]:
		out.append('<table style="border-collapse:collapse;margin:8px 0;">'
			f'<tr><th align="left" style="{cell}">Farm</th><th align="right" style="{cell}">Workers</th>'
			f'<th align="right" style="{cell}">Days</th><th align="right" style="{cell}">KES</th></tr>')
		for name in sorted(t["by_farm"], key=lambda k: k or ""):
			g = t["by_farm"][name]
			out.append(f'<tr><td style="{cell}">{e(name or "(no farm)")}</td>'
				f'<td align="right" style="{cell}">{g["workers"]:,}</td>'
				f'<td align="right" style="{cell}">{g["days"]:,.0f}</td>'
				f'<td align="right" style="{cell}">{g["amount"]:,.0f}</td></tr>')
		out.append("</table>")
	if farms_without_fm:
		out.append("<p>No farm manager is set up for: " + ", ".join(e(f) for f in farms_without_fm)
			+ ". They did not get a farm pack.</p>")
	out.append(f'<p><a href="{e(entry_url, quote=True)}">Open the Payroll Entry</a></p></div>')
	return "".join(out)


def farm_recipients(stage_rows, enabled):
	"""Farm managers by farm. A row with no scope would mean every farm, so it is
	skipped, as are other stages and users who are no longer enabled."""
	out = {}
	for row in stage_rows:
		if row["stage_label"] != "Actuals: Farm Manager" or not row.get("scope"):
			continue
		if row["user"] in enabled and row["user"] not in out.setdefault(row["scope"], []):
			out[row["scope"]].append(row["user"])
	return {farm: users for farm, users in out.items() if users}


def split_addresses(text):
	seen = []
	for part in (text or "").replace("\n", ",").split(","):
		part = part.strip()
		if part and part not in seen:
			seen.append(part)
	return seen
