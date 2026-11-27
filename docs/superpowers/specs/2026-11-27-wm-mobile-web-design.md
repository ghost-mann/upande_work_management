# Work Management screens on phones — design (2026-11-27)

## Why
james@ tried the phone app plan and found it "really shitty": missing features, looks, and hard to use. The app must mirror **all** of the web app's functionality. Of three options, james@ chose **making the web screens themselves phone-friendly**, accepting a change to the ERP's Work Management app. One codebase means every feature and every fix reaches the phone and the web together. james@: "improvise, adapt, overcome, become dynamic."

## Decisions
- The five screens served by the app get a phone layout: `/work-planner` (including master plans, rates and team leaders), `/work-assigner`, `/work-actuals` (including missing work and the payroll check), `/work-payment` and `/work-management` (dashboard). **Desktop stays exactly as it is.**
- **One shared phone layer**, loaded by every screen:
  - `public/css/wm-mobile.css`: rules only under `@media (max-width: 767px)`.
  - `public/js/wm-mobile.js`: phone-only behaviour, which does nothing above 767px.

  Per-screen fixes go in the same two files, scoped by each screen's root id (`#wmp`, `#wpp`, `#wap`, `#acp`, `#wpay`). The screen scripts mirrored from `kaitet-work-management` are left alone wherever possible, and must stay byte-identical with it.
- **Phone layout rules:**
  - Tables become cards. Each cell is labelled with its column heading; ids, buttons and states stay at the top.
  - Tab bars scroll sideways.
  - Filter rows fold behind a "Filters" button.
  - Dialogs and overlays (crew screen, reason boxes, detail sheets) open full screen.
  - Touch targets are at least 44px, and inputs use 16px text so phones don't zoom in.
  - The top navigation becomes a fixed bottom bar: Home, Plan, Assign, Work, Pay.
  - Wide grids (the actuals worker-by-day grid) scroll inside their card, with the first column pinned.
- **Same theme:** colours and fonts unchanged.
- **The phone app** (`ghost-mann/upande-wm-mobile`) becomes a frame. You log in once and these web screens open inside it with the session shared, so every feature is there. It keeps its native extras: offline work entry (outbox) and background notifications. The native approval and crew screens are retired, so there are never two versions of a screen.

## Order
1. Shared layer, plus Actuals and Assigner (the field screens).
2. Planner and Dashboard.
3. Payment.

Each screen is checked at phone size (390×844) as a real user (clerk, FM) on webstore.localhost, with screenshots, before it counts as done.

## Non-goals
- No change to server rules or desktop layout.
- Attendance dashboard and aerial farm layout aren't served by this app (they are Web Pages on live), so they are out of scope here.
