# System Console (Python) script: day-rows whose amount does not follow their quantity.
#
# Paste into /app/system-console on the live site.
#
#   DRY_RUN = True   lists every Work Actuals Employee row where
#                        amount != round(qty x unit x multiplier, 2)
#                    (0 for a row outside payroll), and changes nothing.
#                    Leave "Commit" unticked.
#   DRY_RUN = False  re-prices the UNPAID rows of that list and re-sums their
#                    documents' totals. Tick "Commit" before Execute.
#
# The rule is the one the Actuals controller now applies on every save
# (work_management/actuals_pay.py), inlined because the console sandbox allows
# no imports:
#   unit       = the document's rate, snapped to the task's daily wage when
#                rate x daily_target lands within 1% of it without hitting it
#   multiplier = the row's stored holiday_multiplier, or 1 when none is stored
#                (rows written before public-holiday pay are judged by x1)
#   amount     = round(qty x unit x multiplier, 2) if count_in_payroll else 0
#
# A row is PAID if its own `paid` is ticked or its document's is. Paid rows are
# listed and never touched. A document whose rate is 0 is listed and not touched
# either: there is no rate to price it by, so a figure on it came from somewhere
# this script cannot second-guess.
#
# Restricted sandbox: no def, no import, no += on names, and no UPDATE through
# frappe.db / frappe.qb -- writes go through doc.db_set.

DRY_RUN = True
SHOW = 300          # rows printed per category; the counts cover all of them
TOL = 0.005

rows = frappe.db.sql("""
    SELECT we.name, we.parent, we.idx, we.employee, we.work_date,
           IFNULL(we.actual_quantity, 0) qty, IFNULL(we.amount, 0) amount,
           IFNULL(we.count_in_payroll, 0) in_pay, IFNULL(we.holiday_multiplier, 0) hol_x,
           IFNULL(we.paid, 0) row_paid, IFNULL(ac.paid, 0) doc_paid,
           IFNULL(ac.rate, 0) rate, ac.workflow_state, ac.docstatus,
           IFNULL(ac.planner_request, a2.planner_request) plan
    FROM `tabWork Actuals Employee` we
    INNER JOIN `tabWork Management Actuals` ac ON ac.name = we.parent
    LEFT JOIN `tabWork Management Assigner` a2 ON a2.name = ac.assignment
    WHERE we.parenttype = 'Work Management Actuals' AND ac.docstatus < 2
    ORDER BY we.parent, we.idx
""", as_dict=True)

# ---- unit value per (rate, plan): the wage snap ----------------------------
plan_names = list(set([r.plan for r in rows if r.plan]))
plan_info = {}
if plan_names:
    for p in frappe.db.sql("""
        SELECT name, IFNULL(daily_target, 0) daily_target, task, from_date
        FROM `tabWork Management Planner` WHERE name IN %(p)s
    """, {"p": tuple(plan_names)}, as_dict=True):
        plan_info[p.name] = p
wage_cache = {}
unit_cache = {}
for r in rows:
    key = str(r.rate) + "|" + str(r.plan or "")
    if key in unit_cache:
        continue
    rate = frappe.utils.flt(r.rate)
    unit = rate
    pi = plan_info.get(r.plan) if r.plan else None
    if pi and rate > 0 and frappe.utils.flt(pi.daily_target) > 0:
        day_wage = rate * frappe.utils.flt(pi.daily_target)
        wkey = str(pi.task or "") + "|" + str(pi.from_date or "")
        if wkey not in wage_cache:
            snap = 0
            if pi.task:
                w = frappe.db.sql("""
                    SELECT daily_wage_basis b FROM `tabWork Task Rate`
                    WHERE task = %(t)s AND derived = 1
                      AND valid_from <= %(d)s
                      AND (valid_to IS NULL OR valid_to >= %(d)s)
                    ORDER BY valid_from DESC LIMIT 1
                """, {"t": pi.task, "d": pi.from_date or frappe.utils.today()}, as_dict=True)
                if w and frappe.utils.flt(w[0].b) > 0:
                    snap = frappe.utils.flt(w[0].b)
            wage_cache[wkey] = snap or 340.0
        snap_wage = wage_cache[wkey]
        gap = abs(day_wage - snap_wage)
        if gap <= snap_wage * 0.01 and gap > 0.001:
            unit = snap_wage / frappe.utils.flt(pi.daily_target)
    unit_cache[key] = unit

# ---- compare ----------------------------------------------------------------
fix = []
paid_bad = []
no_rate = []
for r in rows:
    unit = unit_cache[str(r.rate) + "|" + str(r.plan or "")]
    mult = frappe.utils.flt(r.hol_x) or 1
    if frappe.utils.cint(r.in_pay):
        want = round(frappe.utils.flt(r.qty) * unit * mult, 2)
    else:
        want = 0
    have = frappe.utils.flt(r.amount)
    if abs(want - have) <= TOL:
        continue
    item = {"row": r.name, "doc": r.parent, "idx": r.idx, "employee": r.employee,
            "date": str(r.work_date), "qty": frappe.utils.flt(r.qty),
            "unit": round(unit, 6), "x": mult, "in_pay": frappe.utils.cint(r.in_pay),
            "amount": have, "should_be": want, "diff": round(have - want, 2),
            "state": r.workflow_state}
    if frappe.utils.cint(r.row_paid) or frappe.utils.cint(r.doc_paid):
        paid_bad.append(item)
    elif frappe.utils.flt(r.rate) <= 0 and frappe.utils.cint(r.in_pay):
        no_rate.append(item)
    else:
        fix.append(item)

total_fix = 0
for x in fix:
    total_fix = total_fix + x["diff"]
total_paid = 0
for x in paid_bad:
    total_paid = total_paid + x["diff"]

print("Scanned " + str(len(rows)) + " day-rows. DRY_RUN = " + str(DRY_RUN))
print("To re-price (unpaid): " + str(len(fix)) + " rows on "
      + str(len(set([x["doc"] for x in fix]))) + " documents; overstated by KES "
      + str(round(total_fix, 2)) + " net")
print("  of which qty = 0 with an amount: " + str(len([x for x in fix if x["qty"] == 0 and x["amount"]])))
print("  of which outside payroll with an amount: " + str(len([x for x in fix if not x["in_pay"]])))
print("PAID, reported only: " + str(len(paid_bad)) + " rows on "
      + str(len(set([x["doc"] for x in paid_bad]))) + " documents; KES "
      + str(round(total_paid, 2)) + " net")
print("No rate on the document, reported only: " + str(len(no_rate)) + " rows")

head = "doc | row# | employee | date | qty | unit | x | in_pay | amount -> should_be (diff) | state"
for label, lst in (("TO RE-PRICE", fix), ("PAID - NOT TOUCHED", paid_bad), ("NO RATE - NOT TOUCHED", no_rate)):
    if not lst:
        continue
    print("")
    print("== " + label + " (" + str(len(lst)) + ") ==")
    print(head)
    for x in lst[:SHOW]:
        print(x["doc"] + " | " + str(x["idx"]) + " | " + str(x["employee"]) + " | " + x["date"]
              + " | " + str(x["qty"]) + " | " + str(x["unit"]) + " | " + str(x["x"])
              + " | " + str(x["in_pay"]) + " | " + str(x["amount"]) + " -> " + str(x["should_be"])
              + " (" + str(x["diff"]) + ") | " + str(x["state"]))
    if len(lst) > SHOW:
        print("... " + str(len(lst) - SHOW) + " more")

# ---- apply ------------------------------------------------------------------
if not DRY_RUN and fix:
    # db_set: a direct column write, as the sandbox allows no UPDATE. It skips
    # the controller (which would re-price anyway) and writes no Version.
    for x in fix:
        frappe.get_doc("Work Actuals Employee", x["row"]).db_set(
            "amount", x["should_be"], update_modified=False)
    docs = list(set([x["doc"] for x in fix]))
    for dn in docs:
        t = frappe.db.sql("""
            SELECT COALESCE(SUM(actual_quantity), 0) q,
                   COALESCE(SUM(CASE WHEN IFNULL(count_in_payroll,0) = 1 THEN amount ELSE 0 END), 0) p,
                   COALESCE(SUM(CASE WHEN IFNULL(count_in_payroll,0) = 1 THEN actual_quantity ELSE 0 END), 0) tw,
                   COALESCE(SUM(CASE WHEN IFNULL(count_in_payroll,0) = 0 THEN actual_quantity ELSE 0 END), 0) sal,
                   COUNT(DISTINCT CASE WHEN actual_quantity > 0 THEN employee END) ppl,
                   COUNT(DISTINCT CASE WHEN IFNULL(count_in_payroll,0) = 1 AND actual_quantity > 0 THEN employee END) pp
            FROM `tabWork Actuals Employee` WHERE parent = %(d)s
        """, {"d": dn}, as_dict=True)[0]
        ad = frappe.get_doc("Work Management Actuals", dn)
        ad.db_set({
            "total_actual_qty": frappe.utils.flt(t.q),
            "total_payment": frappe.utils.flt(t.p),
            "custom_tw_qty": frappe.utils.flt(t.tw),
            "custom_salaried_qty": frappe.utils.flt(t.sal),
            "actual_people": frappe.utils.cint(t.ppl),
            "payroll_people": frappe.utils.cint(t.pp),
            "cost_variance": frappe.utils.flt(t.p) - frappe.utils.flt(ad.planned_cost),
        }, update_modified=False)
    print("")
    print("Re-priced " + str(len(fix)) + " rows and re-summed " + str(len(docs))
          + " documents. Saved only if Commit was ticked.")
