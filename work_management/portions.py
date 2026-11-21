# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Activity portions: one master plan line split between team leaders.

A line keeps one overall team leader who answers for the whole activity. Under
it, the Farm Manager may split the line into portions -- a team leader, the
blocks they run, and their share of the line's quantity and money. A weekly
request raised on a split line belongs to one portion and is capped by it.

The rules here are the unit-tested statement. wm_masterplan (set_portions) and
wm_planner (save) inline them, because the Server Script sandbox has no def;
keep them in step.
"""

#: Money and quantity comparisons tolerate this much, matching master_plan.py.
TOLERANCE = 0.005


def _f(x):
	return float(x or 0)


def portion_cost(qty, rate):
	"""A portion's money: its quantity at the line's frozen rate, as the line does."""
	return round(_f(qty) * _f(rate), 2)


def portion_errors(line, portions, used=None, legacy=None, valid_leaders=None, leaders=None):
	"""Problems with a proposed split of one line, as sentences. Empty means fine.

	line: {task, label, work_qty, cost}
	portions: [{portion_key, team_leader, work_qty, cost, blocks: [...]}]
	used: {portion_key: {q, c}} -- what weekly requests already hold per portion
	legacy: {q, c} -- requests on this line raised before it was split (no portion)
	valid_leaders: who may be named, or None to skip the check
	leaders: {portion_key: team_leader} of the portions as they stand, so a portion
	         that would disappear can be named
	"""
	used = used or {}
	legacy = legacy or {}
	what = line.get("label") or line.get("task") or "This activity"
	errs = []
	if not portions:
		# unsplitting is allowed only when no request belongs to a portion
		for k, u in used.items():
			if _f(u.get("q")) > TOLERANCE or _f(u.get("c")) > TOLERANCE:
				errs.append("%s: %s's portion has requests against it and cannot be removed."
				            % (what, (leaders or {}).get(k) or k))
		return errs
	seen_block = {}
	keys = set()
	for i, p in enumerate(portions, start=1):
		tl = p.get("team_leader")
		key = p.get("portion_key")
		if key:
			keys.add(key)
		if not tl:
			errs.append("%s: portion %d needs a team leader." % (what, i))
			continue
		if valid_leaders is not None and tl not in valid_leaders:
			errs.append("%s: %s is not on the farm's active team leader list." % (what, tl))
		if _f(p.get("work_qty")) < 0 or _f(p.get("cost")) < 0:
			errs.append("%s: %s's portion cannot be negative." % (what, tl))
		if not p.get("blocks"):
			errs.append("%s: %s's portion needs at least one block." % (what, tl))
		for b in p.get("blocks") or []:
			if b in seen_block and seen_block[b] != i:
				errs.append("%s: block %s is in both %s's and %s's portions. A block belongs to one."
				            % (what, b, portions[seen_block[b] - 1].get("team_leader"), tl))
			seen_block.setdefault(b, i)
		u = used.get(key) if key else None
		if u:
			if _f(p.get("work_qty")) < _f(u.get("q")) - TOLERANCE:
				errs.append("%s: %s's portion already has %.2f planned and cannot be cut to %.2f."
				            % (what, tl, _f(u.get("q")), _f(p.get("work_qty"))))
			elif _f(p.get("cost")) < _f(u.get("c")) - TOLERANCE:
				errs.append("%s: %s's portion already has KES %.2f planned and cannot be cut to KES %.2f."
				            % (what, tl, _f(u.get("c")), _f(p.get("cost"))))
	for k, u in used.items():
		if k not in keys and (_f(u.get("q")) > TOLERANCE or _f(u.get("c")) > TOLERANCE):
			errs.append("%s: %s's portion has requests against it and cannot be removed."
			            % (what, (leaders or {}).get(k) or k))
	sq = sum(_f(p.get("work_qty")) for p in portions) + _f(legacy.get("q"))
	sc = sum(_f(p.get("cost")) for p in portions) + _f(legacy.get("c"))
	tail = " including %.2f in earlier requests made before the split" % _f(legacy.get("q")) \
		if _f(legacy.get("q")) > TOLERANCE else ""
	if sq > _f(line.get("work_qty")) + TOLERANCE:
		errs.append("%s: the portions come to %.2f%s, over the activity's %.2f."
		            % (what, sq, tail, _f(line.get("work_qty"))))
	# each portion's money is rounded on its own, so n portions may come to up
	# to n half-cents over the line's single rounded figure without being over
	if sc > _f(line.get("cost")) + TOLERANCE * (len(portions) + 1):
		ctail = " including KES %.2f in earlier requests made before the split" % _f(legacy.get("c")) \
			if _f(legacy.get("c")) > TOLERANCE else ""
		errs.append("%s: the portions come to KES %.2f%s, over the activity's KES %.2f."
		            % (what, sc, ctail, _f(line.get("cost"))))
	return errs


def portion_headroom(portion, used):
	"""What is left of one portion after the requests already raised against it."""
	used = used or {}
	rq = _f(portion.get("work_qty")) - _f(used.get("q"))
	rc = _f(portion.get("cost")) - _f(used.get("c"))
	return {"remaining_qty": rq, "remaining_cost": rc,
	        "exhausted": rq <= TOLERANCE or rc <= TOLERANCE}


def unallocated(line, portions, legacy=None):
	"""The part of a split line no portion holds (and no earlier request used)."""
	legacy = legacy or {}
	return {
		"qty": round(_f(line.get("work_qty")) - sum(_f(p.get("work_qty")) for p in portions) - _f(legacy.get("q")), 6),
		"cost": round(_f(line.get("cost")) - sum(_f(p.get("cost")) for p in portions) - _f(legacy.get("c")), 2),
	}


def _num(x):
	x = _f(x)
	return str(int(x)) if x == int(x) else ("%.2f" % x)


def portion_changes(old, new):
	"""What a save changed, for the log kept on an approved plan."""
	out = []
	was = {p.get("portion_key"): p for p in old or []}
	now = {p.get("portion_key"): p for p in new or []}
	for k, p in now.items():
		o = was.get(k)
		if not o:
			out.append({"kind": "added", "portion_key": k, "old_value": "",
			            "new_value": "%s %s %s" % (p.get("team_leader"), _num(p.get("work_qty")),
			                                       ",".join(sorted(p.get("blocks") or [])))})
			continue
		if o.get("team_leader") != p.get("team_leader"):
			out.append({"kind": "leader", "portion_key": k,
			            "old_value": o.get("team_leader") or "", "new_value": p.get("team_leader") or ""})
		if abs(_f(o.get("work_qty")) - _f(p.get("work_qty"))) > TOLERANCE:
			out.append({"kind": "budget", "portion_key": k,
			            "old_value": _num(o.get("work_qty")), "new_value": _num(p.get("work_qty"))})
		ob = sorted(o.get("blocks") or [])
		nb = sorted(p.get("blocks") or [])
		if ob != nb:
			out.append({"kind": "blocks", "portion_key": k, "old_value": ",".join(ob), "new_value": ",".join(nb)})
	for k, o in was.items():
		if k not in now:
			out.append({"kind": "removed", "portion_key": k,
			            "old_value": "%s %s" % (o.get("team_leader"), _num(o.get("work_qty"))), "new_value": ""})
	return out
