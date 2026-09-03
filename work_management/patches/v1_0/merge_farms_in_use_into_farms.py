"""Fold the farms-in-use picker into the one farms table.

Settings briefly had two fields about farms: a picker deciding which farms the
screens offered, and a table supplying each farm's cost project. A farm could
need to be in both, and nothing said so -- somebody setting a cost project still
saw every farm, and somebody narrowing the farms still had no project.

So there is one table now, and a checkbox saying whether it narrows. This carries
the picker's rows across and ticks that checkbox, because a site that had narrowed
its farms must stay narrowed: silently widening it would put farms back on five
screens that somebody had deliberately taken off them.

The picker's rows are the only source of the answer, and its child table is
deleted with this release, so this runs once and cannot be re-derived later.
"""

import frappe

OLD_FIELD = "farms_in_use"
OLD_CHILD = "Work Management Farm In Use"


def execute():
	if not frappe.db.exists("DocType", "Work Management Settings"):
		return
	# The picker's child doctype existing is the whole signal, and the only one
	# available: Work Management Settings is a Single, so it has no table and
	# has_column() on it raises TableMissingError rather than answering False.
	# A fresh install never had the picker and stops here.
	if not frappe.db.exists("DocType", OLD_CHILD):
		return
	# table_exists(), not `in get_tables()`: get_tables() returns raw table names,
	# so a bare doctype name is never in it and that guard returned every time --
	# this patch could not carry a row on any site.
	if not frappe.db.table_exists(OLD_CHILD):
		return  # the doctype record survives without its table on some sites
	chosen = frappe.db.sql_list(
		"""
		SELECT farm FROM `tab{child}`
		WHERE parenttype = 'Work Management Settings' AND parentfield = %(f)s
		  AND IFNULL(farm, '') != ''
		""".format(child=OLD_CHILD),
		{"f": OLD_FIELD},
	)
	if not chosen:
		return

	settings = frappe.get_doc("Work Management Settings")
	already = {row.farm for row in (settings.get("farms") or []) if row.farm}
	added = []
	for farm in chosen:
		if farm in already:
			continue
		# no cost project and no area: this row says "we work this farm", which is
		# exactly what the picker said. The project is somebody's to fill in.
		settings.append("farms", {"farm": farm})
		added.append(farm)

	# the picker narrowed, so the table must go on narrowing
	settings.farms_restrict = 1
	settings.flags.ignore_permissions = True
	settings.flags.skip_approval_sync = True
	settings.save()
	frappe.db.commit()

	print(
		"Work Management: moved %d farm(s) from the picker into the farms table, and "
		"turned on 'Only work the farms listed below' so the screens stay narrowed"
		% len(chosen)
	)
	if added:
		print("Work Management: added rows for " + ", ".join(added)
		      + " -- give each one its cost project")
