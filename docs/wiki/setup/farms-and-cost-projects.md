A farm is the unit work is planned against. Whatever your project calls it — farm, estate, site, division, block group — create one Farm record for each in Upande Core, and the rest of the module follows that naming. Farms belong to Upande Core rather than to this module, so one list of farms serves every Upande app on the site.

- Farm Name — it appears in every picker and is stored on every plan, assignment, actuals document and payment. Company, Farm Type and Abbreviation are Upande Core's own required fields.

Two things this module needs are not on Core's farm record, and are set under Work Management Settings → Farms, one row per farm:

- Cost Project — costs recorded for this farm are attributed to this project. The Rates tab reads it to decide which tasks exist, so a farm without one shows an empty task list.
- Area (HA) — an override, for the farms whose own area in Upande Core is not the figure the efficiency numbers should divide by. Leave it empty to use Core's.

> **Note** — A row naming a farm Upande Core has not got is ignored. Which farms exist is Core's answer alone — create the farm there first.

Three things on core records then have to be tagged, or the screens have nothing to offer:

- Warehouses used as blocks — set Farm, and set Area (HA) if you want the efficiency figures in Field intelligence to work.
- Employees who do task work — set Unit/Division to their farm.
- Tasks — set UoM, Daily Target and Rate. These are the standard a plan inherits, and the Task list is where rates are edited day to day.

> **Note** — Editing a rate on a Task records a rate period starting today, so rate history writes itself. Backdated rate changes belong to a rate card, applied from the Rates section of Settings.
