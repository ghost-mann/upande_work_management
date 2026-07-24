# Upande Work Management — User Guide

Work Management plans, assigns, records and pays farm task work. The whole
pipeline is: **Plan → Assign → Actuals → Confirm → Pay**, and every step is
visible on the web pages under your site:

| Page | URL | Who uses it |
|---|---|---|
| Command Centre (dashboard) | `/work-management` | Management — the whole pipeline at a glance |
| Planner | `/work-planner` | Supervisors creating weekly task plans |
| Assigner | `/work-assigner` | Assigning workers to approved plans |
| Actuals | `/work-actuals` | Recording the work actually done each day |
| Payment | `/work-payment` | Audit, review and payment of workers |

Sign in with your normal site account (use the round account button at the
top-right of any page to log in/out).

---

## 1. Planner (`/work-planner`)

1. Pick the farm, task, block(s), period and rate, and the number of people.
2. Save — the plan starts in **PENDING** and goes to the farm's approver.
3. The approver (Farm Manager) approves or rejects the plan.
4. Approved plans become available to the Assigner.

A plan's budgeted value = rate × target quantity. You can plan several blocks
in one go; each block becomes its own plan line.

## 2. Assigner (`/work-assigner`)

1. Pick an approved plan and the actual date window.
2. Add the workers (search by name or number). Substitutions later — workers
   who leave or join mid-job — are tracked automatically.
3. Submit for approval; the General Manager signs off assignments.

## 3. Actuals (`/work-actuals`)

1. Each day, open the assignment and enter the quantity each worker did.
2. Each worker-day row is valued at the plan rate (qty × rate).
3. Submit the actuals document through its confirmations: Farm Manager →
   HR → General Manager (**CONFIRMED**). Only CONFIRMED work can be paid.

## 4. Payment (`/work-payment`) — workers are paid one at a time

The payment section is worker-centric. There are no batch runs: you review
each worker, send them to accounts individually, and accounts releases them.

**Statuses a worker moves through:** `Unpaid → Reviewed → Sent to accounts → Paid`

### Audit workers tab
Every worker with CONFIRMED earnings, with farm and date filters. Click a
worker to open their **review sheet**:

- Headline numbers: mandays, days, tasks, quantity, earned / paid / unpaid.
- **Per-task cards**: each task with its block, plan period, worked period,
  qty, rate, amount — and the full accountability chain (who created the plan,
  assigned the job, entered actuals, and each approver).
- **Daily log**: every worker-day row. Unpaid rows can be **edited** here
  (fix a quantity — the amount recalculates at the doc rate and the parent
  totals re-sum; every edit is recorded as a comment on the actuals document).
  Editing a day clears the review stamp so the worker must be re-reviewed.
- **Review & approve** stamps the worker's unpaid rows as Reviewed (who + when).
- **Send to accounts** creates that worker's payment entry (see below) and
  moves them to *Sent to accounts*.

### Pay workers tab
Same in-depth view and editing as Audit workers, for the people doing payment.

### Awaiting accounts tab
Workers whose payment entry is with accounts (*Pending Accounts*). From here:

- **Release payment** — accounts marks the entry Paid; every included
  worker-day row is stamped paid.
- **Return to unpaid** — withdraws the entry: the payment document is deleted,
  the rows go back to Unpaid and lose their review stamp, and the worker
  restarts at review. Use this when something needs to be corrected.

### The payment entry (Work Management Payment)
Sending a worker to accounts creates **one payment document per worker**
(`WMPAY-…`), which accounts can open in the desk. It contains:

- Header: employee, name, farm, period, total days / quantity / amount,
  **who reviewed** the earnings and when, and who prepared (sent) it.
- **Lines — one row per task/actuals document** with: task, block, worked
  period (from → to), days, quantity, rate, amount, the assignment reference,
  **who assigned the job, who entered the actuals**, and the FM / HR / GM
  approvers.

So the full "who did what" trail from the review sheet travels with the money.

## 5. Dashboard (`/work-management`)

- **Delivery timeline** — planned vs assigned vs actual value per day.
- **Action queues** — one tabbed card of everything waiting for someone.
- **Approver KPIs** — per approval stage, bar charts of each approver's
  sign-offs, value handled and time taken.
- **Value flow** — weekly planned / assigned / confirmed value plus a per-plan
  table with farm & date filters showing each plan's accountability chain.
- **Pipeline performers** — ranking of every plan creator, assigner, actuals
  enterer and approver by volume and value.
- **Crew movements** — substitution history (who left, who joined, swaps).

## Tips

- Money only ever flows from **CONFIRMED** actuals rows that are
  `count_in_payroll` — advances/exclusions never double-pay.
- If a worker's amount looks wrong in review, fix the day in the daily log
  before sending to accounts; the audit trail keeps every change.
- "Return to unpaid" is always safe: it deletes only the pending payment
  document, never the underlying work records.
