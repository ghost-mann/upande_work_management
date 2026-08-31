# Frappe Wiki user guides for upande_crm, work_management and upande_webstore

**Date:** 2026-08-31
**Status:** approved (design approved in chat; two open questions decided by the
implementer as recorded under "Decisions taken")

## Problem

Three apps — `upande_crm`, `work_management`, `upande_webstore` — each carry user
documentation in a different, hard-to-read format: a 55 KB `.docx`, a Python
module of content tuples, and a `.docx` built by a 33 KB script. None of it is
browsable by the people who need it, and none of it is in the site's Wiki.

The goal is one browsable guide per app in Frappe Wiki, with the source of truth
staying in git.

## Decisions taken

Both were flagged in the design and left to the implementer when the requester
went AFK with "finish":

1. **The CRM "presentation companion" (Part 5) is dropped.** Suggested demo
   running order, slides worth having, and questions-to-expect are
   sales-enablement material for a specific session in August 2026, not user
   documentation. Retained: Parts 1–4 and all three appendices.
2. **One publisher, in this repo.** `scripts/publish_wiki.py` takes `--docs`, so
   the same script publishes all three apps rather than three copies drifting
   apart. Trade-off accepted: the other two repos depend on this one to publish.
   If per-repo CI publishing is wanted later, vendor a copy into each.

## Target platform

The site runs **Frappe Wiki 3.0.0**, which is not the Wiki most documentation
describes. Established by probe against `kaitetv16-staging` (spike created and
deleted, site left clean):

- Content lives in a `Wiki Document` nested-set tree (`lft`/`rgt`,
  `parent_wiki_document`, `is_group`, `sort_order`), **not** in the legacy
  `Wiki Page` + `Wiki Group Item` model. Writing the legacy doctypes would
  produce rows the v3 UI never shows.
- `Wiki Document.content` is markdown and **renders directly**. No
  `Wiki Revision`, `Wiki Content Blob` or Change Request is required to publish;
  those are the version-history and review machinery.
- Inserting a `Wiki Space` auto-creates its `root_group` document.
- `route` is derived as `parent_route/slug`, `slug` from `title`, and `doc_key`
  is auto-generated. The nested set is maintained by the framework.
- `source_path` is a free-form `Data` field — used here as the idempotency key.
- Guests get 404; authenticated users get 200. Correct default for internal
  guides, so no `Wiki Space Role` rows are configured.

## Repo layout

Each app repo gets:

    docs/wiki/
      wiki.json          space metadata + the ordered tree
      <group-slug>/
        <page-slug>.md

`wiki.json` shape:

    {
      "space_name": "Work Management User Guide",
      "route": "work-management-guide",
      "groups": [
        { "title": "Getting Started",
          "pages": [ { "title": "The Pipeline at a Glance",
                       "file": "getting-started/pipeline-at-a-glance.md" } ] }
      ]
    }

Order is manifest position, written to `sort_order`. The manifest is explicit
rather than filename-encoded so titles can contain punctuation and pages can be
reordered without renaming files.

## Publisher

`scripts/publish_wiki.py --docs <repo>/docs/wiki --site <url> [--dry-run]`

- Token from `WIKI_TOKEN` env var (`api_key:api_secret`). Never committed, never
  a CLI argument (CLI args leak into shell history and `ps`).
- Upsert by `source_path`, which is set to the manifest-relative file path:
  found → `PUT` the changed fields; not found → `POST`.
- Space is matched on `route`, created if absent.
- Groups are documents with `is_group=1`; pages hang off their group.
- Idempotent: a second run with no content change makes no writes.
- `--dry-run` prints the plan without writing.

## Content sources and treatment

| App | Source | Treatment |
|---|---|---|
| `upande_crm` | `docs/*.docx` (7,129 words) | Extracted to markdown, split by heading, Part 5 dropped |
| `work_management` | `docs/manual_content.py` | Rendered mechanically from the content tuples |
| `upande_webstore` | `docs/02-user-guide.docx`, `04-customisation-manual.docx` | Extracted; portal section expanded from code |

The work_management manual generates two chapters from code
(`approvals.CATALOGUE` and the settings doctype JSON), so those cannot drift and
are carried through as generated.

## Verification performed against code

- **CRM:** `frontend/src/nav.js` matches every "Views available" table in the
  docx exactly; `CRM_ROLES` in `api/crm.py` matches the stated role list; the
  seven Settings tabs match `sections/Settings/index.jsx`. Note the Settings
  *doctype* has six sections and no Integrations — the seven tabs are a frontend
  concern, and the docx is describing the SPA correctly.
- **Webstore:** the customisation manual says the Features tab has "nineteen
  switches"; it has **twenty** (10 storefront, 10 portal). Corrected in the
  guide. Portal has 13 routes against the docx's single "Your portal" section,
  so that section is split into four pages.

## Out of scope

`docs/manual_content.py` and `docs/build_guides.py` still build the `.docx`
outputs and now overlap the wiki markdown, so the two can drift. Not addressed
here. A follow-up could make those builders read `docs/wiki/` instead.
