# Farm manager week sign-off, clean-up, and per-farm history

Date: 2026-11-02. Asked for by james@ after the Sep–Oct task-pay audit, where drafts and
rejected actuals were never paid and nobody saw them, and farm managers had no way to
say that a week was complete.

## Why

Payment picks up whatever happens to be CONFIRMED when somebody builds a run. Nobody is
responsible for a farm's week being finished. Drafts are visible only to the clerk who
saved them, and rejected records only to the person who entered them. As of
2026-11-02, live held 34 drafts or rejected records older than 20 Oct.

## Decisions (the user's)

- **Week sign-off is an extra gate on top of the existing approval.** The farm manager
  still approves each record (quality score included). At the end of a week the FM
  also signs off the whole farm-week.
- Sign-off is refused while any record for that farm with work in that week is a Draft,
  Rejected, or waiting for the Farm Manager. Records already with the HR Head or GM
  don't block it.
- **Clean-up in the sign-off view:**
  - Rejected: Delete. Delete removes the record but keeps a log: who, when, why,
    worker-days, amount, and a snapshot. History shows it as "Deleted".
  - Draft: Notify. Emails the clerk who entered it, Cc HR and GM.
  - Draft: Complete it myself. The FM finishes the entry, and it goes to the FM's own
    approval queue and is approved normally.
- Sign-off emails HR and GM ("Lokitela 13–19 Oct signed off by Katule").
- **Payment leaves an unsigned farm-week out.** Other farms and weeks are paid, and the
  unsigned farm-week is listed as waiting for FM sign-off.
- **Work entered or approved after sign-off is allowed and flagged as late.** The week
  shows "N late records since sign-off".
- **History tab**, for one farm, covering all time and every status:
  - per employee, day by day
  - per activity
  - a month calendar with flags
  - CSV export (opens in Excel)
- Who sees history: an FM sees their own farm; HR Head, GM and System Manager see
  every farm.

## Builder's calls (not discussed; check these)

1. Pay weeks come from Settings (`pay_week_starts_on` / `pay_week_ends_on`, Mon–Sun on
   live), the same weeks payroll uses.
2. A record belongs to a week if any of its worker rows is dated in the week. A record
   with no rows yet (an empty draft) belongs to every week its from–to dates overlap.
3. **The payment gate is behind a Settings switch, "Require farm manager week sign-off
   before payment", default OFF.** Turning it on at deploy would stop every payment
   until each FM had signed off. Switch it on once FMs have started signing off.
4. HR/GM email recipients come from a Settings list ("Week sign-off emails to"). If it
   is empty, they fall back to the users on the Settings approver rows for Actuals: HR
   Head / Actuals: GM. On live, put hro@endebesscoffee.com and koskey@ in it, the same
   people the approval reminders mail.
5. **Reopening a signed-off week is GM / System Manager only**, with a reason, and
   reopening takes the week out of payment until it is signed off again.
6. An FM of the record's farm may now submit actuals. Before, only HR Clerk could, so
   "complete it myself" was impossible for an FM without that role. A comment records
   that the FM completed it on behalf of the clerk.
7. Export is CSV, not .xlsx. The screen has no spreadsheet library, and Excel opens CSV.

## Pieces

- New doctypes:
  - `Work Management Week Signoff`: farm, week_from, week_to, status, signed/reopened
    by/on, reason, snapshot counts. Named `WMWS-<farm>-<week_from>`, one per farm-week.
  - `Work Management Deleted Actuals`: the delete log.
- Settings fields: `week_signoff_required` (Check), `week_signoff_notify` (Small Text).
- `wm_actuals` actions:
  - `ws_meta`, `ws_week`, `ws_signoff`, `ws_reopen`, `ws_notify`, `ws_delete_rejected`
  - `hist_people`, `hist_tasks`, `hist_employee`, `hist_activity`, `hist_calendar`
- `wm_payment`: a SIGNED_ONLY SQL fragment on every payable selection when the switch
  is on, and `awaiting_signoff` on `pay_workers`.
- Actuals screen: tabs "Week sign-off" and "History". Payment screen: a banner listing
  farm-weeks waiting for sign-off.
