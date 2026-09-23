"""Switch on the "closed short" check, which arrives off through no choice of anyone's.

The third time this trap has cost something, and the second time in this file's
neighbourhood -- see switch_on_the_new_discrepancy_checks, whose docstring says
it plainly: a `default` on a doctype field applies to a NEW document. Work
Management Settings is a Single that already exists on every site, so adding a
Check field to it writes `'0'` into tabSingles, not the field's default.

Measured on kentrout.local the moment the field landed:

    disc_long_day        stored=1    switched on by that earlier patch
    disc_short_day       stored=1
    disc_hours_vs_qty    stored=1
    disc_closed_short    stored=0    disabled=1  <- shipped invisible

A check that arrives off is the exact failure the category exists to prevent.
The whole point of "Closed short of target" is that a run of short weeks stays
visible rather than becoming normality one plan at a time; shipping it switched
off would make the feature agree with the problem.

One field, and only where the stored value is 0. It is new, so no site can have
deliberately switched it off yet -- which is why this can run now and could not
run later. A `disc_*` field turned off by hand looks identical to one that was
never set, and correcting those indiscriminately would override somebody's
decision.

NOT the feature itself. `allow_short_submit` stays off, and no patch turns it on:
that one changes what the pipeline DOES -- it lets a week be submitted short and
caps the plan -- and no existing site's behaviour may move on a migrate. This
patch only makes a report show something it was always meant to show.
"""

import frappe

#: The one check added with the short-submit work. Named individually on purpose
#: -- see the docstring above and the patch this one follows.
NEW_CHECKS = ("disc_closed_short",)


def execute():
	if not frappe.db.exists("DocType", "Work Management Settings"):
		return
	meta = frappe.get_meta("Work Management Settings")
	switched = []
	for field in NEW_CHECKS:
		if not meta.get_field(field):
			# the field has not arrived yet; the next migrate will bring both
			continue
		try:
			stored = frappe.db.get_single_value("Work Management Settings", field)
		except Exception:
			stored = None
		if frappe.utils.cint(stored):
			continue
		frappe.db.set_single_value("Work Management Settings", field, 1)
		switched.append(field)
	if switched:
		frappe.db.commit()
		frappe.clear_cache(doctype="Work Management Settings")
		print("switched on: %s" % ", ".join(switched))
	else:
		print("the closed-short check is already on")
