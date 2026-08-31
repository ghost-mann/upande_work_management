- Activity across the pipeline — stage cards for Planned, Assigned (with active employees split into task workers and permanent staff), Actual and Payment.
- Workers & value per farm — per-farm cards: assigned workers, active employees (task/permanent split), awaiting actuals, confirmed, quantities and value.
- Delivery timeline — planned vs staffed vs delivered per day, with farm and date filters and quantity/KES toggle.
- Field intelligence (beside the timeline) — two tabs: Efficiency (Ha per man-day and Cost per Ha, per farm and per task) and Available workers (the number and list of employees free to work on any chosen date, filterable by farm). Explained in full in the next section.
- Action queues — everything waiting on someone, one queue at a time.
- Value flow — weekly planned/assigned/confirmed value and a per-plan table with each plan's accountability chain.
- Cost centres — running labour cost per block, beside the GL cost-centre actuals posted against it, as a treemap sized by spend and a table below it. A Group toggle reads the same money by section instead of by block; either way, click a row for the tasks, workers, weekly trend and GL accounts behind it.
- Crew movements — substitution history: who left, who joined, swaps.

## Pipeline performers

Planner and assigner economics, per person, with most/least-expensive callouts (judged only on people with real volume, more than 500 units).

**Column key**

| Column | Meaning |
|---|---|
| Plans | Approved plans created in the window |
| Target qty | The output those plans promised |
| Actual qty | Confirmed output delivered |
| Achieved | Actual ÷ Target (green 90%+, amber 60%+, red below) |
| Budget KES | What the plans are worth if fully delivered (rate × target) |
| Spent KES | Confirmed pay earned on them |
| Of budget | Spent ÷ Budget |
| KES/unit | Spent ÷ Actual — what one unit of output cost under this person |

> **Note** — 'Of budget' being low is NOT automatically a saving. Read it with Achieved: 50% spent at 50% achieved just means half the work happened.

The Assigners tab uses the same definitions over their assignments, plus Workers put on jobs (assignment rows they created — a worker on two assignments counts twice). A third tab evaluates Actuals enterers: documents, worker-days, value entered, average entry lag and rejections. Click any name for that person's full evaluation popup: volume, delivery (achieved %, closed-early rate), money (budget vs spent, KES/unit, and a task-adjusted 'vs peers on the same tasks' benchmark that removes task-mix unfairness), speed (approval wait / staffing speed / entry lag), quality (rejections, substitutions, attendance overrides, flagged rows) and the list of their documents.
