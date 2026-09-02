# A worker's day, split between two jobs

*2026-09-02*

## The change in one sentence

Record the hours a worker gave each task, so a day can be split between two jobs
and every number derived from it stays true.

## What happens today

**It is refused outright.** The assigner carries a hard double-allocation guard:

> These workers are already assigned elsewhere for an overlapping period: … Remove
> them to avoid double-allocation.

Any worker already on a live assignment whose dates overlap is rejected. Half a
day weeding and half a day pruning is not awkward to record; it cannot be
recorded.

## What is already right, and must not be disturbed

**Pay needs nothing.** A worker's pay is `actual_quantity × rate` -- piece rate.
Three units of weeding and two of pruning pays for both, correctly, by
construction. There is no day rate to pay twice. `daily_wage_basis` on
`Work Task Rate` is only the figure a piece rate was *derived* from, never an
amount anybody receives.

**Per-task cost is already exact.** Every worker's amount chains
`Work Actuals Employee -> Work Management Actuals -> Assigner -> Planner -> task`,
so each shilling already belongs to exactly one task. Hours buy no improvement in
costing, and this spec does not claim any.

What hours buy is what cannot be had today:

- honest man-days when a day is split
- output per **hour** rather than per day -- a worker producing five units in four
  hours and one producing five in eight are indistinguishable now
- utilisation: how much of the available workforce time is actually used

## The gap: the plan speaks person-days, the delivery speaks whole people

`Work Management Planner` already carries `people_per_day`, `person_days`
(labelled *Mandays*), `working_days` and `total_hours`. The plan budgets in
fractions of effort.

The delivery does not. `Work Assignment Employee` is employee, status, dates.
`Work Actuals Employee` is employee, work_date, actual_quantity, amount. **No
hours, no fraction: a day is atomic.** That asymmetry is where a split day falls
through, and it is what this fixes.

## Decisions taken

| question | decision |
|---|---|
| what to record | **actual hours**, not a share of the day |
| does pay change | **no** -- pay stays `quantity × rate`; hours are measurement only |
| who records them | default to the day's standard hours; only a split is typed |
| a day totalling more than its standard hours | **warn and record**, and flag the pattern |

The pay decision is what keeps this out of payroll: a mistyped hour spoils a
metric, never a wage. That is also why warning beats refusing on the total -- the
cost of a wrong number here is bounded.

## Design

### Where the hours live

One new field, `hours` (Float), on **`Work Actuals Employee`**. Delivery is
precise; intent stays coarse.

Nothing is added to `Work Assignment Employee`. An assignment says *these people
are on this job over these dates*; it has never claimed to say how much of each
day. Adding planned hours there would double the data entry to describe an
intention nobody acts on.

### The standard day

The mirror already models it, inline, because the sandbox allows no functions:

    WEEKDAY_HOURS = 8
    SATURDAY_HOURS = 6
    SUNDAY_HOURS = 8      # Sunday counts as a workday here

That model becomes load-bearing rather than informational: it supplies the
default, and it is the denominator for man-days. It moves to Settings in the same
change, because a farm working a six-hour Friday cannot express that today and
this makes the number matter.

### Defaults, and the existing rows

A new actuals row arrives with that date's standard hours already in it. A clerk
touches the field only when somebody split their day. On a normal day there is no
new work at all.

Existing rows are backfilled to their own date's standard hours by a patch --
1,388 actuals documents on live, each with a worker list. Backfilling
rather than leaving them null is what keeps history and new data on one footing:
a null would have to be read as "unknown", and every efficiency series would
break at the date of the deploy.

### The arithmetic that changes

Three places count a day today, and all three are wrong the moment one is split:

**Man-days.** Currently:

    COUNT(DISTINCT CONCAT(we.employee, '|', we.work_date))

which is correct *within* a plan and is then grouped per plan and summed per
farm -- so one worker-day across two plans counts as two. It becomes the sum of
hours over the standard hours for each date, which counts a split day once
however many plans it touches.

**The head-count limit.** The assigner refuses more workers than
`people_per_day`. It compares people; two half-days read as two people, so a plan
for ten could take only five split workers. It compares person-days instead.

**The daily target.** Each task carries `daily_target`, the output expected of one
person for one day. A half-day worker meets half of it and reads as
underperforming. It is pro-rated by hours.

### The guard becomes a warning

The double-allocation refusal is what makes a split impossible, so it stops
refusing and starts saying so -- the same treatment the overlapping-master-plan
refusal got, and for the same reason: it was enforcing a rule that turned out not
to be one.

It still earns its place as a warning. A worker on two assignments is usually a
mistake, and the assigner should say so while letting somebody who means it
proceed.

### The discrepancy flags it collides with

The payment audit already has an opinion about split days, and it is currently
the opposite of this one.

`multi_farm_day` flags *"the same worker earning on more than one farm on the same
date -- physically doubtful; usually a wrong worker picked."* That stance is still
right and stays: this spec makes a split day possible **within one farm**, where
it is ordinary, and leaves crossing farms in a day flagged, where it remains
doubtful.

`disc_dup_day` keys on worker, **task** and date, and offers to delete one copy in
one click. Two different tasks do not collide, so a legitimate split is not
flagged and cannot be auto-deleted. Worth stating explicitly because a change here
would silently start deleting real work.

**Two new flags** join them, each with its own on/off switch like the other eleven.

`disc_long_day` -- a day whose recorded hours exceed its standard. This is where
the warning above becomes visible as a pattern rather than one dismissed message;
the audit is the right home for "this keeps happening".

`disc_short_day` -- a day whose **hours and output disagree**. Not a day that is
merely short: four hours producing about half a target is an ordinary half day and
must not be flagged, or the flag is noise. What is worth a look is three hours
producing a full day's target -- either the hours are wrong or the quantity is,
and the message says exactly that.

    flag when   output share of daily_target
                  minus hours share of the standard day
                exceeds a tolerance

The obvious design was to compare recorded hours against hours present, and it
cannot be built: live holds 864,507 `Employee Checkin` records and almost no
out-scans. In the newest 400, 390 are `IN` and 10 are `OUT`, and 394 of 397
employee-days carry exactly one scan. The app has only ever read `MIN(time)` --
when somebody arrived -- because that is all there is. Hours present is not a
number this data can produce, and a flag that treated a missing out-scan as an
early departure would accuse almost everybody.

The tolerance is a constant to begin with rather than a setting. It can be
exposed if it proves noisy; shipping a threshold nobody has a feel for yet invites
somebody to tune it blind.

## Not in scope

- **Hours affecting pay.** No floor for hours worked, no overtime rate. That is a
  payroll change against ~1,800 live payment records and would need its own
  measurement and rollout.
- **Hours from the attendance clock.** `Employee Checkin` knows when somebody
  arrived and left, not which task they were on, so it can total a day and cannot
  split it. Deriving the total from it later is compatible with this design and is
  not part of it.
- **Planned hours on the assignment.** See above.
- **Sub-hour precision.** Hours are a Float, so a half hour is expressible, but
  nothing in the design depends on finer than that.

## Testing

The arithmetic is pure and carries the weight:

- a full day, unsplit -- every number identical to today, which is the property
  that makes this safe to deploy
- two half-days on one farm: one man-day, not two
- two half-days across two plans: one man-day at farm level
- a day totalling more than standard: recorded, warned, flagged
- a day totalling less than standard: recorded, no warning -- somebody may simply
  have worked a short day
- Saturday, where the standard is six
- the head-count limit against person-days: ten half-days fit a plan for five
- `daily_target` pro-rated: a half-day worker meeting half the target reads as on
  target, not under
- the backfill: an existing row gets its own date's standard, not today's

Then on `kaitet.local`, end to end: assign one worker to two tasks on one farm for
one date, record four hours against each, and confirm the farm shows one man-day,
both amounts paid, and no duplicate-day discrepancy.

## Risks

| risk | disposition |
|---|---|
| The backfill misstates history | it uses each row's own date, not today's, and a test covers a Saturday row; the alternative -- null hours -- breaks every series at the deploy date |
| Relaxing the guard lets real double-allocation through | it warns rather than going silent, and the payment audit's own flags still catch a worker paid twice for one task on one date |
| Man-days change for existing data | they must: the current figure double-counts nothing today only because splits are impossible. With hours defaulted to the standard day, every historical man-day comes out exactly as it does now -- verified by the first test above |
| Clerks leave the default when a day really was split | the metric is wrong, nobody is paid wrongly, and the over-day flag catches the opposite error. This is the cost of defaulting, and it is why defaulting was chosen over demanding entry |
| The hours model moving to Settings changes a live number | it ships seeded with 8/6/8, which is what the code has always used |

## Open questions

Both of the questions this spec opened are now answered, and the answers are in
the design above.

1. **A short day is flagged**, but on hours disagreeing with output rather than on
   shortness -- see `disc_short_day`. The distinction matters because the naive
   version cannot tell a half day from an under-recorded one, and the data cannot
   settle it either.
2. **`person_days` on the planner stays the budget.** It is
   `people_per_day × working_days` -- five people for four days is twenty
   man-days, decided when the plan is raised. Man-days *used* is a new, separate
   figure computed from delivered hours. Overwriting the budget with the actual
   would destroy the only comparison worth having: planned twenty, used
   twenty-three. The two are labelled **Mandays planned** and **Mandays used**,
   because similarly-named numbers meaning different things have already cost this
   project a wrong dashboard column and a double-counting bug.
