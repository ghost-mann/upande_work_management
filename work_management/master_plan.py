# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Cap arithmetic for the Work Management Master Plan.

A master plan line budgets an activity twice over: a quantity of work and the
money it may cost. A weekly plan is refused when either ceiling would be
crossed -- whichever is hit first -- because a rate change can blow the budget
without the quantity moving at all.

Mirrored inline in server_scripts/wm_masterplan.py and wm_planner.py: Frappe's
script sandbox forbids imports, so the two must be kept in step.
"""

import re

#: Money and quantity comparisons tolerate this much, matching wm_payment.
TOLERANCE = 0.005


def line_headroom(work_qty, cost, planned_qty, planned_cost):
	"""What is left on one master plan line."""
	work_qty = float(work_qty or 0)
	cost = float(cost or 0)
	planned_qty = float(planned_qty or 0)
	planned_cost = float(planned_cost or 0)

	remaining_qty = max(0.0, work_qty - planned_qty)
	remaining_cost = max(0.0, cost - planned_cost)
	return {
		"remaining_qty": remaining_qty,
		"remaining_cost": remaining_cost,
		"qty_pct": (planned_qty / work_qty * 100) if work_qty else 100.0,
		"cost_pct": (planned_cost / cost * 100) if cost else 100.0,
		# a line with no budget at all is exhausted, not infinitely available
		"exhausted": remaining_qty <= TOLERANCE or remaining_cost <= TOLERANCE,
	}


def _candidate(c):
	"""A candidate as {name, greenhouse}. A bare name is a farm-level plan, which
	is the shape every caller had before plans could name a greenhouse."""
	if isinstance(c, dict):
		return {"name": c.get("name"), "greenhouse": c.get("greenhouse") or ""}
	return {"name": c, "greenhouse": ""}


def plan_fits_blocks(greenhouse, block_ancestors):
	"""May a plan for `greenhouse` fund work on these blocks? Pure.

	A farm-level plan (no greenhouse) funds anything on its farm. A greenhouse
	plan funds a request only when EVERY block it names sits in that greenhouse
	-- is the greenhouse, or under it in the Warehouse tree. `block_ancestors`
	is {block: the set of warehouses it sits in, itself included}; None means
	the blocks are not known yet (the screen asks before any is picked), and
	nothing is filtered out on a guess.
	"""
	if not greenhouse or not block_ancestors:
		return True
	for ancestors in block_ancestors.values():
		if greenhouse not in (ancestors or ()):
			return False
	return True


def pick_master_plan(stored, candidates, block_ancestors=None):
	"""Which master plan a request draws against, with why. Pure.

	`candidates` are the approved plans on the request's farm whose period
	contains its dates. Returns {name, reason, kind, tied}; `kind` is one of
	picked / stored_missing / stored_elsewhere / tied / span / none.

	THE RULE, in order:

	1. The link the request carries wins, if that plan may fund these blocks.
	2. Of the plans that may fund them, a greenhouse plan beats a farm-level one:
	   the greenhouse budget is the narrower, deliberate answer, and the farm
	   plan is what covers work no greenhouse plan does.
	3. Two plans at the same level is refused rather than guessed -- guessing
	   which budget work came from is the error this exists to prevent -- and
	   both names are in the message.
	4. Nothing fits: when the blocks sit in different greenhouses and no
	   farm-level plan covers them, the message names the greenhouses, because
	   the fix is one request per greenhouse.
	"""
	cands = [_candidate(c) for c in (candidates or []) if c]
	cands = [c for c in cands if c["name"]]
	fits = [c for c in cands if plan_fits_blocks(c["greenhouse"], block_ancestors)]
	fit_names = [c["name"] for c in fits]
	out = {"name": None, "reason": None, "kind": None, "tied": []}

	if stored:
		if stored in fit_names:
			out.update(name=stored, kind="picked")
			return out
		named = [c for c in cands if c["name"] == stored]
		if named:
			out.update(kind="stored_elsewhere", reason=(
				f"{stored} budgets {named[0]['greenhouse']}, and this request's "
				+ ", ".join(sorted(block_ancestors or {}))
				+ " are not in it. Choose a master plan for their greenhouse, or a "
				"farm-level one."))
			return out
		out.update(kind="stored_missing", reason=(
			f"{stored} does not cover this request's farm and dates. "
			"Choose a master plan whose period contains them."))
		return out

	for level in ([c for c in fits if c["greenhouse"]], [c for c in fits if not c["greenhouse"]]):
		if len(level) == 1:
			out.update(name=level[0]["name"], kind="picked")
			return out
		if len(level) > 1:
			tied = sorted(c["name"] for c in level)
			out.update(kind="tied", tied=tied, reason=(
				"More than one approved master plan covers these dates: "
				+ ", ".join(tied)
				+ ". Say which one this work is planned against."))
			return out

	houses = blocks_greenhouses(cands, block_ancestors)
	if len(set(houses.values())) > 1:
		out.update(kind="span", reason=(
			"This request's blocks are in different greenhouses ("
			+ ", ".join(sorted(set(houses.values())))
			+ ") and no farm-level master plan covers these dates. Raise one "
			"request per greenhouse."))
		return out
	out.update(kind="none", reason=(
		"No approved master plan covers these dates for this farm. "
		"A master plan must be approved before work can be planned."))
	return out


def blocks_greenhouses(candidates, block_ancestors):
	"""{block: the greenhouse it is budgeted under}. Pure. A block no candidate
	greenhouse plan contains stands for itself -- on a farm whose greenhouses
	are leaf warehouses, the block IS the greenhouse."""
	houses = {}
	ghs = [c["greenhouse"] for c in (_candidate(x) for x in (candidates or [])) if c["greenhouse"]]
	for block, ancestors in (block_ancestors or {}).items():
		hit = [g for g in ghs if g in (ancestors or ())]
		houses[block] = sorted(hit)[0] if hit else block
	return houses


def resolve_master_plan(stored, candidates, block_ancestors=None):
	"""``(name, reason)`` -- pick_master_plan() for callers that only need those.

	`candidates` may be bare names (farm-level plans) or {name, greenhouse}.
	"""
	picked = pick_master_plan(stored, candidates, block_ancestors)
	return picked["name"], picked["reason"]


# ------------------------------------------------------------------- naming

#: The counter in a name format: a run of #, as in {###}.
_COUNTER = re.compile(r"\{(#+)\}")
_TOKEN = re.compile(r"\{([A-Za-z_]+)\}")
#: What Settings > Naming > Document names may put in a master plan's name.
NAME_TOKENS = ("greenhouse", "farm", "YY", "YYYY")


def name_part(value, company_abbr=None):
	"""A link value made fit for the middle of a document name. Pure.

	`GH-3 - KFL` -> `GH-3`: the company suffix ERPNext puts on every warehouse
	says nothing a farm's own plan names need, and spaces, slashes and the like
	are folded to single hyphens so the name works in a URL and a filename.
	"""
	v = (value or "").strip()
	if company_abbr and v.endswith(" - " + company_abbr):
		v = v[: -len(" - " + company_abbr)]
	elif not company_abbr:
		v = re.sub(r"\s+-\s+[A-Za-z0-9]+$", "", v)
	v = re.sub(r"[^A-Za-z0-9_-]+", "-", v)
	v = re.sub(r"-{2,}", "-", v).strip("-")
	return v


def expand_name_format(fmt, values):
	"""``(prefix, digits, suffix)`` for a name format. Pure.

	`{greenhouse}-MP-{YY}-{###}` with GH-3 in 2026 -> ("GH-3-MP-26-", 3, "").
	The counter is Frappe's series keyed on the prefix, so it runs separately
	for every greenhouse and every year without anything keeping count of
	either. A format with no counter gets five digits on the end; a placeholder
	nobody defined is refused rather than left in the name.
	"""
	fmt = (fmt or "").strip()
	m = _COUNTER.search(fmt)
	if m:
		head, digits, tail = fmt[: m.start()], len(m.group(1)), fmt[m.end():]
	else:
		head, digits, tail = fmt, 5, ""

	def fill(part):
		def one(t):
			key = t.group(1)
			if key not in NAME_TOKENS:
				raise ValueError("Unknown placeholder {%s} in the master plan name format. "
					"Use %s." % (key, ", ".join("{%s}" % k for k in NAME_TOKENS)))
			v = values.get(key) or ""
			if not v:
				raise ValueError("The master plan name format needs {%s}, and this plan "
					"has none." % key)
			return v
		return _TOKEN.sub(one, part)

	return fill(head), digits, fill(tail)


def name_format_needs_greenhouse(fmt):
	return "{greenhouse}" in (fmt or "")


def master_plan_name_format():
	"""Settings > Naming > Document names, or "" for the doctype's WMMP-#####."""
	import frappe

	return (frappe.db.get_single_value("Work Management Settings", "mp_name_format") or "").strip()


def master_plan_name(doc):
	"""The name a NEW master plan gets under the configured format, or None to
	leave it to the doctype's own naming series. Never called for a plan that
	already has a name: existing plans keep theirs."""
	import frappe
	from frappe.model.naming import getseries

	fmt = master_plan_name_format()
	if not fmt:
		return None
	# A plan with no greenhouse is a farm-level plan -- the one that covers the
	# blocks no greenhouse plan does. A format built on the greenhouse has nothing
	# to name it by, so it keeps the doctype's WMMP-#####.
	if name_format_needs_greenhouse(fmt) and not doc.get("greenhouse"):
		return None
	gh = doc.get("greenhouse") or ""
	abbr = None
	if gh:
		gh_company = frappe.db.get_value("Warehouse", gh, "company")
		if gh_company:
			abbr = frappe.get_cached_value("Company", gh_company, "abbr")
	year = str(doc.get("period_from") or frappe.utils.today())[:4]
	values = {"greenhouse": name_part(gh, abbr), "farm": name_part(doc.get("farm"), ""),
		"YYYY": year, "YY": year[2:]}
	try:
		prefix, digits, suffix = expand_name_format(fmt, values)
	except ValueError as e:
		frappe.throw(str(e), title=frappe._("Master plan name format"))
	key = prefix + ("#" + suffix if suffix else "")
	while True:
		name = prefix + getseries(key, digits) + suffix
		# a name typed by hand, or a counter reset, must not collide
		if not frappe.db.exists("Work Management Master Plan", name):
			return name


# ------------------------------------------------------------- site lookups
# Everything above is pure; these read the site and hand the answers to it.


def approved_candidates(farm, from_date, to_date):
	"""Approved plans on `farm` whose period contains the dates, latest first."""
	import frappe

	return frappe.db.sql(
		"""
		SELECT name, greenhouse, plan_name, period_from, period_to
		FROM `tabWork Management Master Plan`
		WHERE farm = %(f)s AND workflow_state = 'Approved'
		  AND period_from <= %(a)s AND period_to >= %(b)s
		ORDER BY period_from DESC
		""",
		{"f": farm, "a": from_date, "b": to_date},
		as_dict=True,
	)


def block_ancestors(blocks):
	"""{block: every warehouse it sits in, itself included} from the tree."""
	import frappe

	out = {}
	for block in blocks or []:
		if not block or block in out:
			continue
		lr = frappe.db.get_value("Warehouse", block, ["lft", "rgt"])
		ancestors = {block}
		if lr and lr[0] is not None:
			ancestors.update(frappe.db.sql_list(
				"SELECT name FROM `tabWarehouse` WHERE lft <= %s AND rgt >= %s",
				(lr[0], lr[1])))
		out[block] = ancestors
	return out


def planner_blocks(name):
	"""The blocks a saved request names: its primary block and any extras."""
	import frappe

	blocks = []
	primary = frappe.db.get_value("Work Management Planner", name, "block_section")
	if primary:
		blocks.append(primary)
	for b in frappe.get_all("Work Planner Block", filters={
			"parent": name, "parenttype": "Work Management Planner"},
			pluck="block", order_by="idx"):
		if b and b not in blocks:
			blocks.append(b)
	return blocks


def resolve_for_request(farm, from_date, to_date, blocks, stored=""):
	"""pick_master_plan() against the site, plus the picked plan's row."""
	rows = approved_candidates(farm, from_date, to_date)
	picked = pick_master_plan(stored, rows, block_ancestors(blocks) if blocks else None)
	picked["row"] = None
	for r in rows:
		if r.name == picked["name"]:
			picked["row"] = r
	picked["candidates"] = rows
	return picked


# ------------------------------------------------------- drawdown attribution

#: The four bind parameters every drawdown query below expects: the plan being
#: charged, its farm, and its period. Named rather than positional because these
#: strings are pasted into queries that already carry parameters of their own.
DRAWDOWN_PARAMS = ("plan", "f", "pfrom", "pto")


#: The greenhouse of the plan being charged, as SQL. Empty for a farm-level plan.
_ME_GH = ("IFNULL((SELECT me.greenhouse FROM `tabWork Management Master Plan` me"
	" WHERE me.name = %(plan)s),'')")


def _fits_sql(gh, a):
	"""SQL: may a plan whose greenhouse is `gh` fund request row `a`?

	plan_fits_blocks() as a predicate. Farm-level always fits; a greenhouse fits
	when the row's block and every extra block sit inside it in the Warehouse
	tree (nested sets: a child's lft/rgt lie within its ancestor's). `{{` and
	`}}` because the result is .format()ted with the alias.
	"""
	return (
		"(IFNULL(" + gh + ",'') = ''"
		" OR (EXISTS (SELECT 1 FROM `tabWarehouse` gw, `tabWarehouse` bw"
		" WHERE gw.name = " + gh + " AND bw.name = " + a + ".block_section"
		" AND bw.lft >= gw.lft AND bw.rgt <= gw.rgt)"
		" AND NOT EXISTS (SELECT 1 FROM `tabWork Planner Block` xb, `tabWarehouse` xw,"
		" `tabWarehouse` gx"
		" WHERE xb.parent = " + a + ".name AND xb.parenttype = 'Work Management Planner'"
		" AND xw.name = xb.block AND gx.name = " + gh +
		" AND NOT (xw.lft >= gx.lft AND xw.rgt <= gx.rgt))))"
	)


def _others_sql(a, greenhouse_level):
	"""SQL: how many OTHER approved plans at one level could fund row `a`."""
	level = "IFNULL(o.greenhouse,'') != ''" if greenhouse_level else "IFNULL(o.greenhouse,'') = ''"
	return (
		"(SELECT COUNT(*) FROM `tabWork Management Master Plan` o"
		" WHERE o.farm = %(f)s AND o.name != %(plan)s"
		" AND o.workflow_state = 'Approved'"
		" AND o.period_from <= " + a + ".from_date AND o.period_to >= " + a + ".to_date"
		" AND " + level + " AND " + _fits_sql("o.greenhouse", a) + ")"
	)


def attributed_to_plan(alias="p"):
	"""SQL: the planner rows THIS master plan is charged for. Pure.

	Two approved plans over one period used to be charged each other's requests.
	Every drawdown query matched on dates alone -- `from_date >= period_from AND
	to_date <= period_to` -- which is exact while a farm holds one budget per
	period and wrong the moment it holds two: a request for 6 and a request for 9
	both landed on both plans, and each plan read 15 planned. The stored link was
	written and read for *which* plan, and never for *how much of it is spent*.

	So the link decides. A request naming a plan is charged to that plan and to no
	other, whatever its dates say -- the link is what the requester chose, and the
	dates cannot overrule it.

	A row with no link is the shape of every request raised before the field
	existed, and dates are all it has. Containment still attributes it, but only
	when exactly one approved plan contains it. Where two do, it is charged to
	NEITHER: charging it to both is precisely the bug being removed here, and
	picking one would be the guess that resolve_master_plan() refuses to make on
	the way in. Those rows are real money and do not vanish -- see
	unattributed_to_plan().

	`alias` is the alias the caller gave `tabWork Management Planner`; the
	correlated subquery needs to reach the row's own dates, so the table cannot be
	left unaliased. The caller still supplies its own farm and workflow_state
	filters -- this is the attribution rule, not the whole WHERE clause.

	GREENHOUSES. A row with no link goes to the plan pick_master_plan() would
	pick: only plans that may fund its blocks count, a greenhouse plan beats a
	farm-level one, and two at the winning level charge NEITHER. So a
	greenhouse plan takes the row when no other greenhouse plan fits it; a
	farm-level plan takes it only when nothing else fits it at all.
	"""
	return (
		"({a}.master_plan = %(plan)s\n"
		"     OR (IFNULL({a}.master_plan,'') = ''\n"
		"         AND {a}.from_date >= %(pfrom)s AND {a}.to_date <= %(pto)s\n"
		"         AND " + _fits_sql(_ME_GH, "{a}") + "\n"
		"         AND " + _others_sql("{a}", True) + " = 0\n"
		"         AND (" + _ME_GH + " != '' OR " + _others_sql("{a}", False) + " = 0)))"
	).format(a=alias)


def unattributed_to_plan(alias="p"):
	"""SQL: the rows inside this plan's period that nothing may be charged for.

	The remainder attributed_to_plan() drops: no link, contained by this plan, and
	contained by at least one other approved plan too. Reported per plan as
	`unattributed_qty` / `unattributed_cost` and NEVER folded into planned_qty --
	adding it back to both plans would restore the double-charge this exists to
	prevent, and adding it to one would be the guess.

	It is reported because it is real committed work whose budget nobody can name.
	Silently dropping it would leave a plan looking healthier than it is, with no
	trace of the money. A non-zero figure here means somebody should set the
	`master_plan` link on those requests; then it moves into planned_qty, on the
	plan a human chose.

	With greenhouses: the rows this plan could fund whose winning level is tied
	-- two greenhouse plans fit, or no greenhouse plan and two farm-level ones.
	A row one greenhouse plan takes is that plan's, not anybody's remainder.
	"""
	return (
		"(IFNULL({a}.master_plan,'') = ''\n"
		"     AND {a}.from_date >= %(pfrom)s AND {a}.to_date <= %(pto)s\n"
		"     AND " + _fits_sql(_ME_GH, "{a}") + "\n"
		"     AND ((" + _ME_GH + " != '' AND " + _others_sql("{a}", True) + " >= 1)\n"
		"       OR (" + _ME_GH + " = '' AND (" + _others_sql("{a}", True) + " >= 2\n"
		"           OR (" + _others_sql("{a}", True) + " = 0 AND "
		+ _others_sql("{a}", False) + " >= 1)))))"
	).format(a=alias)


def check_plan_allowed(work_qty, cost, planned_qty, planned_cost, new_qty, new_cost):
	"""May a plan for ``new_qty`` / ``new_cost`` be raised against this line?

	Returns ``(allowed, reason)``. The reason names the ceiling, what is
	already committed and what is left -- a bare refusal is useless to whoever
	hit it.
	"""
	h = line_headroom(work_qty, cost, planned_qty, planned_cost)
	new_qty = float(new_qty or 0)
	new_cost = float(new_cost or 0)

	if new_qty > h["remaining_qty"] + TOLERANCE:
		return False, (
			"Over the budgeted quantity: {0:,.2f} left of {1:,.2f}, "
			"this plan asks for {2:,.2f}.".format(h["remaining_qty"], float(work_qty or 0), new_qty)
		)
	if new_cost > h["remaining_cost"] + TOLERANCE:
		return False, (
			"Over the budgeted cost: KES {0:,.2f} left of {1:,.2f}, "
			"this plan costs {2:,.2f}.".format(h["remaining_cost"], float(cost or 0), new_cost)
		)
	return True, None


def check_cut_allowed(new_qty, new_cost, planned_qty, planned_cost, task=None):
	"""May an approved line be moved down to ``new_qty`` / ``new_cost``?

	An approved line is not a number on a form, it is budget the weekly planner
	has already been spending against. Raising it is always safe. Lowering it
	below what is already committed is not: the planner would start refusing
	work that was legitimately planned, with an error pointing at a ceiling
	rather than at the edit that moved it.

	Removing a line entirely is a cut to zero and goes through here too.

	Returns ``(allowed, reason)``. The reason names the task and both figures,
	because "you cannot do that" tells whoever hit it nothing about what to do
	next.
	"""
	new_qty = float(new_qty or 0)
	new_cost = float(new_cost or 0)
	planned_qty = float(planned_qty or 0)
	planned_cost = float(planned_cost or 0)
	what = str(task) if task else "This activity"

	if new_qty < planned_qty - TOLERANCE:
		return False, (
			"{0} is already planned at {1:,.2f} and cannot be cut to {2:,.2f}.".format(
				what, planned_qty, new_qty
			)
		)
	if new_cost < planned_cost - TOLERANCE:
		return False, (
			"{0} already has KES {1:,.2f} planned against it and cannot be cut "
			"to KES {2:,.2f}.".format(what, planned_cost, new_cost)
		)
	return True, None
