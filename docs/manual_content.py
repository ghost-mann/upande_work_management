"""The user guide's content, as structured data.

Kept apart from the renderers so the same words produce the PDF and the DOCX.
Two chapters are not written by hand at all: the approval stage catalogue is
generated from ``work_management.approvals.CATALOGUE`` and the settings
reference from the Work Management Settings doctype JSON, so neither can drift
from the code the way a hand-maintained reference always eventually does.

Block kinds:

    part    a part title -- starts a new page, resets nothing
    h2      a numbered section
    h3      a subsection
    p       a paragraph
    b       a bullet
    n       a numbered step
    note    a callout, for the thing people get wrong
    table   (caption, [headers], [[cells], ...])
"""

import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
SETTINGS_JSON = (
	REPO / "work_management" / "work_management" / "doctype"
	/ "work_management_settings" / "work_management_settings.json"
)

TITLE = "Work Management"
SUBTITLE = "User Guide"
STRAPLINE = (
	"Plan task work against a budget, assign crews, record what was done, "
	"and pay for it — with the payroll protected by attendance checks and a standing audit."
)


# ---------------------------------------------------------------- generated


def stage_rows():
	"""The approval stage catalogue, read from the code that defines it."""
	from work_management import approvals

	rows = []
	for stage in approvals.CATALOGUE:
		document = stage.document_type.replace("Work Management ", "")
		rows.append([
			stage.label,
			document,
			stage.kind,
			stage.state or "—",
			stage.action or "—",
			"Yes" if stage.scoped else "—",
		])
	return rows


def settings_blocks():
	"""The settings reference, read from the doctype definition."""
	doc = json.loads(SETTINGS_JSON.read_text())
	fields = {f["fieldname"]: f for f in doc["fields"]}

	blocks, section, rows = [], "General", []
	skip = {"Section Break", "Column Break", "HTML", "Tab Break"}

	def flush():
		if rows:
			blocks.append(("table", (section, ["Setting", "Type", "What it does"], list(rows))))

	for fieldname in doc["field_order"]:
		field = fields[fieldname]
		if field["fieldtype"] == "Section Break":
			flush()
			rows.clear()
			section = field.get("label") or fieldname
			continue
		if field["fieldtype"] in skip:
			continue
		label = field.get("label") or fieldname
		if field.get("read_only"):
			label += " (read-only)"
		description = (field.get("description") or "").replace("—", "—")
		if not description:
			description = {
				"Check": "On or off.",
				"Table": "A table of rows.",
			}.get(field["fieldtype"], "See the field's help text on the form.")
		rows.append([label, field["fieldtype"], description])
	flush()
	return blocks


# -------------------------------------------------------------- the content


def sections():
	return [
		("part", "Part I · Operations"),

		("h2", "The pipeline at a glance"),
		("p", "Every shilling follows the same path: Plan → Assign → Actuals → Confirm → Pay. "
			  "A plan sets the task, blocks, period, daily standard and rate. An assignment puts "
			  "named workers on an approved plan. Actuals record each worker's daily output. "
			  "Confirmations turn records into payable earnings, and Payment reviews and releases "
			  "the money one worker at a time."),
		("p", "Nothing skips a step. A worker cannot be paid for a day that was never recorded, "
			  "recorded work cannot exist without an assignment, and an assignment cannot exist "
			  "without an approved plan. That chain is what makes the audit in Part I, "
			  "Discrepancies, possible."),
		("p", "Sign in with your normal account. The round button at the top-right of every "
			  "screen shows who is signed in, and is used to log in and out."),

		("h2", "Finding your way around"),
		("p", "The module puts itself in three places, so you can reach it however you already "
			  "work."),
		("h3", "The five work screens"),
		("p", "Day-to-day work happens on five full-page screens. These are where almost "
			  "everyone spends their time."),
		("table", ("The screens", ["Screen", "Address", "What it is for"], [
			["Command Centre", "/work-management", "Dashboard: activity, value, queues, performance"],
			["Planner", "/work-planner", "Raise and approve plans; the consultant weekly review"],
			["Assigner", "/work-assigner", "Put named workers on an approved plan"],
			["Actuals", "/work-actuals", "Record each worker's daily output"],
			["Payment", "/work-payment", "Review workers, send to accounts, release pay, audit"],
		])),
		("h3", "The apps screen"),
		("p", "Work Management appears as its own tile on the Frappe apps screen, which opens "
			  "the Command Centre. The tile is only shown to people who hold one of the "
			  "module's roles, so it does not clutter the screen for everyone else."),
		("h3", "The desk workspace"),
		("p", "Inside the desk, the Work Management workspace gives shortcuts to the five "
			  "screens and cards linking every underlying record: Plan & budget, Doing the "
			  "work, Money, and Setup. Use this when you need the records themselves — a "
			  "specific plan document, a rate history, the settings — rather than the screens."),
		("p", "On Frappe v16 the same links also appear in the left sidebar, grouped into "
			  "Records, Rates and Setup. Frappe v15 has no sidebar of this kind; everything is "
			  "reachable from the workspace instead."),

		("h2", "Planner"),
		("n", "Pick the farm, task, block or blocks, the work period, and the crew size."),
		("n", "The daily standard and rate come from the task list (for example 150 Meter/day at "
			  "KES 2.2667 per Meter — rates carry four decimals so a full day comes to exactly "
			  "KES 340)."),
		("n", "Save. The plan starts as PENDING and goes to the farm's approver."),
		("n", "Approved plans become available to the Assigner. A plan's budget = rate × target "
			  "quantity."),

		("h3", "Consultant weekly review"),
		("p", "Plans that start in an upcoming week must be signed off by a consultant before "
			  "the farm's approver can approve them individually. Plans for the current week "
			  "are exempt, so day-to-day operations are never blocked."),
		("n", "Open the Weekly review tab on the Planner, pick the farm and the week (it "
			  "defaults to next Monday; use Prev/Next week to move)."),
		("n", "The board shows the whole week as one package: number of plans, total budgeted "
			  "value (rate × target across every plan), peak crew per day against the farm's "
			  "active workforce, and a day-by-day crew-load chart. If any day asks for more "
			  "workers than the farm has, the board flags the week as over-planned."),
		("n", "Below the chart, every plan is listed with its task, blocks, period, crew per "
			  "day, target, rate, budget, who requested it, and its consultant status."),
		("n", "Consultants decide the week in one action: 'Approve week' stamps every plan as "
			  "consultant-approved and unlocks approval; 'Return with note' sends the whole "
			  "week back — the note is required and is written on every plan for the planner "
			  "to act on."),
		("n", "Every decision is stamped on the plans (who, when, note) and logged as a "
			  "comment, so the trail survives on the document."),
		("p", "Who can decide: the people named as approvers on the Planner: Weekly Consultant "
			  "stage in Settings, plus System Managers. Everyone else sees the board read-only. "
			  "The whole gate can be switched off with 'Require consultant approval for "
			  "future-week plans' in Settings."),

		("h2", "Assigner"),
		("n", "Pick an approved plan; the farm's workers load in the picker."),
		("n", "Every worker carries today's presence chip, whatever the work window: P · 06:12 "
			  "(scanned in or marked Present), A today (submitted Absent record — a Present "
			  "record always beats a stale Absent one), ? today (no scan or attendance record "
			  "yet), or 'night shift'. Alongside it: off days in the window, leave, absences, "
			  "and 'assigned elsewhere' (a worker on another live assignment for an overlapping "
			  "period cannot be picked — this prevents double allocation and double pay)."),
		("n", "A presence bar above the picker shows how many of the farm's workers are in "
			  "today, a key for the chips, an 'only workers who are in' filter and a Refresh "
			  "scans link. The morning-scan block itself still applies only to day-of "
			  "assignment."),
		("n", "Selecting a flagged worker asks for explicit confirmation; submitting re-checks "
			  "on the server and logs every override on the assignment."),
		("n", "Assignments are signed off through the approval chain configured in Settings. "
			  "Mid-job changes use the swap button — substitutions record who left, who joined "
			  "and when."),

		("h3", "How attendance is checked at assignment"),
		("p", "Every worker is screened against attendance before they can be given work. Each "
			  "check is a switch in Work Management Settings, under Time & Attendance "
			  "integration."),
		("b", "Marked Absent — a submitted Absent attendance record blocks the worker for that "
			  "day. A Present, Half Day or WFH record on the same day always wins over a stale "
			  "Absent one, so corrected attendance clears the flag immediately."),
		("b", "Approved leave — leave overlapping the work window flags the worker."),
		("b", "Weekly offs and holidays — the off-day rule is configurable: flag only when offs "
			  "cover the whole window (default), flag any off day in the window, or ignore offs "
			  "at assignment. Night-shift guards whose off starts the morning after their shift "
			  "are handled by the same rule."),
		("b", "Morning presence — when the window includes today, the worker must have scanned "
			  "in (or have a Present record) by the cutoff time (default 09:00). Before the "
			  "cutoff nobody is blocked, so early assigning always works; night shifts are "
			  "exempt."),
		("b", "Assigned elsewhere — a worker already on a live assignment for an overlapping "
			  "period cannot be picked at all; this one has no override because it creates "
			  "double pay."),
		("b", "Overrides — leave, off-day and no-scan conflicts can be pushed through with an "
			  "explicit confirmation; the server re-checks on submit and writes every override "
			  "on the assignment, so the trail is permanent. Recording actuals on a "
			  "marked-Absent day is stricter: only the farm approver or the GM can confirm it."),
		("note", "Missing attendance never blocks anyone. Only an explicit Absent record does, "
				 "so a device sync gap cannot stop work from being assigned."),

		("h2", "Actuals"),
		("n", "Open the assignment; the grid shows one row per worker and one column per day."),
		("n", "Every past/today cell carries presence evidence: the check-in time (in 06:52), "
			  "P (marked present, no scan time), A · absent (marked Absent), or ? (no record "
			  "either way — presence unknown). Rest days show a dot, approved leave days are "
			  "blocked."),
		("n", "Enter each worker's daily quantity. Rows are valued at qty × rate to the cent; "
			  "on plans whose implied daily wage is within 1% of the standard daily wage, a "
			  "full day is valued at exactly that wage."),
		("n", "Saving warns when a quantity conflicts with attendance: recording work for a "
			  "worker marked Absent needs the farm approver (or GM) to approve; leave/off/"
			  "no-scan conflicts can be overridden by the enterer, and every override is logged "
			  "on the document. Saving also warns when the same worker-day is already recorded "
			  "for the task in another document (double pay)."),
		("n", "Submit walks the document through the approval chain to CONFIRMED. Submission "
			  "unlocks only when the plan target is reached; plans that cannot finish "
			  "(absentees, crop finished early) are closed early via a close request, which the "
			  "GM approves — the close queue shows live done/remaining figures."),

		("h2", "Payment — workers are paid one at a time"),
		("p", "The payment section is worker-centric. Each worker's confirmed earnings are sent "
			  "to accounts as their own payment entry and released. The status ladder per "
			  "worker is: Unpaid → Sent to accounts → Paid. There is no separate review step — "
			  "sending IS the sign-off: the sender's name and time are stamped on every "
			  "included day-row and on the payment entry. The review sheet stays available for "
			  "checking anyone before sending."),
		("h3", "Reviewing a worker"),
		("b", "Click any worker to open the review sheet: identity, window KPIs (earned, paid, "
			  "unpaid, days), one card per task with the daily log underneath, a Payments tab, "
			  "and a Discrepancies tab listing that worker's flagged days."),
		("b", "Each task card names the full accountability chain: who created the plan, "
			  "assigned the job, captured the actuals, and each approver, plus the task's "
			  "standard (e.g. 300 Tree/day @ KES 1.1333)."),
		("b", "Every day row shows presence evidence next to the pay. In Work & days, every "
			  "unpaid day's quantity is directly editable — change as many as needed and press "
			  "the single Save changes button at the bottom (Undo restores the originals). Pay "
			  "recomputes at each row's rate, documents re-sum, and one audit comment per "
			  "document lists every change."),
		("b", "Download Excel exports the review as a workbook: a Summary sheet and a Tasks & "
			  "days sheet laid out like the review (one table per task with its day rows and "
			  "presence)."),
		("h3", "Sending to accounts"),
		("b", "Submit & send to accounts creates one payment document for that worker "
			  "(WMPAY-…) holding the period, totals, who sent it and when, and one line per "
			  "actuals document with the task, block, worked period, days, qty, rate, amount "
			  "and the whole sign-off chain. The sender is stamped as reviewer on every "
			  "included day-row."),
		("b", "Bulk: tick several workers (workers with attendance conflicts carry a red flag "
			  "with the day count) and use Send to accounts — each still gets their own entry."),
		("h3", "Awaiting accounts"),
		("b", "Accounts releases an entry with Mark paid — every included day row is stamped "
			  "paid."),
		("b", "Return to unpaid withdraws an entry (deletes the reference, clears review "
			  "stamps) so the days can be corrected and re-sent. Bulk return handles many "
			  "entries at once."),
		("b", "A payment already marked paid can still be cancelled if it was released in "
			  "error."),

		("h2", "Time & attendance protection"),
		("p", "The pipeline checks workers against attendance before work is given to them or "
			  "recorded for them. Every behaviour is a switch in Work Management Settings."),
		("b", "Checks: marked Absent (submitted attendance), approved leave, weekly "
			  "offs/holidays, and morning presence (biometric scan or Present attendance today, "
			  "with a configurable cutoff so early assigning is never blocked; night shifts are "
			  "exempt)."),
		("b", "The off-day rule when assigning is configurable: flag only when offs cover the "
			  "whole window (default), flag any off day, or ignore offs at assignment."),
		("b", "Overrides: leave/off/no-scan conflicts can be overridden by the person doing the "
			  "work, always logged. Absent-day actuals need the farm approver or GM."),

		("h2", "Discrepancies — the standing audit"),
		("p", "Payment → Audit → Discrepancies scans every confirmed worker-day in the chosen "
			  "window and groups everything suspicious. Each check has its own settings "
			  "checkbox; rows link to the worker's review sheet and name the documents."),
		("b", "Paid on marked-Absent days — a scan time means the attendance record is probably "
			  "wrong; no scan means the entry needs scrutiny. Days whose attendance was "
			  "corrected (a Present record exists alongside an old Absent one) are validated "
			  "out and never flagged."),
		("b", "No presence evidence at all — no scan and no attendance record of any kind."),
		("b", "Earning while on approved leave — possible double payment."),
		("b", "Work on off days / holidays — fine if deliberate overtime."),
		("b", "Amount ≠ qty × rate — edited or corrupted values."),
		("b", "Two farms, one day — physically doubtful."),
		("b", "Entered and approved by the same person — no independent check."),
		("b", "Earning after leaving the job — days dated after a worker was released."),
		("b", "Paid twice for the same day — the same worker, task and date in two documents; a "
			  "one-click repair keeps the earliest copy and zeroes the rest."),
		("b", "Recorded work with no pay — rows valued at zero although the document has a "
			  "rate; a one-click Revalue repairs them at qty × rate."),
		("b", "Left the company but still on live assignments — ex-employees still assignable. "
			  "A Clean slate button releases the backlog; the auto-release setting (off by "
			  "default) releases future leavers the moment HR deactivates them. Released "
			  "workers keep all recorded work and pay — release only stops new quantities."),

		("h2", "Dashboard"),
		("b", "Activity across the pipeline — stage cards for Planned, Assigned (with active "
			  "employees split into task workers and permanent staff), Actual and Payment."),
		("b", "Workers & value per farm — per-farm cards: assigned workers, active employees "
			  "(task/permanent split), awaiting actuals, confirmed, quantities and value."),
		("b", "Delivery timeline — planned vs staffed vs delivered per day, with farm and date "
			  "filters and quantity/KES toggle."),
		("b", "Field intelligence (beside the timeline) — two tabs: Efficiency (Ha per man-day "
			  "and Cost per Ha, per farm and per task) and Available workers (the number and "
			  "list of employees free to work on any chosen date, filterable by farm). "
			  "Explained in full in the next section."),
		("b", "Action queues — everything waiting on someone, one queue at a time."),
		("b", "Value flow — weekly planned/assigned/confirmed value and a per-plan table with "
			  "each plan's accountability chain."),
		("b", "Crew movements — substitution history: who left, who joined, swaps."),
		("h3", "Pipeline performers"),
		("p", "Planner and assigner economics, per person, with most/least-expensive callouts "
			  "(judged only on people with real volume, more than 500 units)."),
		("table", ("Column key", ["Column", "Meaning"], [
			["Plans", "Approved plans created in the window"],
			["Target qty", "The output those plans promised"],
			["Actual qty", "Confirmed output delivered"],
			["Achieved", "Actual ÷ Target (green 90%+, amber 60%+, red below)"],
			["Budget KES", "What the plans are worth if fully delivered (rate × target)"],
			["Spent KES", "Confirmed pay earned on them"],
			["Of budget", "Spent ÷ Budget"],
			["KES/unit", "Spent ÷ Actual — what one unit of output cost under this person"],
		])),
		("note", "'Of budget' being low is NOT automatically a saving. Read it with Achieved: "
				 "50% spent at 50% achieved just means half the work happened."),
		("p", "The Assigners tab uses the same definitions over their assignments, plus Workers "
			  "put on jobs (assignment rows they created — a worker on two assignments counts "
			  "twice). A third tab evaluates Actuals enterers: documents, worker-days, value "
			  "entered, average entry lag and rejections. Click any name for that person's full "
			  "evaluation popup: volume, delivery (achieved %, closed-early rate), money "
			  "(budget vs spent, KES/unit, and a task-adjusted 'vs peers on the same tasks' "
			  "benchmark that removes task-mix unfairness), speed (approval wait / staffing "
			  "speed / entry lag), quality (rejections, substitutions, attendance overrides, "
			  "flagged rows) and the list of their documents."),

		("h2", "Field intelligence, explained"),
		("p", "The Field intelligence card sits beside the Delivery timeline on the dashboard. "
			  "It answers two everyday management questions: 'what does our work actually cost "
			  "per hectare, and how much ground does a worker-day cover?' and 'who is free to "
			  "work today (or any day I pick)?'"),
		("h3", "Efficiency tab"),
		("p", "Pick a date window (default: the last 30 days) and press Apply. The table shows, "
			  "per farm and in total:"),
		("b", "Area Ha — the hectares of the blocks whose plans had confirmed work in the "
			  "window. Each plan's blocks are counted once for that plan, using the Area (HA) "
			  "captured on the block record (Warehouse). If a block has no area captured, it "
			  "contributes nothing — a dash (—) in the table means areas are missing, and the "
			  "fix is data entry on the block records, not a system fault."),
		("b", "Man-days — one worker working one day is one man-day, counted from confirmed "
			  "actuals (a worker on two tasks the same day is still one man-day)."),
		("b", "Ha / man-day — Area ÷ man-days: how much ground one worker-day covers. Higher is "
			  "leaner. Compare farms with care: the task mix matters (a farm doing slow "
			  "detailed tasks like handling will always cover fewer hectares per man-day than "
			  "one doing slashing)."),
		("b", "Cost KES — the confirmed pay for that work in the window."),
		("b", "Cost / Ha — Cost ÷ Area: what a hectare of work cost. This is the number to "
			  "watch over time per farm and per task."),
		("p", "When Cost/Ha rises on the same task mix, each hectare is consuming more paid "
			  "work than before. Read it together with Ha/man-day: if Cost/Ha rises while "
			  "Ha/man-day falls, workers are covering less ground per day — productivity "
			  "dropped (denser weeds, harder terrain, crop stage slowing the task, or "
			  "quantities recorded that don't match ground actually covered). If Ha/man-day is "
			  "steady while Cost/Ha rises, the change is in the rates — check the task list."),
		("p", "Below the farm table, the same metrics appear per task (top tasks by man-days), "
			  "which is where differences usually explain themselves — compare the same task "
			  "across time, not different tasks against each other."),
		("h3", "Available workers tab"),
		("p", "Pick any date (past, today or future) and optionally a farm. The card shows the "
			  "count and the full name list of AVAILABLE workers — active employees with no "
			  "live assignment covering that date (assignment start and leaving dates are "
			  "respected). For today and past dates, a green P marks workers who scanned in "
			  "that day, so you can see at a glance who is both free AND on the farm. Use the "
			  "name search to find someone specific."),
		("p", "This is the assigner's shortlist: when a new plan needs a crew, the Available "
			  "workers list for the start date is exactly who can be picked without a "
			  "double-allocation conflict."),

		("part", "Part II · Setup & administration"),

		("h2", "Setting up a new project"),
		("p", "The module ships knowing nothing about your organisation. There are no farms, no "
			  "approvers and no company until you configure them, and the screens say so rather "
			  "than offering someone else's. Work through this part once, in order, and the "
			  "pipeline in Part I becomes usable."),
		("table", ("Setup order", ["Step", "Where", "Covered in"], [
			["Create your farms and cost projects", "Work Management Farm", "Farms and cost projects"],
			["Tag blocks, workers and tasks", "Warehouse, Employee, Task", "Farms and cost projects"],
			["Set the roles and people for each approval step", "Settings → Approvals", "Approval stages and approvers"],
			["Set company, attendance and payroll behaviour", "Settings", "Settings reference"],
		])),

		("h2", "Farms and cost projects"),
		("p", "A farm is the unit work is planned against. Whatever your project calls it — "
			  "farm, estate, site, division, block group — create one Work Management Farm "
			  "record for each, and the rest of the module follows that naming."),
		("b", "Farm — the name. It appears in every picker and is stored on every plan, "
			  "assignment, actuals document and payment."),
		("b", "Cost Project — costs recorded for this farm are attributed to this project."),
		("b", "Disabled — hides the farm from pickers on new documents. Existing documents keep "
			  "their farm, so disabling is safe for a site you have stopped working."),
		("p", "Three things on core records then have to be tagged, or the screens have nothing "
			  "to offer:"),
		("b", "Warehouses used as blocks — set Farm, and set Area (HA) if you want the "
			  "efficiency figures in Field intelligence to work."),
		("b", "Employees who do task work — set Unit/Division to their farm."),
		("b", "Tasks — set UoM, Daily Target and Rate. These are the standard a plan inherits, "
			  "and the Task list is where rates are edited day to day."),
		("note", "Editing a rate on a Task records a rate period starting today, so rate "
				 "history writes itself. Backdated rate changes belong to a rate card, applied "
				 "from the Rates section of Settings."),

		("h2", "Naming the levels"),
		("p", "The module ships calling things farms and blocks. If your project calls "
			  "them estates and plots, say so once in Work Management Settings under "
			  "Taxonomy and every form, screen and column heading follows. Nothing about "
			  "the data changes — only what it is called."),
		("b", "Leave a name empty to use the built-in wording."),
		("b", "Turn on the level above the farm if your farms belong to a business unit; "
			  "reports can then group by it."),
		("b", "The cost grouping name is used by the section view described below."),

		("h2", "Sections, and cost by section"),
		("p", "A section is a group of blocks. It exists so the cost-centre view on the "
			  "dashboard can be read by section instead of block by block — nothing else "
			  "in the system uses it, and no plan, assignment or payment mentions one."),
		("n", "Create a section, give it a farm, and add its blocks to the table."),
		("n", "A block belongs to one section only. Adding a block another section already "
			  "holds is refused, naming that section — counted twice it would double its "
			  "cost in the total."),
		("n", "On the dashboard, the cost-centre view has a Group toggle: by block, or by "
			  "section. Overheads and administration appear under both."),
		("note", "Blocks you have not placed in a section are grouped under Unassigned, "
				 "never dropped, so the section view always totals the same as the block "
				 "view."),

		("h2", "Approval stages and approvers"),
		("p", "Every step of every approval chain is configured in Work Management Settings, "
			  "under Approvals. Nothing about who approves what is fixed in the software."),
		("h3", "The two tables"),
		("b", "Approval Stages — one row per step, seeded when the module is installed. The "
			  "step and the document it belongs to are fixed; you set the role that takes it, "
			  "and whether the step happens at all."),
		("b", "Stage Approvers — one row per person per step: the stage, optionally the farm, "
			  "the person, and optionally a role override. Saving grants each person the role "
			  "their stage runs on."),
		("p", "The approval workflows are generated from these two tables. That means approvers "
			  "get the ordinary Frappe experience — the action buttons on the document, the "
			  "notifications, and the awaiting-approval inbox — rather than anything bespoke."),
		("h3", "Switching a step off"),
		("p", "Clear the On box and the chain relinks around it: with the Assigner GM step off, "
			  "HR approval sends the assignment straight to Assigned. Submit steps cannot be "
			  "switched off, because a document nobody can submit is not a useful "
			  "configuration."),
		("h3", "Approvers for one farm only"),
		("p", "On a farm-scoped step, give each farm its own approver row and its own role "
			  "override. That is what keeps one farm's approvals out of another farm's reach: "
			  "the generated workflow carries a separate transition per farm, each allowed only "
			  "to that farm's role."),
		("p", "Leaving the Farm cell empty means that person acts on every farm. Leaving the "
			  "step with no approver rows at all means the stage's own role covers every farm."),
		("note", "Settings refuses to save a configuration that would strand a farm. If a "
				 "farm-scoped step names approvers for some farms but not others, the farms "
				 "left out would have nobody able to approve their work, and the error names "
				 "them."),
		("h3", "What changes when you save"),
		("b", "Each listed approver is granted their stage's role. Roles granted by hand, for "
			  "any other reason, are never touched."),
		("b", "Removing someone from the table revokes the role it gave them, unless another "
			  "row still grants it."),
		("b", "The five workflows are regenerated to match. This also happens on every "
			  "bench migrate."),
		("h3", "The stages"),
		("p", "Submit steps move a draft into the chain. Approval steps have an approve action "
			  "and a reject action. A gate is not a workflow step at all — it is a check on a "
			  "screen that reads its approvers from the same table."),
		("table", ("The approval stage catalogue", [
			"Stage", "Document", "Kind", "Waits in", "Action", "Per farm",
		], stage_rows())),

		("h2", "Settings reference"),
		("p", "Every field in Work Management Settings, in the order it appears on the form."),
	] + settings_blocks() + [

		("h2", "Definitions"),
		("b", "Man-day — one worker working one day (a worker on two tasks the same day is one "
			  "man-day)."),
		("b", "Ha / man-day — area of the blocks whose plans were worked, divided by the "
			  "man-days spent on them: how much ground one worker-day covers."),
		("b", "Cost / Ha — confirmed pay divided by the area worked: what a hectare of work "
			  "costs."),
		("b", "Available worker — an active employee with no live assignment covering the "
			  "chosen date."),
		("b", "Standard — the plan's daily expectation, e.g. 150 Meter/day @ KES 2.2667."),
		("b", "Presence evidence — a biometric check-in time, a Present attendance record, an "
			  "Absent record, or nothing (? — unknown)."),
		("b", "Farm — the unit work is planned against, whatever your project calls it."),
		("b", "Block — a Warehouse record standing for a piece of ground, optionally with its "
			  "area in hectares."),
		("b", "Stage — one step of an approval chain, configured in Settings."),
	]


KINDS = {"part", "h2", "h3", "p", "b", "n", "note", "table"}
