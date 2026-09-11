# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Run a single-document action once per document, and report on each.

The client's words: *"the system allows submission and approval of one task at
a time... time consuming with a large number of people."* Master plans already
had a bulk path and Payment already had bulk send; the three approval tabs in
between did not.

**This does not implement approval.** It re-enters the calling module's own
action dispatcher once per document, with `action` and `name` swapped into
`frappe.form_dict` -- so the transition a bulk approve performs is, to the
letter, the transition the single button performs: the same role checks, the
same stage checks, the same writes, the same comment. There is no second
approval path to keep in step, because there is no second approval path.

The alternative -- copying each module's checks into a bulk branch, which is
what `wm_masterplan`'s `plans_bulk` does -- is how the two drift. One of them
gets a fix and the other does not, and the one that does not is the one people
use on a busy Friday.

**One savepoint per document.** A document that refuses is rolled back to
exactly where it started and the rest carry on; a document that raises is
caught, rolled back and reported by name. Partial success is the normal case
with a mixed queue, so it is a result to render rather than an error to raise.
"""

import frappe

#: How many documents one press may act on. Not a technical ceiling -- it is
#: the point past which somebody is no longer reviewing and is just clicking,
#: and a bulk approve is still an approval.
MAX_PER_CALL = 200


def run_bulk(dispatch, action, names, base=None, key="name"):
    """Call `dispatch()` once per name with `action`/`key` set in form_dict.

    `dispatch` is the module's whitelisted entry point -- wm_planner,
    wm_assigner, wm_actuals. It reads `frappe.form_dict`, so this swaps the
    document in, calls it, and puts the caller's own form_dict back afterwards
    whatever happens.

    `base` carries anything else the single action needs (a rejection reason,
    for instance). Returns ``(ok, failed)``: ok entries carry the name and the
    state it reached, failed entries carry the name and `why` in the single
    action's own words.
    """
    ok = []
    failed = []
    saved = dict(frappe.form_dict)
    try:
        for name in names:
            point = "wmbulk_" + frappe.generate_hash(length=8)
            frappe.db.savepoint(point)
            try:
                frappe.form_dict.clear()
                frappe.form_dict.update(base or {})
                frappe.form_dict["action"] = action
                frappe.form_dict[key] = name
                result = dispatch() or {}
                if result.get("error"):
                    # The single action refused. Its reason is the one the user
                    # would have seen pressing the button on that row, so it is
                    # the one reported -- not a bulk-flavoured paraphrase.
                    frappe.db.rollback(save_point=point)
                    failed.append({"name": name, "why": str(result["error"])})
                else:
                    ok.append({
                        "name": name,
                        "workflow_state": result.get("workflow_state"),
                        "step_label": result.get("step_label"),
                    })
            except Exception as exc:
                # A validation error raised rather than returned. Same treatment:
                # this document alone is undone, and the rest of the selection is
                # not punished for it.
                frappe.db.rollback(save_point=point)
                failed.append({"name": name,
                               "why": _readable(exc)})
    finally:
        frappe.form_dict.clear()
        frappe.form_dict.update(saved)
    return ok, failed


def _readable(exc):
    """A raised exception as one line a person can act on."""
    text = str(exc) or type(exc).__name__
    # frappe.throw carries HTML often enough to be worth stripping
    try:
        from frappe.utils import strip_html

        text = strip_html(text)
    except Exception:
        pass
    text = " ".join(text.split())
    return text[:300] if text else type(exc).__name__


def check_selection(names, reason=None, needs_reason=False):
    """Why this selection cannot be acted on, or None.

    Kept apart from run_bulk so the refusals are testable without a database,
    and so every module refuses an empty tick-box list and a missing rejection
    note in the same words.
    """
    if not isinstance(names, (list, tuple)):
        return "Nothing selected. Tick the rows you want to act on."
    clean = [n for n in names if n]
    if not clean:
        return "Nothing selected. Tick the rows you want to act on."
    if len(clean) > MAX_PER_CALL:
        return ("Too many at once: %d selected, %d is the most one action may take. "
                "Narrow the filters and go again." % (len(clean), MAX_PER_CALL))
    if needs_reason and not str(reason or "").strip():
        return "A reason is required to reject."
    return None


def summarise(ok, failed, verb="approved"):
    """One sentence for the toast, so every screen words it the same way."""
    if ok and not failed:
        return "%d %s." % (len(ok), verb)
    if ok and failed:
        return "%d %s, %d could not be." % (len(ok), verb, len(failed))
    if failed and not ok:
        return "None %s — %d could not be." % (verb, len(failed))
    return "Nothing to do."
