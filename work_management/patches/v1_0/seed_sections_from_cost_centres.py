"""Build sections from the grouping accounts already maintain in the ledger.

Where the Cost Center tree has been built out, it already says which blocks
belong together -- `SB1 - KL` sits under `SBT - Saboti - KL`. Reading that costs
nothing and saves opening dozens of records by hand.

It is only a head start. On the site this app came from, 52 of the 83 blocks
that plans have been raised against resolve to a parent cost centre and 31 do
not, and the ones that do not carry most of the work: the estate overheads and
the VALE-B series match no cost centre at all. Those are left for someone to
place deliberately rather than guessed at, and blocks in no section group under
Unassigned so no total goes missing.
"""

import frappe

from work_management import sections


def section_name_for(cost_centre, abbr):
	"""Drop the company abbreviation ERPNext appends to a cost-centre name."""
	suffix = f" - {abbr}"
	if abbr and cost_centre.endswith(suffix):
		return cost_centre[: -len(suffix)]
	return cost_centre


def parent_cost_centre(block):
	"""The group cost centre above this block's own, if the block maps to one."""
	cc = frappe.db.exists("Cost Center", block)
	if not cc:
		cc = frappe.db.get_value("Cost Center", {"cost_center_name": block}, "name")
	if not cc:
		return None
	parent = frappe.db.get_value("Cost Center", cc, "parent_cost_center")
	if not parent or not frappe.db.get_value("Cost Center", parent, "is_group"):
		return None
	return parent


def execute():
	for doctype in ("Work Management Section", "Cost Center", "Work Management Farm"):
		if not frappe.db.exists("DocType", doctype):
			return

	blocks = frappe.db.sql(
		"""select distinct block_section from `tabWork Management Planner`
		   where ifnull(block_section, '') != ''"""
	)
	created = placed = 0
	for (block,) in blocks:
		if sections.claimed_by(block):
			continue
		parent = parent_cost_centre(block)
		if not parent:
			continue
		farm = frappe.db.get_value("Warehouse", block, "custom_farm")
		if not farm or not frappe.db.exists("Work Management Farm", farm):
			continue
		abbr = frappe.db.get_value("Company", frappe.db.get_value("Cost Center", parent, "company"), "abbr")
		name = section_name_for(parent, abbr)

		if frappe.db.exists("Work Management Section", name):
			doc = frappe.get_doc("Work Management Section", name)
		else:
			doc = frappe.get_doc({
				"doctype": "Work Management Section", "section_name": name, "farm": farm,
			})
			doc.insert(ignore_permissions=True)
			created += 1
		doc.append("blocks", {"block": block})
		doc.flags.ignore_permissions = True
		doc.save()
		placed += 1

	frappe.db.commit()
	print(f"Work Management: seeded {created} section(s) holding {placed} block(s) from the ledger")
