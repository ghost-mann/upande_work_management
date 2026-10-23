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

CENT = 0.01


def _money(value):
	return round(float(value or 0), 2)


def _farm_key(worker):
	"""Workers with no farm (paid with no work behind it) sort last."""
	farms = worker["farms"]
	return (not farms, farms[0] if farms else "", worker["employee_name"] or "", worker["employee"])


def build_pack(entries, lines, slips, days_by_employee):
	"""Everything an approver needs, from the rows behind a payroll entry."""
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
		"totals": _totals(workers, lines, _money(sum(slip_amount.values())))}


def _totals(workers, lines, slip_total):
	by_farm = {}
	for row in lines:
		g = by_farm.setdefault(row.get("farm"), {"_w": set(), "days": 0, "amount": 0})
		g["_w"].add(row["employee"])
		g["days"] += row.get("days") or 0
		g["amount"] += row.get("amount") or 0
	return {
		"workers": len(workers),
		"man_days": sum(w["days_worked"] for w in workers),
		"slip_total": slip_total,
		"line_total": _money(sum(r.get("amount") or 0 for r in lines)),
		"by_farm": {farm: {"workers": len(g["_w"]), "days": g["days"], "amount": _money(g["amount"])}
			for farm, g in by_farm.items()},
	}


def filter_farm(pack, farm):
	"""The same pack cut down to one farm, for that farm's manager.

	A worker on two farms appears in both packs, but only that farm's lines are
	shown. The headline here is the farm's own line total -- the slip total is
	per person, not per farm, so it cannot be split.
	"""
	detail = [r for r in pack["detail"] if r["farm"] == farm]
	staff = {r["employee"] for r in detail}
	workers = [w for w in pack["workers"] if w["employee"] in staff]
	totals = _totals(workers, detail, 0)
	totals["slip_total"] = totals["line_total"]
	return {"entries": pack["entries"], "workers": workers, "detail": detail,
		"by_task": [r for r in pack["by_task"] if r["farm"] == farm],
		"checks": [c for c in pack["checks"] if c["employee"] in staff], "totals": totals}


def farms_in(pack):
	return sorted({r["farm"] for r in pack["detail"] if r.get("farm")})
