"""Sections: a grouping of blocks, used to total cost by section.

A section is not a level of the hierarchy. It never appears on a plan, an
assignment, actuals or a payment, and no screen label depends on it. Its whole
job is to let the cost-centre view be read by section instead of by block.

The section owns its blocks rather than each block naming its section, so
setting one up means opening a section and adding blocks to it. A block belongs
to at most one section: counted in two it would double its cost, and the section
totals would quietly stop matching the block totals they are built from.
"""

import frappe

# Blocks in no section still have to appear, or a section view would silently
# total less than the block view it replaces.
UNASSIGNED = "Unassigned"


def duplicate_blocks(rows):
	"""Blocks listed more than once in one section's table, in first-seen order."""
	seen, repeated = set(), []
	for row in rows or []:
		block = (row.get("block") if isinstance(row, dict) else row.block) or ""
		block = block.strip()
		if not block:
			continue
		if block in seen and block not in repeated:
			repeated.append(block)
		seen.add(block)
	return repeated


def claimed_by(block, exclude=None):
	"""The section already holding this block, if any."""
	rows = frappe.get_all(
		"Work Management Section Block",
		filters={"block": block, "parenttype": "Work Management Section"},
		fields=["parent"],
	)
	for row in rows:
		if row.parent != exclude:
			return row.parent
	return None


def section_of(block):
	"""The section a block belongs to, or None."""
	return claimed_by(block)


def block_to_section():
	"""{block: section} for every block that has been placed in one."""
	mapping = {}
	for row in frappe.get_all(
		"Work Management Section Block",
		filters={"parenttype": "Work Management Section"},
		fields=["block", "parent"],
	):
		mapping[row.block] = row.parent
	return mapping
