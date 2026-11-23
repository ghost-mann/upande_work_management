# Work Management -- DUPLICATE WORKER-DAY REPORT (read-only)
#
# Paste into System Console (desk: /app/system-console, "Execute"). Sandbox-safe:
# SELECTs only, no def, no imports, nothing written. DRY_RUN is here for the
# house style and changes nothing -- there is no write path in this script.
#
# Lists, by worker and date, every captured day the pipeline will pay or has
# paid (every state except Rejected) that day_guard now refuses or flags:
#
#   SAME WORK TWICE   same worker + date on the same assignment, or on the same
#                     task and block, in more than one row. At stake: everything
#                     beyond the largest single copy.
#   OVER THE CEILING  hour-based rows (plan UOM Hours) adding up to more than
#                     MAX_HOURS on one date. At stake: the pay for the hours over
#                     the ceiling, at the row's own average.
#   OVER ONE STANDARD sum of qty / daily_target above 1 on one date (8 h + 1 bed).
#                     Flagged, not refused: may be a real split day. Shown with
#                     the day's total, not an "excess".
#
# Narrow the window with FROM_DATE / TO_DATE (None = everything).

DRY_RUN = True
FROM_DATE = None          # e.g. "2026-10-01"
TO_DATE = None            # e.g. "2026-11-30"
MAX_HOURS = 8
HOURLY = ("hour", "hours", "hr", "hrs")
SHOW = 300

cond = "ac.workflow_state != 'Rejected' AND we.actual_quantity > 0"
params = []
if FROM_DATE:
    cond = cond + " AND we.work_date >= %s"
    params.append(FROM_DATE)
if TO_DATE:
    cond = cond + " AND we.work_date <= %s"
    params.append(TO_DATE)

rows = frappe.db.sql("""
    SELECT we.name row_name, we.employee, we.employee_name, we.work_date d,
           we.actual_quantity qty, IFNULL(we.amount, 0) amount, IFNULL(we.paid, 0) paid,
           ac.name doc, ac.workflow_state state, ac.assignment,
           COALESCE(ac.task, a.task) task, COALESCE(ac.block_section, a.block_section) block,
           p.uom, p.daily_target
    FROM `tabWork Actuals Employee` we
    INNER JOIN `tabWork Management Actuals` ac ON we.parent = ac.name
    LEFT JOIN `tabWork Management Assigner` a ON ac.assignment = a.name
    LEFT JOIN `tabWork Management Planner` p ON p.name = COALESCE(ac.planner_request, a.planner_request)
    WHERE """ + cond + """
    ORDER BY we.work_date, we.employee, ac.name
""", tuple(params), as_dict=True)

by_day = {}
for r in rows:
    by_day.setdefault((r.employee, str(r.d)), []).append(r)

dups = []
hours = []
multi = []
for k in sorted(by_day.keys(), key=lambda x: (x[1], x[0])):
    day = by_day[k]
    name = day[0].employee_name or k[0]
    # same work twice: group by assignment, and by task + block
    groups = {}
    for r in day:
        if r.assignment:
            groups.setdefault(("assignment", r.assignment), []).append(r)
        if r.task:
            groups.setdefault(("task+block", str(r.task) + " / " + str(r.block or "-")), []).append(r)
    seen_rows = {}
    for g in groups:
        grp = groups[g]
        if len(grp) < 2:
            continue
        sig = ",".join(sorted([x.row_name for x in grp]))
        if seen_rows.get(sig):
            continue
        seen_rows[sig] = 1
        total = sum([frappe.utils.flt(x.amount) for x in grp])
        keep = max([frappe.utils.flt(x.amount) for x in grp])
        dups.append({"date": k[1], "employee": k[0], "name": name, "by": g[0], "what": g[1],
            "docs": ", ".join([x.doc + " (" + str(x.state) + (", paid" if x.paid else "") + ", " +
                str(frappe.utils.flt(x.qty)) + ")" for x in grp]),
            "total": total, "excess": total - keep})
    # hours over the ceiling
    hrows = [r for r in day if str(r.uom or "").strip().lower() in HOURLY]
    htot = sum([frappe.utils.flt(r.qty) for r in hrows])
    if htot > MAX_HOURS + 0.005:
        hamt = sum([frappe.utils.flt(r.amount) for r in hrows])
        hours.append({"date": k[1], "employee": k[0], "name": name, "hours": htot,
            "docs": ", ".join([r.doc + " (" + str(frappe.utils.flt(r.qty)) + " h)" for r in hrows]),
            "total": hamt, "excess": hamt * (htot - MAX_HOURS) / htot})
    # more than one day's standard
    share = 0
    for r in day:
        if frappe.utils.flt(r.daily_target) > 0:
            share = share + frappe.utils.flt(r.qty) / frappe.utils.flt(r.daily_target)
    if share > 1.005:
        multi.append({"date": k[1], "employee": k[0], "name": name, "share": share,
            "docs": ", ".join([r.doc + " (" + str(r.task) + " " + str(frappe.utils.flt(r.qty)) + " " +
                str(r.uom or "") + ")" for r in day]),
            "total": sum([frappe.utils.flt(r.amount) for r in day])})

print("DUPLICATE WORKER-DAY REPORT  (read-only; DRY_RUN=" + str(DRY_RUN) + ")")
print("window: " + str(FROM_DATE or "start") + " -> " + str(TO_DATE or "end") +
      " | rows scanned: " + str(len(rows)))
print("")
print("== SAME WORK TWICE (refused from now on): " + str(len(dups)) + " worker-days, KES " +
      str(round(sum([x["excess"] for x in dups]), 2)) + " beyond one copy ==")
for x in dups[:SHOW]:
    print(x["date"] + " | " + x["name"] + " (" + x["employee"] + ") | same " + x["by"] + " " +
          x["what"] + " | KES " + str(round(x["total"], 2)) + ", excess " +
          str(round(x["excess"], 2)) + " | " + x["docs"])
print("")
print("== HOURS OVER " + str(MAX_HOURS) + " (refused from now on): " + str(len(hours)) +
      " worker-days, KES " + str(round(sum([x["excess"] for x in hours]), 2)) + " for hours over ==")
for x in hours[:SHOW]:
    print(x["date"] + " | " + x["name"] + " (" + x["employee"] + ") | " + str(x["hours"]) +
          " h | KES " + str(round(x["total"], 2)) + ", over-ceiling " + str(round(x["excess"], 2)) +
          " | " + x["docs"])
print("")
print("== MORE THAN ONE DAY'S STANDARD (flagged): " + str(len(multi)) + " worker-days, KES " +
      str(round(sum([x["total"] for x in multi]), 2)) + " on those days ==")
for x in multi[:SHOW]:
    print(x["date"] + " | " + x["name"] + " (" + x["employee"] + ") | " +
          str(round(x["share"], 2)) + " standards | KES " + str(round(x["total"], 2)) + " | " + x["docs"])
