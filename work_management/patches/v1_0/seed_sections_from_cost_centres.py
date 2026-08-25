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

Reading someone else's tree also means reading someone else's ambiguity. A
`Cost Center`'s `name` carries the company abbreviation ERPNext appends and so
is unique, but `cost_center_name` does not and is not scoped to a company --
on a site with more than one company, two of them can genuinely share one. A
block that only matches by `cost_center_name`, and matches more than one
Cost Center that way, is left unassigned rather than bound to a guess at which
company it belongs to. The same refusal applies to reusing an existing
section: if two companies' trees strip to the same section name, a block is
only added to that section when the section's farm already matches the
block's own -- otherwise it would silently move part of one farm's total into
another's section.
"""

import frappe

from work_management import migrating, sections

# `select distinct` with no ordering leaves iteration order up to the
# database. That does not matter when every block resolves independently, but
# it does once ambiguity or section reuse is possible -- ordering makes a run
# reproducible instead of nondeterministic.
PLANNER_BLOCKS_SQL = """select distinct block_section from `tabWork Management Planner`
	where ifnull(block_section, '') != ''
	order by block_section"""

# What placing one block did. CREATED means a section was made for it, so the
# block landed too -- the summary counts it under both.
CREATED = "created"
PLACED = "placed"
AMBIGUOUS = "ambiguous"
FARM_CONFLICT = "farm_conflict"


def section_name_for(cost_centre, abbr):
	"""Drop the company abbreviation ERPNext appends to a cost-centre name."""
	suffix = f" - {abbr}"
	if abbr and cost_centre.endswith(suffix):
		return cost_centre[: -len(suffix)]
	return cost_centre


def unique_cost_centre(names):
	"""The single cost centre among candidates that share one cost_center_name,
	or None when there isn't exactly one.

	ERPNext appends the company abbreviation to a Cost Center's `name` but not
	to `cost_center_name`, so two companies can share one. Guessing which
	company a block belongs to would risk binding it to the wrong parent, the
	wrong farm, and the wrong section -- so more than one match refuses rather
	than guesses, the same as no match at all.
	"""
	return names[0] if len(names) == 1 else None


def farm_mismatch(section_farm, block_farm):
	"""True when reusing an existing section would move a block onto a farm
	other than the one that section already carries.

	Two companies' cost-centre trees can strip to the same section name; if
	the existing section's farm differs from the block's own, appending would
	silently merge part of one farm's total into another's section.
	"""
	return section_farm != block_farm


def cost_centre_lookup(block):
	"""(cost centre docname or None, whether the lookup was ambiguous) for a
	block name.

	Tried first by docname, which is unique by construction; falls back to
	cost_center_name, which is not.
	"""
	cc = frappe.db.exists("Cost Center", block)
	if cc:
		return cc, False
	matches = frappe.get_all("Cost Center", filters={"cost_center_name": block}, pluck="name")
	return unique_cost_centre(matches), len(matches) > 1


def _parent_of(cc):
	"""The group cost centre above `cc`, if any."""
	parent = frappe.db.get_value("Cost Center", cc, "parent_cost_center")
	if not parent or not frappe.db.get_value("Cost Center", parent, "is_group"):
		return None
	return parent


def parent_cost_centre(block):
	"""The group cost centre above this block's own, if the block maps to one
	unambiguously."""
	cc, _ = cost_centre_lookup(block)
	return _parent_of(cc) if cc else None


def summary_message(created, placed, ambiguous, farm_conflict):
	"""The line printed once seeding finishes, naming both skip reasons
	separately so migrate output can tell "no grouping existed" apart from
	"the grouping was ambiguous and this refused to guess"."""
	return (
		f"Work Management: seeded {created} section(s) holding {placed} block(s) from the ledger "
		f"({ambiguous} skipped for an ambiguous cost-centre name, "
		f"{farm_conflict} skipped for a farm mismatch with an existing section)"
	)


def tally(blocks, place):
	"""Place every block, count what each one did, and survive the ones that raise.

	`place` returns one outcome per block, or None where the ledger says
	nothing about it. It is passed in rather than called directly so the
	counting can be tested without a site.

	A block is somebody else's record: a Warehouse renamed since the plan was
	raised, a Cost Center whose company was deleted, a section name too long
	for the field. Any of those raises, and raising used to abort `bench
	migrate` for the whole site -- over a head start that is explicitly
	optional and that the next migrate would pick up anyway. So a block that
	cannot be placed is named and skipped, and the other eighty-two still get
	their section.

	Returns (counts by outcome, notes for the blocks that raised).
	"""
	counts = {CREATED: 0, PLACED: 0, AMBIGUOUS: 0, FARM_CONFLICT: 0}

	def work(block):
		outcome = place(block)
		if outcome == CREATED:
			counts[CREATED] = counts[CREATED] + 1
			counts[PLACED] = counts[PLACED] + 1
		elif outcome in counts:
			counts[outcome] = counts[outcome] + 1

	_done, notes = migrating.each_without_aborting(blocks, work, "seed a section from")
	return counts, notes


def place(block):
	"""Put one block in the section its cost centre implies, and say what happened."""
	if sections.claimed_by(block):
		return None
	cc, is_ambiguous = cost_centre_lookup(block)
	if is_ambiguous:
		return AMBIGUOUS
	parent = _parent_of(cc) if cc else None
	if not parent:
		return None
	farm = frappe.db.get_value("Warehouse", block, "custom_farm")
	if not farm or not frappe.db.exists("Work Management Farm", farm):
		return None
	abbr = frappe.db.get_value("Company", frappe.db.get_value("Cost Center", parent, "company"), "abbr")
	name = section_name_for(parent, abbr)

	# One document write per block, either way. Inserting the section and then
	# saving its block was two: the section landed first, so a block the Link
	# validation refused left a section behind with nothing in it -- committed
	# by the run's own commit, and counted as neither created nor placed, so
	# migrate reported "seeded 0 section(s)" on a site that had just gained a
	# blank one. Building the section with its block attached validates both
	# before either is written.
	if frappe.db.exists("Work Management Section", name):
		doc = frappe.get_doc("Work Management Section", name)
		if farm_mismatch(doc.farm, farm):
			return FARM_CONFLICT
		doc.append("blocks", {"block": block})
		doc.flags.ignore_permissions = True
		doc.save()
		return PLACED

	frappe.get_doc({
		"doctype": "Work Management Section", "section_name": name, "farm": farm,
		"blocks": [{"block": block}],
	}).insert(ignore_permissions=True)
	return CREATED


def execute():
	for doctype in ("Work Management Section", "Cost Center", "Work Management Farm"):
		if not frappe.db.exists("DocType", doctype):
			return

	blocks = [row[0] for row in frappe.db.sql(PLANNER_BLOCKS_SQL)]
	counts, notes = tally(blocks, place)

	frappe.db.commit()
	print(summary_message(
		created=counts[CREATED], placed=counts[PLACED],
		ambiguous=counts[AMBIGUOUS], farm_conflict=counts[FARM_CONFLICT],
	))
	if notes:
		print(
			f"Work Management: {len(notes)} block(s) left for someone to place by hand, "
			"named above and in the Error Log"
		)
