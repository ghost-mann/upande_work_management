Every step of every approval chain is configured in Work Management Settings, under Approvals. Nothing about who approves what is fixed in the software.

## The two tables

- Approval Stages — one row per step, seeded when the module is installed. The step and the document it belongs to are fixed; you set the role that takes it, and whether the step happens at all.
- Stage Approvers — one row per person per step: the stage, optionally the farm, the person, and optionally a role override. Saving grants each person the role their stage runs on.

The approval workflows are generated from these two tables. That means approvers get the ordinary Frappe experience — the action buttons on the document, the notifications, and the awaiting-approval inbox — rather than anything bespoke.

## Switching a step off

Clear the On box and the chain relinks around it: with the Assigner GM step off, HR approval sends the assignment straight to Assigned. Submit steps cannot be switched off, because a document nobody can submit is not a useful configuration.

## Approvers for one farm only

On a farm-scoped step, give each farm its own approver row and its own role override. That is what keeps one farm's approvals out of another farm's reach: the generated workflow carries a separate transition per farm, each allowed only to that farm's role.

Leaving the Farm cell empty means that person acts on every farm. Leaving the step with no approver rows at all means the stage's own role covers every farm.

> **Note** — Settings refuses to save a configuration that would strand a farm. If a farm-scoped step names approvers for some farms but not others, the farms left out would have nobody able to approve their work, and the error names them.

## What changes when you save

- Each listed approver is granted their stage's role. Roles granted by hand, for any other reason, are never touched.
- Removing someone from the table revokes the role it gave them, unless another row still grants it.
- The five workflows are regenerated to match. This also happens on every bench migrate.

## The stages

Submit steps move a draft into the chain. Approval steps have an approve action and a reject action. A gate is not a workflow step at all — it is a check on a screen that reads its approvers from the same table.

**The approval stage catalogue**

| Stage | Document | Kind | Waits in | Action | Per farm |
|---|---|---|---|---|---|
| Master Plan: Submit | Master Plan | Submit | Draft | Send for Consultant Review | — |
| Master Plan: Consultant | Master Plan | Approval | Pending Consultant | Send to GM | — |
| Master Plan: GM | Master Plan | Approval | Pending GM | GM Approve | — |
| Planner: Submit | Planner | Submit | Draft | Submit for Approval | — |
| Planner: Farm Approval | Planner | Approval | Pending Approval | Approve | Yes |
| Planner: Weekly Consultant | Planner | Gate | — | — | — |
| Assigner: Submit | Assigner | Submit | Draft | Submit for Approval | — |
| Assigner: Farm Manager | Assigner | Approval | Pending Farm Manager | FM Approve | Yes |
| Assigner: HR Head | Assigner | Approval | Pending HR Head | HR Approve | — |
| Assigner: GM | Assigner | Approval | Pending GM | GM Approve | — |
| Actuals: Submit | Actuals | Submit | Draft | Submit for Approval | — |
| Actuals: Farm Manager | Actuals | Approval | Pending Farm Manager | FM Approve | Yes |
| Actuals: HR Head | Actuals | Approval | Pending HR Head | HR Approve | — |
| Actuals: GM | Actuals | Approval | Pending GM | GM Approve | — |
| Payment: Accounts | Payment | Approval | Unpaid | Mark Paid | — |
