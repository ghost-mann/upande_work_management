"""Who may do what, named -- so it can be configured instead of compiled in.

The approval chain became configurable and everything else did not. Four lists
and a scatter of inline checks still carried one company's org chart:

    MP_EDIT_ROLES = ["Farm Manager", "HOD HR", "General Manager", "System Manager"]
    RATE_ROLES    = ["General Manager", "HOD HR", "System Manager"]
    SEND_ROLES    = ["HOD HR", "Accounts Manager", "Accounts User", ...]
    is_clerk      = HR User or HR Manager or HR Clerk or HOD HR
    is_accounts   = Accounts Manager or Accounts User

A farm could say who approves a plan and not who may change a rate.

Each of those is one question with a name -- "who may set rates?" -- and a
question with a name can be a row in Settings. Five of them, each pointing at any
number of roles, seeded the way the approval steps are.

Everything defaults to `System Manager` alone, deliberately, and for the same
reason the approval chain does: it is the only role Frappe guarantees, so a fresh
install invents no job title and hands nothing to anybody by accident. Each site
then points each capability at its own roles.

Two neighbours are deliberately NOT capabilities:

  MP_GM_ROLES     duplicated the approval chain's own `masterplan_gm` role. Two
                  places answering "who is the GM here" is the failure this
                  codebase keeps hitting, so it is deleted, not renamed.
  the farm-scope  `fmbypass` and `AP_BYPASS` answer "may this person act outside
  bypasses        their farm". That is the farm dimension, not a capability, and
                  it already has a designed replacement in the User Permission
                  work -- see the RBAC spec. Making them capabilities would
                  enshrine a mechanism we intend to remove.
"""

from collections import namedtuple

import frappe

Capability = namedtuple("Capability", "key label description roles")


def _cap(key, label, description, roles=None):
	return Capability(key, label, description, list(roles or ["System Manager"]))


# The default a fresh install starts with. Labels are questions about the work,
# never job titles: naming a title here would put the thing being removed back
# into the configuration screen.
CATALOGUE = [
	_cap("edit_master_plan", "Create and edit a master plan",
		"Raise a budget for a farm and change it before it is submitted. "
		"Approving one is a separate thing, set by the approval steps."),
	_cap("set_rates", "Set task rates",
		"Change what an activity pays. A rate is frozen onto a plan when it is "
		"raised, so this decides future work, not work already planned."),
	_cap("send_payment", "Send a payment run",
		"Hand a completed payment run on to be paid. Marking it paid is the "
		"Payment approval step, not this."),
	_cap("enter_work", "Enter work",
		"Record assignments and actuals -- the day-to-day data entry the screens "
		"are built around. It grants no approval of any kind."),
	_cap("handle_payments", "Work with payments",
		"See and act on the payment screens at all. Without it the screen is "
		"read-only, whoever may eventually send or approve a run."),
]

BY_KEY = {cap.key: cap for cap in CATALOGUE}
BY_LABEL = {cap.label: cap for cap in CATALOGUE}

# The bypass every gate in this app allows, and the only one. Somebody has to be
# able to configure a site that is not yet configured.
ALWAYS = "System Manager"


def by_key(key):
	return BY_KEY.get(key)


def _rows(settings):
	rows = (settings.get("capabilities") if settings else None) or []
	return sorted(rows, key=lambda r: (r.get("idx") or 0))


def roles_for(key, settings=None):
	"""The roles a capability is granted to, in the grid's own order.

	Falls back to the shipped default when nothing is configured -- a site
	mid-install, or a grid somebody emptied. Answering "nobody" there would lock
	the screen with no way back in.

	An unknown key grants nothing at all: not the default and not everybody. A key
	the code does not recognise is a typo or a deleted feature, and a gate that
	opens on a typo is a hole.
	"""
	cap = BY_KEY.get(key)
	if not cap:
		return []
	label = cap.label
	roles = []
	for row in _rows(settings):
		named = row.get("capability")
		if named not in (key, label):
			continue
		role = (row.get("role") or "").strip()
		if role:
			roles.append(role)
	return roles or list(cap.roles)


def may(key, user_roles, config=None):
	"""May somebody holding `user_roles` do this?

	`config` is {key: [roles]} as `get_config()` hands it to the screens, so the
	same rule serves the app and the Server Scripts without either reading
	Settings twice.
	"""
	held = set(user_roles or [])
	if ALWAYS in held:
		return True
	if not held:
		return False
	granted = (config or {}).get(key) or []
	return any(role in held for role in granted)


def configured(settings=None):
	"""{key: [roles]} for every capability. What travels to the screens."""
	settings = settings if settings is not None else _settings_or_none()
	return {cap.key: roles_for(cap.key, settings) for cap in CATALOGUE}


def seeded_rows(existing):
	"""Settings' capability rows: one per capability, keeping what is there.

	Seeded rather than left empty so the grid is discoverable -- an empty table
	tells a reader nothing about what can be granted. Rows somebody added are
	kept in place, including extra roles for one capability and rows naming a
	capability this code no longer has: the approval stages learned that the hard
	way, rebuilding themselves from the catalogue and throwing away what somebody
	had configured.
	"""
	rows = []
	seen = set()
	for row in existing or []:
		named = (row.get("capability") or "").strip()
		if not named:
			continue
		cap = BY_LABEL.get(named) or BY_KEY.get(named)
		rows.append({
			"capability": cap.label if cap else named,
			"role": row.get("role"),
		})
		if cap:
			seen.add(cap.key)

	for cap in CATALOGUE:
		if cap.key not in seen:
			rows.append({"capability": cap.label, "role": cap.roles[0]})

	# catalogue order first, then anything added, so the grid reads as the
	# shipped list plus this site's own additions
	order = {cap.label: i for i, cap in enumerate(CATALOGUE)}
	return sorted(rows, key=lambda r: order.get(r["capability"], len(order)))


def _settings_or_none():
	try:
		return frappe.get_cached_doc("Work Management Settings")
	except Exception:
		return None


def seed(settings=None, save=True):
	"""Write the seeded rows onto Settings. Idempotent; runs on migrate."""
	settings = settings or frappe.get_doc("Work Management Settings")
	rows = seeded_rows(settings.get("capabilities") or [])
	before = [(r.get("capability"), r.get("role"))
		for r in (settings.get("capabilities") or [])]
	after = [(r["capability"], r["role"]) for r in rows]
	if before == after:
		return 0

	settings.set("capabilities", [])
	for row in rows:
		settings.append("capabilities", row)
	if save:
		settings.flags.ignore_permissions = True
		settings.flags.skip_approval_sync = True
		settings.save()
	return len(rows)


def labels():
	return [cap.label for cap in CATALOGUE]
