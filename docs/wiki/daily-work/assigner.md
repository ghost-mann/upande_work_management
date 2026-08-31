1. Pick an approved plan; the farm's workers load in the picker.
1. Every worker carries today's presence chip, whatever the work window: P · 06:12 (scanned in or marked Present), A today (submitted Absent record — a Present record always beats a stale Absent one), ? today (no scan or attendance record yet), or 'night shift'. Alongside it: off days in the window, leave, absences, and 'assigned elsewhere' (a worker on another live assignment for an overlapping period cannot be picked — this prevents double allocation and double pay).
1. A presence bar above the picker shows how many of the farm's workers are in today, a key for the chips, an 'only workers who are in' filter and a Refresh scans link. The morning-scan block itself still applies only to day-of assignment.
1. Selecting a flagged worker asks for explicit confirmation; submitting re-checks on the server and logs every override on the assignment.
1. Assignments are signed off through the approval chain configured in Settings. Mid-job changes use the swap button — substitutions record who left, who joined and when.

## How attendance is checked at assignment

Every worker is screened against attendance before they can be given work. Each check is a switch in Work Management Settings, under Time & Attendance integration.

- Marked Absent — a submitted Absent attendance record blocks the worker for that day. A Present, Half Day or WFH record on the same day always wins over a stale Absent one, so corrected attendance clears the flag immediately.
- Approved leave — leave overlapping the work window flags the worker.
- Weekly offs and holidays — the off-day rule is configurable: flag only when offs cover the whole window (default), flag any off day in the window, or ignore offs at assignment. Night-shift guards whose off starts the morning after their shift are handled by the same rule.
- Morning presence — when the window includes today, the worker must have scanned in (or have a Present record) by the cutoff time (default 09:00). Before the cutoff nobody is blocked, so early assigning always works; night shifts are exempt.
- Assigned elsewhere — a worker already on a live assignment for an overlapping period cannot be picked at all; this one has no override because it creates double pay.
- Overrides — leave, off-day and no-scan conflicts can be pushed through with an explicit confirmation; the server re-checks on submit and writes every override on the assignment, so the trail is permanent. Recording actuals on a marked-Absent day is stricter: only the farm approver or the GM can confirm it.

> **Note** — Missing attendance never blocks anyone. Only an explicit Absent record does, so a device sync gap cannot stop work from being assigned.
