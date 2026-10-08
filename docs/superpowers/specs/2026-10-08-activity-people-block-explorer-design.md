# Activity, people & block explorer (dashboard)

Date: 2026-10-08. Agreed in conversation; replaces the dashboard sections
"Planned value & delivery", "Pipeline performers" and "Employee & assignment
tracker". "Cost centres" stays as the finance (GL) view of blocks.

## Purpose

Total visibility below the master-plan level: which activities cost or lag,
who earned what, whose requests turn into work, and where the money goes, with
the history behind each. Audience: management first, farm managers and
finance through the same screens.

## Layout

1. **Shared filter bar**: from / to / farm / search, quick ranges 4w 8w 12w All.
   Every part of the section reads it.
2. **Highlights**: up to six outlier cards for the current filters, each
   clickable to its row: activity furthest over its rate; activity or block
   furthest below target; top earner and earnings outliers; days paid with no
   check-in scan; confirmed pay in no payment run; staff whose approved
   requests delivered least.
3. **Trends chart**: lines, toggled from the legend. KES on the left axis, % on
   the right. Daily up to about 6 weeks, weekly beyond.
   - *Measures*: one subject, any of Planned, Requested, Recorded, Confirmed,
     Paid out (KES, running total by default), Output vs target %,
     Cost/unit vs rate %, People per day. Subject = estate (default), a master
     plan, an activity, *an activity within a plan* (both picked), a worker or a block.
   - *Compare*: up to 6 subjects of one kind, one measure, one line each.
   - Clicking a lens row loads it into the chart.
4. **Lenses**, each a compact sortable scroll list with List | Heatmap:

   | Lens | Answers | Columns |
   |---|---|---|
   | Activities | which work costs or lags | Activity, Done %, Output/day vs target, Cost/unit vs rate, KES earned, trend |
   | Workers | who earned what | Worker, Farm, Days, KES earned, Output vs target, flag |
   | Staff | whose requests turn into work | Person, Requested KES, Delivered KES, Delivered %, Median approval time |
   | Blocks | where the money goes | Block, Farm, Labour KES, KES/ha, Person-days, trend |

   Heatmap = the same rows against weeks, one measure per lens (activities:
   output vs target %; workers: KES; staff: delivered %; blocks: KES).
5. **Drill-down** (inline panel, like the master-plans card):
   activity → overview, by plan, by block, by worker, days;
   worker → overview, activities, blocks, weeks, days (scan or not);
   staff → requests, crews, actuals entered, approvals with times;
   block → activities, workers, weeks, link to Cost centres.
   Rows open the dashboard's existing request / actual / worker / payment drawers.
6. **Key**: every term defined in a collapsible key, here and on the
   master-plans card.

## Definitions

All measures come from recorded worker-days (`Work Actuals Employee`), joined to
their actual, assignment and request. Rejected actuals and requests are excluded.

- Output vs target = output ÷ (person-days × daily target), per activity, so no
  sum ever crosses units.
- Cost/unit vs rate = (pay ÷ output) ÷ rate; 100% = paid exactly the rate.
- Salaried share = salaried output ÷ output.
- Recorded = every non-rejected actual; Confirmed = CONFIRMED actuals;
  Paid out = payment runs in state Paid.

## Server

New `wm_dashboard` actions (mirror `server_scripts/wm_dashboard.py`, ported):
`ex_lens` (with heatmap grid), `ex_detail`, `ex_series`. Each is bounded by the
caller's farms (FARMS), like every other action. As built, the highlights need
no action of their own: they are derived in the browser from the four lens
results the section loads anyway. "Paid out" joins a once-built set of paid
(actual, worker) pairs; a per-row lookup took 22s over eight weeks.

## Delivery

Three steps, each tested (source tests + API + headless Chrome on the live
slice): lenses and drill-downs; trends chart; heatmap, highlights and key.
