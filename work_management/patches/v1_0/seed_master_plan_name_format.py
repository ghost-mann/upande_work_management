"""Altura names master plans after the greenhouse they budget: GH-3-MP-26-001.

The `altura` branch is Altura's alone (docs/ALTURA_FORK.md), so this seeds
Altura's format on whatever site runs this branch, without keying on a
hostname. Any other site leaves Settings > Naming > Document names empty and
keeps the doctype's own WMMP-#####.

INSERT IF MISSING, NEVER OVERWRITE -- the rule seed_monthly_pay_period follows,
for the same reason: a site that has typed its own format keeps it. An empty
stored value counts as missing, so clearing the field and migrating again puts
Altura's format back; to opt out on this branch, set a different format.

Existing master plans keep their names. Only plans created after this runs are
named by the format.
"""

import frappe

from work_management.patches.v1_0.seed_monthly_pay_period import stored

FIELD = "mp_name_format"
ALTURA_FORMAT = "{greenhouse}-MP-{YY}-{###}"


def execute():
	if not frappe.db.exists("DocType", "Work Management Settings"):
		return
	if not frappe.get_meta("Work Management Settings").get_field(FIELD):
		# not synced yet; the next migrate brings the field and this with it
		return
	if stored(FIELD) is not None:
		return
	frappe.db.set_single_value("Work Management Settings", FIELD, ALTURA_FORMAT)
	frappe.db.commit()
	frappe.clear_cache(doctype="Work Management Settings")
	print("seeded: %s=%s" % (FIELD, ALTURA_FORMAT))
