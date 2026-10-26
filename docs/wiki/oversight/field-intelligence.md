The Field intelligence card sits beside the Delivery timeline on the dashboard. It answers two everyday management questions: 'what does our work actually cost per hectare, and how much ground does a worker-day cover?' and 'who is free to work today (or any day I pick)?'

## Graphs in the Delivery timeline card

The Delivery timeline card has a Graph dropdown. Besides the default planned vs staffed vs delivered timeline it can show, for the card's own farm and date window: cost per hectare of the farm (confirmed pay that week ÷ the farm's Area); cost per hectare, farm vs worked area (solid = per hectare of the whole farm, dashed = per hectare of the blocks actually worked that week, each block once); weekly cost in KES; man-days per Ha; and cost per hectare by task. The weekly graphs put Monday-start weeks along the bottom and the measure up the side. A week with no confirmed work is a gap in the line, not a zero; where a farm's blocks have no Area (HA) the dashed line is not drawn and the graph says so. Hover to read each farm's value for a week; the first and last week can be part-weeks, and the hover says how many of their days fall in the window.

## Efficiency tab

Pick a date window (default: the last 30 days) and press Apply. The table shows, per farm and in total:

- Area Ha — the hectares of the blocks whose plans had confirmed work in the window. Each plan's blocks are counted once for that plan, using the Area (HA) captured on the block record (Warehouse). If a block has no area captured, it contributes nothing — a dash (—) in the table means areas are missing, and the fix is data entry on the block records, not a system fault.
- Man-days — one worker working one day is one man-day, counted from confirmed actuals (a worker on two tasks the same day is still one man-day).
- Man-days / Ha — man-days ÷ Area: how many worker-days one hectare takes. Lower is leaner. Compare farms with care: the task mix matters (a farm doing slow detailed tasks like handling will always need more man-days per hectare than one doing slashing).
- Cost KES — the confirmed pay for that work in the window.
- Cost / Ha — Cost ÷ Area: what a hectare of work cost. This is the number to watch over time per farm and per task.

When Cost/Ha rises on the same task mix, each hectare is consuming more paid work than before. Read it together with Man-days/Ha: if Cost/Ha rises while Man-days/Ha rises too, workers are covering less ground per day — productivity dropped (denser weeds, harder terrain, crop stage slowing the task, or quantities recorded that don't match ground actually covered). If Man-days/Ha is steady while Cost/Ha rises, the change is in the rates — check the task list.

Below the farm table, the same metrics appear per task (top tasks by man-days), which is where differences usually explain themselves — compare the same task across time, not different tasks against each other.

## Available workers tab

Pick any date (past, today or future) and optionally a farm. The card shows the count and the full name list of AVAILABLE workers — active employees with no live assignment covering that date (assignment start and leaving dates are respected). For today and past dates, a green P marks workers who scanned in that day, so you can see at a glance who is both free AND on the farm. Use the name search to find someone specific.

This is the assigner's shortlist: when a new plan needs a crew, the Available workers list for the start date is exactly who can be picked without a double-allocation conflict.
