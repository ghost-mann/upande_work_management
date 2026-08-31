Every field in Work Management Settings, in the order it appears on the form.

**Defaults**

| Setting | Type | What it does |
|---|---|---|
| Default Company | Link | Used on new plans, assignments and payments. Falls back to the site's own default company when empty. |
| Block Exclude Keywords | Small Text | Comma-separated keywords. Warehouses whose name contains any of these are hidden from the block picker (e.g. Store, Mill, Tank). |

**Farms**

| Setting | Type | What it does |
|---|---|---|
| Only work the Farms listed below | Check | Off: every farm in Upande Core is available, and the table below only supplies cost projects and area overrides. On: the screens offer just the farms listed. Off by default, so adding a row to give a farm its cost project never hides the others. |
| Farms in use | Table | One row per farm this project works: its cost project — which is where a plan's activities come from — and an area override where the farm's own area is not the figure to divide by. The farms themselves are Upande Core's records. Whether this list also narrows the screens is the checkbox above. |

**Approvals**

| Setting | Type | What it does |
|---|---|---|
| Approval Stages | Table | One row per step of every approval chain, seeded on install. The step and its document are fixed; set the role that takes it, and clear On to drop the step and relink the chain around it. Submit steps cannot be switched off. |
| Stage Approvers | Table | One row per person per stage. Leave Farm empty for someone who approves every farm. On a farm-scoped stage, give each farm its own role override to stop one farm's manager approving another's. |

**Taxonomy**

| Setting | Type | What it does |
|---|---|---|
| Use a level above the farm | Check | Names the level above the farm, for Employee records and for reports. Farms themselves are Upande Core's records and carry no business unit of their own. |
| Level above the farm (singular) | Data | Default: Business Unit. |
| Level above the farm (plural) | Data | Default: Business Units. |
| Farm level (singular) | Data | Default: Farm. Estate, site, division — whatever your project calls it. |
| Farm level (plural) | Data | Default: Farms. |
| Block level (singular) | Data | Default: Block. The piece of ground work is planned against. |
| Block level (plural) | Data | Default: Blocks. |
| Cost grouping (singular) | Data | Default: Section. Names the grouping the cost-centre view can be switched to, and the toggle that switches it. |
| Cost grouping (plural) | Data | Default: Sections. |

**Time & Attendance integration**

| Setting | Type | What it does |
|---|---|---|
| Check attendance (block employees marked Absent) | Check | Blocks when a submitted Attendance record says Absent on the date. Missing attendance never blocks. |
| Check approved leaves | Check | Blocks when an approved Leave Application covers the date(s). |
| Check weekly offs / holidays | Check | Actuals: blocks recording work on the employee's off day. Assigner: flags only when offs cover the whole assignment window. |
| Require a morning scan for day-of assignment | Check | When an assignment window includes today (and the cutoff has passed), workers with no biometric scan and no Present attendance today need an override. Night-shift workers are exempt. |
| Show today's presence on the assigner | Check | On: each worker on the assigner carries a chip for today — P with the scan time when an Employee Checkin or a submitted Attendance says they are on site, A when marked Absent, ? when there is neither. Off by default, because a site without biometric hardware or with attendance kept elsewhere gets ? on every worker, which reads as information and is not. Off, the reads do not run. |
| Morning scan cutoff | Time | Before this time, missing scans are shown as a grey chip only — no override dialog. |
| Check scans when recording actuals | Check | Recording a quantity for a worker with zero biometric scans and no Present attendance on that work date needs an override. |
| Off-day rule when assigning | Select | Entire window: only flag a worker whose off days cover the WHOLE assignment period. Any off day: flag any off day inside the period. Ignore: off days never flag at assignment (actuals still checks the exact day). |

**Discrepancy checks (Audit → Discrepancies)**

| Setting | Type | What it does |
|---|---|---|
| Paid on marked-Absent days | Check | Flags a paid day where attendance says the worker was Absent. Days whose attendance was later corrected are never flagged. |
| No presence evidence at all (no scan, no attendance) | Check | Flags a paid day with no biometric scan and no attendance record of any kind. |
| Earning while on approved leave | Check | Flags a paid day that falls inside an approved leave application. |
| Work recorded on off days / holidays | Check | Flags work recorded on a weekly off or a holiday. Legitimate when overtime was deliberate. |
| Amount doesn't match qty × rate | Check | Flags a row whose amount is not quantity times rate — usually an edited or corrupted value. |
| Two Farms, one day | Check | Flags a worker paid on two farms for the same day. |
| Entered and approved by the same person | Check | Flags work entered and approved by the same person, so nothing had an independent check. |
| Earning after leaving the job | Check | Flags earnings dated after the worker's leaving date. |
| Recorded work with no pay (zero-valued rows) | Check | Flags rows valued at zero although the document carries a rate. Repairable in one click. |
| Paid twice for the same day (duplicate entries) | Check | Flags the same worker, task and date recorded in two documents. Repairable in one click, keeping the earliest copy. |
| Left the company but still on live assignments | Check | Flags employees who have left but are still on live assignments. |
| Auto-release inactive employees from assignments | Check | When ON: deactivating an employee in HR marks their Active rows on live assignments as Left (dated today) with a comment on each assignment. |

**Consultant weekly review**

| Setting | Type | What it does |
|---|---|---|
| Require consultant approval for future-week plans | Check | Plans starting in an upcoming week cannot be approved by the Farm Manager until a consultant approves the farm's week on the Weekly review tab (/work-planner). Same-week plans are exempt. |
| Consultant users (comma-separated emails) (read-only) | Small Text | Superseded by Stage Approvers rows on the Planner: Weekly Consultant stage. Read-only, and removed in the next release. |
| Master plan post-approval editors (comma-separated emails) | Small Text | Who may correct a master plan after it is approved. Empty means nobody, which is the default. System Manager is deliberately not swept in — an administrator who must intervene already has the Desk form. |

**Rates**

| Setting | Type | What it does |
|---|---|---|
| Current Daily Wage (read-only) | Currency | The daily wage most active rate periods are derived from. Read-only — change it by applying a rate card, not by typing here. |

**Recalculate from a date**

| Setting | Type | What it does |
|---|---|---|
| Recalculate From | Date | Revalue work dated on or after this day, e.g. 2026-07-21 for the 340 → 387 rate card. |
| Recalculate To | Date | Optional upper bound. Leave empty to run to the latest recorded work. |
| Farm Scope | Data | Leave empty for all farms. |
| Dry Run | Check | On: report what would change and write nothing. Turn this off only after reading the dry-run figures. |

**Last recalculation**

| Setting | Type | What it does |
|---|---|---|
| Last Run (read-only) | Link | The Work Rate Recalc Run document the last recalculation wrote. Set by the system. |
| Last Run On (read-only) | Datetime | When the last recalculation ran. Set by the system. |
| Last Run By (read-only) | Link | Who ran the last recalculation. Set by the system. |
| Last Run Summary (read-only) | Small Text | What the last recalculation changed. Set by the system. |

**Payroll**

| Setting | Type | What it does |
|---|---|---|
| Salary Component | Link | Earning component the Additional Salary is raised against. Leave empty to stop Additional Salary records being created. |

**Who this system pays**

| Setting | Type | What it does |
|---|---|---|
| Employment types paid here | Table MultiSelect | Pick them. Anyone whose employment type is listed is paid per unit. |
| Employment types paid here (old, typed) | Small Text | Superseded by the picker above. Still read when the picker is empty, so nothing changes until you fill it in; it will be removed once every site has. |
| Designations paid here | Table MultiSelect | Pick them. Any one of these three lists matching is enough. |
| Designations paid here (old, typed) | Small Text | Superseded by the picker above. Still read when the picker is empty, so nothing changes until you fill it in; it will be removed once every site has. |
| Categories paid here | Table | Pick them. Category is a Select on Employee, so these are chosen from the same options rather than linked. |
| Categories paid here (old, typed) | Small Text | Superseded by the picker above. Still read when the picker is empty, so nothing changes until you fill it in; it will be removed once every site has. |
| Allow sending the week still in progress | Check | Off: a pay week can only be sent once it closes, so a week is never paid twice. On: the current week can be sent for the days worked so far. |
| Pay week starts on | Select | The weekday a pay week opens. Default Sunday. Together with the closing day this decides how work is grouped into weekly payments. |
| Pay week ends on | Select | The weekday a pay week closes. Default Saturday. If the span is shorter than seven days, the weekdays left over belong to no week at all and cannot be sent unless single-day sending is on. |
| Pay day | Select | The weekday payment is expected. Defaults to the closing day. |
| Also allow sending a chosen range of days | Check | Pay weeks can always be sent -- one payment per worker per completed week, which is what payroll has always received. Tick this to additionally offer paying a range you choose: one day, five days, a fortnight, up to a month. The range is grouped from the first date selected rather than into pay weeks, so it can pay a weekday the pay week above leaves out, which cannot be sent weekly at all. Ticking this changes nothing on its own -- an ordinary send still groups into pay weeks. |

**Branding**

| Setting | Type | What it does |
|---|---|---|
| Header Logo | Attach Image | Shown in the header of the five work screens. Leave empty for the module's own wordmark. |
