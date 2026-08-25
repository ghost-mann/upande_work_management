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


def roll_up(rows, mapping):
	"""Total per-block cost-centre rows into per-section rows, biggest spend first.

	Mirrors the shape of the farm-level rollup already in the cost-centre view:
	sum the same money/quantity fields (labour_spend, gl_spend, qty,
	worker_days), count the blocks, then derive cost_per_unit guarded on qty
	being positive. Pure -- no frappe calls -- so the arithmetic is testable
	without a site.

	A block with no section (mapping.get(block) is falsy) lands under
	UNASSIGNED rather than being dropped, which is what keeps the section
	view summing to the same figure as the block view it replaces.
	"""
	grouped = {}
	fields = ("labour_spend", "gl_spend", "qty", "worker_days")
	for row in rows:
		key = mapping.get(row.get("block")) or UNASSIGNED
		bucket = grouped.setdefault(
			key, {"key": key, "blocks": 0, **{f: 0.0 for f in fields}}
		)
		bucket["blocks"] += 1
		for field in fields:
			bucket[field] += float(row.get(field) or 0)
	for bucket in grouped.values():
		bucket["cost_per_unit"] = (
			(bucket["labour_spend"] / bucket["qty"]) if bucket["qty"] > 0 else None
		)
	return sorted(grouped.values(), key=lambda r: -r["labour_spend"])
