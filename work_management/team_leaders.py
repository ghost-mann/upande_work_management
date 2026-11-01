"""Team leaders: who runs an activity on a given day, and the KPI arithmetic.

The master plan names a team leader per activity. A dated stand-in on the same
plan takes the activity over for those days, and the work done then counts to
the stand-in -- whoever ran the work answers for it.

The server scripts cannot define functions (RestrictedPython, no `def`), so
wm_planner / wm_masterplan / wm_dashboard inline this logic. Keep them in step;
this file is the unit-tested statement of the rules.
"""

QUALITY_SCORES = ("1 - Good", "2 - Fair", "3 - Rework")


def resolve_leader(owner, on_date, stand_ins):
	"""The person running `owner`'s activity on `on_date`.

	stand_ins: iterable of dicts with team_leader, stand_in, from_date, to_date
	(dates as ISO strings or date objects). The latest-starting stand-in that
	covers the date wins, so a short cover inside a longer one takes over.
	"""
	if not owner:
		return None
	day = str(on_date)
	pick = None
	for s in stand_ins or []:
		if s.get("team_leader") != owner or not s.get("stand_in"):
			continue
		if str(s.get("from_date")) <= day <= str(s.get("to_date")):
			if pick is None or str(s.get("from_date")) >= str(pick.get("from_date")):
				pick = s
	return pick.get("stand_in") if pick else owner


def stand_in_errors(rows, leaders):
	"""Problems with a set of stand-in rows, as sentences. Empty means fine.

	leaders: the team leaders named on the plan's activities.
	"""
	errs = []
	for i, s in enumerate(rows or [], start=1):
		tl, si = s.get("team_leader"), s.get("stand_in")
		fd, td = s.get("from_date"), s.get("to_date")
		if not (tl and si and fd and td):
			errs.append("Stand-in row %d needs a team leader, a stand-in and both dates." % i)
		elif tl == si:
			errs.append("Stand-in row %d: %s cannot stand in for themselves." % (i, tl))
		elif str(td) < str(fd):
			errs.append("Stand-in row %d: the To date is before the From date." % i)
		elif tl not in leaders:
			errs.append("Stand-in row %d: %s leads no activity on this plan." % (i, tl))
	return errs


def pct(part, whole):
	"""part / whole as a percentage, or None when there is nothing to divide by."""
	whole = float(whole or 0)
	if whole <= 0:
		return None
	return round(float(part or 0) / whole * 100, 1)


def weekly_kpis(planned_md, earned_md, actual_md, planned_cost, earned_cost, actual_cost):
	"""Delivery against the weekly plans, summed over many activities.

	A team leader's activities are measured in different units (hectares,
	crates, hours), so quantities cannot be added up. Everything is first put
	into man-days: a week's earned man-days are its actual quantity at the
	planned daily target.

	completion  -- earned man-days / planned man-days (one activity: actual
	               quantity / planned quantity)
	efficiency  -- earned man-days / man-days actually worked. Comparing planned
	               with worked man-days directly would reward doing half the
	               work with half the people.
	cost_eff    -- the planned cost of the work done / what it actually cost
	"""
	return {
		"completion": pct(earned_md, planned_md),
		"efficiency": pct(earned_md, actual_md),
		"cost_efficiency": pct(earned_cost, actual_cost),
	}


def master_plan_kpis(target_qty, target_md, rate, done_qty, actual_md, actual_cost):
	"""Progress against one master plan activity, and what is left of it.

	Summed over activities, progress is weighted by budget cost (done cost /
	budget cost): man-days are optional on a master plan, cost never is.
	"""
	target_qty = float(target_qty or 0)
	done_qty = float(done_qty or 0)
	left = max(target_qty - done_qty, 0.0)
	md_per_unit = (float(target_md or 0) / target_qty) if target_qty else 0
	return {
		"progress": pct(done_qty, target_qty),
		"efficiency": pct(done_qty * md_per_unit, actual_md),
		"cost_efficiency": pct(done_qty * float(rate or 0), actual_cost),
		"backlog_qty": round(left, 2),
		"backlog_md": round(left * md_per_unit, 2),
		"backlog_cost": round(left * float(rate or 0), 2),
	}


def quality_split(scores):
	"""Share of Good / Fair / Rework among the scored actuals, in percent."""
	n = {"good": 0, "fair": 0, "rework": 0}
	for s in scores or []:
		k = str(s or "")[:1]
		if k == "1":
			n["good"] += 1
		elif k == "2":
			n["fair"] += 1
		elif k == "3":
			n["rework"] += 1
	total = n["good"] + n["fair"] + n["rework"]
	return {
		"scored": total,
		"good": pct(n["good"], total),
		"fair": pct(n["fair"], total),
		"rework": pct(n["rework"], total),
	}
