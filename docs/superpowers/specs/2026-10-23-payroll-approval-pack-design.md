# Payroll approval pack (task pay breakdown email + button)

Date: 2026-10-23. Agreed in conversation with james@upande.com.

## Purpose

When a weekly Kaitet task-pay Payroll Entry goes to approval, the people who
approve it (Accounts, GM, Director, CFO) and HR should be able to see exactly
what each worker is being paid, for which days and for which tasks, before
they approve it. Farm managers should be able to confirm the figures for their
own workers. The decision this supports is **approving the payroll**, so the
pack must make wrong or unexplained amounts easy to spot. It is not just a
record.

## Background (live kaitet-group.upande.com, checked 2026-10-23)

- A `Work Management Payment` (WMPAY) covers **one worker**. Its `Work Payment
  Line` rows carry `actuals, employee, employee_name, farm, task, block,
  work_from, work_to, days, qty, rate, amount`, plus `assigned_by,
  entered_by, fm_approved_by, hr_approved_by, gm_approved_by`. Bulk "send to
  payroll" creates hundreds of WMPAYs at once, so a WMPAY is the wrong trigger.
- Each WMPAY raises one `Additional Salary` (`ref_doctype = "Work Management
  Payment"`, `ref_docname = WMPAY name`). HR then creates a weekly `Payroll
  Entry` ("Kaitet Task pay …"). Its Salary Slips pick up those Additional
  Salaries through `Salary Detail.additional_salary`. Example: 28 Sep–4 Oct
  2026 had 379 slips, all WM-linked, 1,284 payment lines, KES 711k, across
  Endebess 243 workers, Lokitela 78, Vale 57 and Saboti 1.
- Payroll Entry workflow for Kaitet Ltd.: Draft → (Create Salary Slips) →
  Pending HR Review → **(Send to Accounts) → Pending Accounts** → Pending GM →
  Pending Director → Pending CFO → Approved. Rejected → (Resubmit to Accounts)
  → Pending Accounts. The entry is at docstatus 1 from Pending HR Review on,
  and its slips are drafts.
- Five enabled Notifications ("Payroll Entry - …") already email each stage
  from notifications@karenroses.com to one static Cc list. **They stay
  untouched.**
- The monthly salaried payroll (e.g. "Kaitet September 2026 Payroll") has no
  WM-linked slips. Karen Roses has its own workflow.

## Decisions (the user's)

1. **Trigger: one separate "approval pack" email**, sent when a Kaitet task-pay
   Payroll Entry enters **Pending Accounts**, in addition to the existing stage
   notifications. It is not sent at every stage.
2. **Plus a "Download pay breakdown" button** on the Payroll Entry form, so a
   later approver can pull the current figures instead of searching their inbox.
3. **Farm managers get a separate email containing only their own farm's
   workers.** Everyone else gets the full pack.

## Recipients

- **Full pack (To):** the non-Upande people on the existing payroll Cc list:
  bob@karenroses.com, hro@endebesscoffee.com (HR), peter@endebesscoffee.com
  (Director), pkanda@endebesscoffee.com (Accounts / Payroll Verifier) and
  koskey@lokitelaorchards.com (GM), plus ibett@karenroses.com (CFO).
  **Bcc:** austin@, jeniffer@ and teresia@upande.com. *(My call: the list is
  stored as a Work Management Settings field, a newline list, so it can be
  edited without a deploy. It is seeded with these addresses. It is a fixed
  list, not role-based, because role holders include Upande staff the user
  asked to keep off payroll mail.)*
- **Farm packs:** one email per farm present in the payroll, sent to the
  enabled users on `Work Management Settings.stage_approvers` with
  `stage_label = "Actuals: Farm Manager"` and `scope = <farm>`. Today that is
  Endebess: tarus@, guchu@; Lokitela: pkatule@, bramuel@, ewachira@; Vale:
  kibett@; Saboti: ogola@ and pkatule@ (acting). Rows with no scope (the GM)
  are skipped, since the GM already gets the full pack. A farm with no FM rows
  gets no farm email, and the full-pack email body says so.
  Worker-to-farm assignment comes from `Work Payment Line.farm`. A worker
  whose lines span two farms appears in each farm's pack with only that
  farm's lines.

## Scope: which Payroll Entries

Send only when `company == "Kaitet Ltd."` **and** at least one of its Salary
Slips carries an Additional Salary with `ref_doctype = "Work Management
Payment"`. Monthly payrolls and Karen Roses are never sent.

## The email

- **From:** notifications@karenroses.com (the same Email Account the payroll
  Notifications use).
- **Subject:** `Task pay for approval — <Payroll Entry name> — KES <total>`.
  On a resend after Rejected → Resubmit, prefix with `Revised: `. Farm packs
  use `… — <Farm> — KES <farm total>`.
- **Body:** headline only, small enough to avoid Gmail's ~100KB clip (Frappe
  inlines CSS with Premailer, so keep markup lean; see the ops-digest
  lessons). It shows the period, workers, man-days, total KES, a per-farm
  table (workers / days / KES), the **check results** count (below), and a
  link to the Payroll Entry. No per-worker table in the body.
- **Attachment:** `Task-pay-<start>-to-<end>.xlsx` (farm packs:
  `…-<Farm>.xlsx`).
- Sent with `reference_doctype = "Payroll Entry"` / `reference_name` so the
  sends show in the entry's timeline. "Revised" is decided by whether an
  earlier pack Communication exists for that entry. *(My call.)*
- Sent from a background job enqueued after commit, so the HR click is never
  slowed or blocked. A failed build is logged to Error Log and does not
  roll back the workflow action. *(My call.)*

## The workbook

Built with openpyxl directly (it needs several sheets), header row frozen,
autofilter on, KES columns number-formatted, widths sensible.

1. **Workers**: one row per worker: Employee ID, Name, Farm(s), Days worked,
   Tasks (count), WM amount, Slip amount (the slip's WM component), Difference,
   Flag. Sorted by Farm, then Name.
   *Days worked* = **distinct calendar dates** the worker has actuals for in
   the payroll's WMPAYs (from `Work Actuals Employee` via each line's
   `actuals`), not the sum of line `days`. A worker on two tasks in one day
   (split days) counts once. *(My call: the user asked for "days they're
   getting paid", and summed line days overstate exactly where approvers
   compare pay against days.)* The Detail sheet keeps each line's own `days`.
2. **Detail**: one row per `Work Payment Line`: Employee ID, Name, Farm, Task,
   Block, Work from, Work to, Days, Qty, Rate, Amount, Entered by, FM
   approved by, HR approved by, GM approved by, WMPAY ref.
3. **By task**: per farm × task: workers, days, qty, amount.
4. **Checks**: one row per problem found (also counted in the body):
   - a slip on the entry with **no** WM-linked Additional Salary (a worker paid
     with no work behind it);
   - a worker whose slip WM component amount ≠ the sum of their WMPAY line
     amounts;
   - a worker appearing on more than one slip in the entry.
   An empty Checks sheet says "No problems found."
   *(My call: no line-level `amount = qty × rate` check. Line amounts are
   sums of actuals that can span rate periods, split days or re-valuations,
   and older lines carry no rate, so the rule would mostly flag correct
   lines.)*

**Which total is "the" total.** The subject, headline and per-farm table use
the **slip WM component total**, which is what will actually be paid. When it
differs from the payment-line total, the body also shows the line total and
the difference, next to the Checks count. *(My call.)* Headline "man-days" =
the sum of the Workers sheet's *Days worked*.

Days are the line's `days` count with its `work_from`–`work_to` range. A
per-calendar-day grid is **out of scope** (it would need joining to actuals).

## The button

The user's decision (2026-10-23, at approval): **the button downloads the Excel
for a selected date range**, not just one entry.

- **"Download pay breakdown"** opens a dialog with From / To dates and
  downloads the workbook for that range. It appears in two places:
  - on the Payroll Entry form (company Kaitet Ltd., docstatus 1), with the
    dialog defaulting to that entry's start_date–end_date;
  - in the Payroll Entry list view's menu, defaulting to the last 4 weeks.
- **What "the range" selects** *(my call)*: every Kaitet Ltd. task-pay Payroll
  Entry (docstatus 1, `workflow_state` not Cancelled/Rejected) whose pay period
  **overlaps** From–To. Whole entries are included, never part-weeks, so the
  slip checks stay meaningful. The workbook gets a first sheet **Payrolls**
  listing the entries included (name, period, state, workers, KES), so the
  reader sees exactly what was covered. A range that matches no entry
  downloads nothing and shows "No task-pay payrolls in that range."
- The workbook is built from current data with the same four sheets as the
  email. The emailed pack carries the Payrolls sheet too, with one row.
- Permission: the caller must have read permission on **every** entry in the
  range (`frappe.has_permission("Payroll Entry", "read", doc)`), otherwise a
  PermissionError names the first unreadable entry. It is the full pack or
  nothing, never a silently filtered subset.
- From > To, or a range over 92 days, is refused with a message. *(My call: it
  bounds the query; a quarter is the longest useful approval view.)*

## Code placement

- New hand-written module `work_management/payroll_pack.py`, beside
  `payroll_rule.py` / `rates.py`. **Not** in `api/`, which is generated from
  the mirror by `port_app.py` (see the repo's check_ported).
- Hook: `doc_events["Payroll Entry"]["on_update_after_submit"]` → checks
  `doc.has_value_changed("workflow_state")` and `doc.workflow_state ==
  "Pending Accounts"`, applies the scope test, then enqueues the send.
- New Settings field(s) on Work Management Settings: `payroll_pack_to`
  (Small Text), `payroll_pack_bcc` (Small Text), `payroll_pack_enabled`
  (Check, default 1). Seed the addresses via a patch that **does nothing unless
  Company "Kaitet Ltd." exists**, so other clients' sites never get Kaitet
  contacts. *(My call.)* The fields are new on a saved Single, so read them
  with an explicit fallback, not the meta default.
- Unit tests in `work_management/tests/` for: scope detection, recipient
  resolution per farm, workbook sheets and check rules (synthetic rows, no
  site).

## Non-goals

- Changing, replacing or narrowing the five existing payroll Notifications.
- Emails at the GM / Director / CFO stages.
- Monthly salaried payroll, Karen Roses, any other company.
- A per-day attendance grid.
- Blocking approval when checks fail. The pack only informs.

## Anti-goals (a failure even if it "works")

- One email per worker or per WMPAY.
- A farm manager receiving another farm's workers' pay.
- Breaking or slowing the HR "Send to Accounts" click.
- Upande staff other than austin@, jeniffer@ and teresia@ receiving pay data.

## Verify before calling it done

- Run it locally (webstore.localhost has WM data) and against a copy of a real
  entry. Open the xlsx in LibreOffice and check its totals equal the Payroll
  Entry's WM component total.
- Check the rendered email size is under 100KB.
- Test the button as a non-Administrator user who holds Payroll Verifier
  Kaitet.
