# Work Management phone app — design (2026-11-27)

## Why
Requested by james@ for Kaitet. Work Management runs as web pages (`/work-planner`,
`/work-assigner`, `/work-actuals`, `/work-payment`, `/work-management`). They were
built for desktop, and that slows down everyone who uses them in the field.
**Goal, in the user's words: "for transactions to move faster."** The user named
four causes, all of which matter:
1. The screens are hard to use on a phone (wide tables, a 3-column crew dialog).
2. There is no signal in the field. Work is written on paper and typed in late,
   which then shows up as missing work, late actuals and payroll check issues.
3. Approvals wait too long. Approvers don't know something is waiting.
4. Logging in and finding the pages is hard.

Users: everyone. Clerks, team leaders, farm managers, HR and the GM.

## Decisions (james@)
- **Native phone app (Expo / React Native), phased.** Not an installable web app,
  and not a wrapper around the web pages.
- **Android only, installed as an APK** from a download link. No Play Store and no iPhone.
- **Offline refusals are held on the phone.** If the server refuses an entry made
  offline (worker already recorded elsewhere, payroll check closed those dates, cut-off
  reason needed, and so on), it stays on the phone marked **Needs fixing** with the
  server's message. The user fixes and resends it, or deletes it. Nothing is silently
  dropped or forced through.
- **A separate Work Management app** with its own repo. It is not merged into the
  irrigation app.
- **Everyone uses it, and nobody is locked out** ("involve all users"). The app
  opens for any Kaitet login. What each person sees and can do follows their roles
  and farms on the server, exactly as on the web. **Team leaders enter their own
  crews' actuals.** Going live therefore includes logins for the team leaders who
  have none (many are keyed by Employee ID today) and giving them the right to record
  work for their crews. That access change is confirmed with james@ at go-live.
- **Everything follows whoever is logged in.** A phone can be personal or shared:
  each person's cache and outbox are kept under their own login. Switching user
  shows only that user's items, and entries are always sent under the name of the
  person who made them. Logging out while that person still has entries waiting
  to send is blocked, with the count shown, until they are sent or deleted.
- **Push uses the irrigation app's Expo (EAS) account**, with a new Firebase project
  for this app's Android push.
- **Repo:** `ghost-mann/upande-wm-mobile`, private, commits credited to ghost-mann only.

## Goals
- One login that stays logged in. The home screen shows what is waiting on *me*.
- Push notifications for everything waiting on the user, so approvals move the same day.
- Actuals entry that works with no signal and sends itself when signal returns.
- Every approval step on the phone: plans, assignments and actuals, at the FM, HR and GM steps.
- Later phases: assigning crews (including the late-reason prompt), Add crew and swap,
  then the planner, the payroll check and dashboards.

## Non-goals
- No new business rules. Every rule stays on the server (one worker / one day,
  the cut-off and late reason, the payroll check gate, attendance gates, quantity caps,
  separation of duties). The app calls the same `wm_*` actions as the web screens and
  shows the server's messages.
- The web screens stay. The app is an additional way in, not a replacement.
- No iPhone, no Play Store, no other clients (Mutara, Marginpar…) in this design.

## Anti-goals (a failure even if it "works")
- **Double pay from a resend.** A request that reaches the server, with the phone
  never hearing back, must not create a second actuals record when it is resent.
- **Silent loss of field work.** Anything entered on the phone must be visibly sent,
  pending or needing fixes, never just gone.
- **A second set of rules in the app** that drifts from the server.
- **Wrong person sees data.** The app must respect the same roles and farm scope as
  the web: team leaders see only their own work, and FMs only their farms.

## Approaches considered
1. **Native Expo app, phased (chosen).** It is the only option that properly fixes
   no signal (a reliable on-phone outbox) and slow approvals (push). Cost: a separate
   codebase and APK distribution.
2. **Installable web app.** One codebase, but browser storage is unreliable for pay
   data, and offline and push support is weaker.
3. **App shell around the web pages.** Quickest, but it fixes only login and push.
   The screens stay desktop-shaped and nothing works offline.

## Starting point
`ghost-mann/upande-irrigation-mobile` (Expo 54, expo-router, expo-sqlite, expo-secure-store,
EAS with an APK `preview` profile) already solves:
- Login with a Frappe session, kept in secure storage (`lib/auth.ts`, `lib/auth-storage.ts`).
- An SQLite outbox replayed when online (`lib/db.ts`, `lib/sync.ts`).
- Role lookup on live Frappe 16.36.1, which has no roles API. Roles are read from the
  `/desk` boot HTML (`"roles":[…]`).
- jest-expo tests with fixtures captured from live.

The new app copies these pieces into a new repo. It does not fork the irrigation
screens.

## Phases
**Phase 1: get transactions moving (first release)**
- Login, kept logged in, with the farm scope from the user's roles and permissions.
- **Home: "Waiting on me."** One list of what needs this user, by type and count:
  plans, assignments and actuals at their approval step, missing work to clear (phase 1
  shows the count and opens the web page; clearing in the app is phase 3, *Claude's
  call*), items needing fixes on the phone, and today's crews for team leaders. Tapping an item opens it.
- **Push notifications** when something reaches a step this user can act on.
- **Approvals:** the plan approve/reject actions (`wm_planner approve/reject`), assignments
  (`a_fm_approve/a_hr_approve/a_gm_approve/a_reject`) and actuals
  (`act_fm_approve/act_hr_approve/act_gm_approve/act_reject`), with the detail needed to decide.
- **Actuals entry, offline-first:** pick the assignment, enter quantity and hours per
  worker per day, then **Save** (a Draft) or **Send for approval**, the same two
  choices as the web screen. *(Claude's call)* Stored in the outbox and sent by
  `act_submit` when online.
- An **Outbox screen** listing Pending, Sent and Needs fixing items, with the server's
  message on each.

**Phase 2: crews.** New assignment from an approved plan (with the late-reason prompt
and the attendance override), Add crew, swap and release, plus my assignments.

**Phase 3: the rest.** Planner (create/submit), payroll check steps, missing work clearing,
the team leader card (Performance / Late assigning / People) and key dashboard numbers.

## Server changes (work_management app)
1. **Merge, don't overwrite, plus phone entry IDs.** Today `act_submit` keeps one
   actuals record per assignment and rewrites all its worker rows from each call.
   A phone sending only what it entered offline would therefore wipe days typed on
   the web or sent by another phone. For calls from the app (`merge=1`), the server
   **merges by worker + work date**: a row from the phone adds or replaces only that
   worker's day and leaves every other row alone. Each phone row carries a
   `client_ref` (a UUID made on the phone), stored on the row, so a resend changes
   nothing. *(Claude's call)* The same `client_ref` rule applies to the other create
   actions the app sends offline in later phases (`a_submit`, `a_add_crew`).
   Once an assignment's actuals are pending approval, the server keeps refusing new
   rows as it does today. The phone shows this as Needs fixing with the server's
   message.
2. **"Waiting on me" endpoint.** A single action returns this user's queues with counts
   and rows, using the same rules as the dashboard's action queues and each screen's
   pending lists. It respects roles and farms.
3. **Push.**
   - A doctype for devices: user, Expo push token, last seen, active.
   - App actions to register and unregister a device.
   - A hook that sends a push when a record enters a step, to the users who can act on
     it (the same people the approval emails go to).
   - Sending goes through Expo's push service. Notification text stays generic,
     e.g. "3 assignments waiting for your approval", with no worker names or pay figures.
4. **Sessions.** The user stays logged in. The app re-logs in quietly when the session
   expires, using credentials held in secure storage, as the irrigation app does.

## Offline behaviour
- Cached on the phone at each sync, for offline entry: my assignments and their crews,
  task names and targets, and today's date window. Entry offline is limited to
  assignments already on the phone.
- An outbox row holds the action, its arguments, the `client_ref`, status
  (pending / sent / needs_fixing) and the server's last message.
- Rows replay oldest first. A server refusal (`error` in the response, or a 417)
  → **needs_fixing**. A network failure → stays pending and retries later.
- Prompts the server sends back, such as `needs_late_reason` or `needs_att_override`,
  are also needs_fixing. The user answers them in the app and resends.
- The screen always shows how many items are waiting to send.

## Distribution
APK built with EAS (`preview` profile) and shared by download link. Updates come
as a new APK (plus Expo OTA updates for JS-only changes, if wanted). Live URL
`https://kaitet-group.upande.com`.

## Left to the builder
Screen layouts and navigation; the exact cache shape; retry timing; how the push
hook finds recipients (reuse the approval-reminder and Stage Approver rules);
naming of the new doctype and actions; test approach (jest fixtures from live, plus
server unit tests in the site-less suite).
