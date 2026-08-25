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


def enabled_block_to_section():
	"""{block: section} for the sections the cost-centre toggle still shows.

	A disabled section is hidden from the toggle, so its blocks have to fall
	back to Unassigned -- in the rollup and in the drill-down alike. Both read
	this, rather than each deciding for itself, because a row that totals money
	the drill-down then refuses to show is worse than either behaviour alone.
	"""
	disabled = set(
		frappe.get_all("Work Management Section", filters={"disabled": 1}, pluck="name")
	)
	return {b: s for b, s in block_to_section().items() if s not in disabled}


def group_condition(column, key, mapping):
	"""(SQL fragment, params) restricting cost rows to the blocks of one group.

	No actuals record carries a section name -- `block_section` holds a block --
	so drilling into a section row means asking for the blocks that section
	holds. Asking for the section name itself is what made the drill-down
	return nothing at all.

	UNASSIGNED is the complement, written as a negation so it needs no list of
	every block that has ever existed. A named section holding nothing matches
	nothing rather than everything: an empty `in ()` is a SQL error, and
	dropping the condition would show the whole site's spend under a section
	with no blocks in it.

	`column` is a literal from our own code. The group name and the block names
	are typed by hand, so they go in params, never into the fragment.
	"""
	if key == UNASSIGNED:
		claimed = sorted(mapping)
		if not claimed:
			return "1=1", []
		return f"{column} not in ({_placeholders(claimed)})", claimed
	held = blocks_of(key, mapping)
	if not held:
		return "1=0", []
	return f"{column} in ({_placeholders(held)})", held


def blocks_of(key, mapping):
	"""The blocks one named section holds, in name order.

	Empty for UNASSIGNED, which is defined by the blocks it excludes rather
	than by a list of its own -- and which has no single grouping account
	behind it for the GL breakdown to read.
	"""
	if key == UNASSIGNED:
		return []
	return sorted(block for block, section in mapping.items() if section == key)


def _placeholders(values):
	return ", ".join(["%s"] * len(values))


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


def totals(rows):
	"""Total a list of rollup buckets, for the strip above the cost-centre table.

	`blocks` counts the blocks the buckets hold between them, never the buckets
	themselves. Reading it off the rolled-up list was a real bug once: the
	strip reported "3 Blocks" on a site with eighty-three of them, because
	three was the number of sections. It stays a block count in both toggle
	positions and under a search that narrows either one.
	"""
	return {
		"labour": sum(r["labour_spend"] for r in rows),
		"gl": sum(r["gl_spend"] for r in rows),
		"qty": sum(r["qty"] for r in rows),
		"worker_days": sum(r["worker_days"] for r in rows),
		"blocks": sum(r["blocks"] for r in rows),
	}


def roll_up(rows, mapping):
	"""Total per-block cost-centre rows into per-section rows, biggest spend first.

	Mirrors the shape of the farm-level rollup already in the cost-centre view:
	sum the same money/quantity fields (labour_spend, gl_spend, qty,
	worker_days), count the blocks, then derive the ratios of those sums --
	cost_per_unit, cost_per_wd, labour_share -- each guarded on its divisor
	being positive. Pure -- no frappe calls -- so the arithmetic is testable
	without a site.

	A block with no section (mapping.get(block) is falsy) lands under
	UNASSIGNED rather than being dropped, which is what keeps the section
	view summing to the same figure as the block view it replaces.

	The weekly trend behind each sparkline is merged week by week, so a section
	has a sparkline of its own instead of a blank column. What cannot be added
	is left out: `workers` and `tasks` are counts of distinct things and two
	blocks can share both, so summing them would overstate. Those columns stay
	empty in section mode on purpose.

	The farm comes along where the blocks agree on one. A section belongs to a
	single farm, so its rollup normally does too, and carrying it keeps the farm
	column, the treemap's farm colours and the "Colour: by farm" option working
	in both toggle positions. UNASSIGNED collects blocks from every farm, and
	naming one of them there would attribute the others' money to it -- so a
	bucket whose rows disagree carries no farm rather than the first one seen.
	"""
	grouped = {}
	farms = {}
	weeks = {}
	fields = ("labour_spend", "gl_spend", "qty", "worker_days")
	for row in rows:
		key = mapping.get(row.get("block")) or UNASSIGNED
		bucket = grouped.setdefault(
			key, {"key": key, "blocks": 0, **{f: 0.0 for f in fields}}
		)
		bucket["blocks"] += 1
		farms.setdefault(key, set()).add(row.get("farm"))
		by_week = weeks.setdefault(key, {})
		for point in row.get("trend") or []:
			by_week[point["w"]] = by_week.get(point["w"], 0.0) + float(point.get("pay") or 0)
		for field in fields:
			bucket[field] += float(row.get(field) or 0)
	for key, bucket in grouped.items():
		bucket["farm"] = next(iter(farms[key])) if len(farms[key]) == 1 else None
		bucket["trend"] = [
			{"w": week, "pay": weeks[key][week]} for week in sorted(weeks[key])
		]
		bucket["cost_per_unit"] = (
			(bucket["labour_spend"] / bucket["qty"]) if bucket["qty"] > 0 else None
		)
		bucket["cost_per_wd"] = (
			(bucket["labour_spend"] / bucket["worker_days"]) if bucket["worker_days"] > 0 else None
		)
		# None, not zero: zero reads as "labour is 0% of cost", which is the
		# opposite of "nothing has been posted to compare against".
		bucket["labour_share"] = (
			(bucket["labour_spend"] / bucket["gl_spend"] * 100) if bucket["gl_spend"] > 0 else None
		)
	return sorted(grouped.values(), key=lambda r: -r["labour_spend"])
