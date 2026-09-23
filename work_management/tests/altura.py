# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""A chain shaped like Altura's, for tests to verify against.

The last family of bugs passed seventeen hundred tests. Every one of them was
written against the chain this app ships with -- `Pending Farm Manager`,
`FM Approve`, a role called `Farm Manager` -- and on the shipped chain the faulty
code and the correct code give the same answer. That is the whole problem: a
guard that reads `"Farm Manager" in roles` is indistinguishable from one that
reads `chain.may_take(step, roles)` until somebody configures the chain.

So this is the other site. Nothing here is invented to be awkward: it is the
shape Altura actually runs.

    every step RELABELLED     `Assigner: Manager`, not `Assigner: Farm Manager`
    every state RENAMED       so no comparison against `Pending GM` can pass by
                              accident
    every action RENAMED      so none of the shipped `FM Approve` family appears
    three roles, none shipped  Production Manager, Production Section Head,
                              HR Officer -- the app ships none of them and
                              deliberately creates none
    five steps OFF            the consultant review, the planner's second
                              approval, the assigner's HR and GM steps and the
                              actuals GM step

The important consequence, and the reason these figures are worth stating: ONE
role, Production Manager, takes the last enabled step of all four chains. Philip
holds it. Every gate this app has ever written as "is this person a Farm Manager,
the HR head or the GM" answers *no* for him, and every gate written as "does the
chain name this person" answers *yes*.

`settings()` returns the plain dict `approvals.configured_stages()` reads, so a
test can drive the real chain code with no site at all -- which is how the rest
of this suite works. `chain_rows()` returns what `get_config()["stage_rows"]`
would hand the dispatchers.
"""

from work_management import approvals


class Row(dict):
	"""A Settings child row, as frappe hands one over: item AND attribute."""

	def __getattr__(self, name):
		try:
			return self[name]
		except KeyError:
			return None


class Settings(dict):
	"""The Settings doc, as far as approvals.py reads it."""

	def get(self, key, default=None):
		return dict.get(self, key, default)


#: The three roles. Named once so a test can say which person it means.
MANAGER = "Production Manager"
SECTION_HEAD = "Production Section Head"
HR_OFFICER = "HR Officer"

#: (key, label, state, action, role, enabled). Order is the chain's order, which
#: is the order Settings holds the rows in.
STEPS = [
	("masterplan_submit", "Budget: Raise", "Drafting", "Send for review", SECTION_HEAD, 1),
	("masterplan_consultant", "Budget: Review", "With the reviewer", "Send on", MANAGER, 0),
	("masterplan_gm", "Budget: Manager", "With the manager", "Sign off", MANAGER, 1),

	("planner_submit", "Plan: Raise", "Drafting", "Send for approval", SECTION_HEAD, 1),
	("planner_farm_approval", "Plan: Manager", "With the manager", "Sign off", MANAGER, 1),
	("planner_hr_approval", "Plan: People", "With people", "People sign off", HR_OFFICER, 0),

	("assigner_submit", "Crew: Raise", "Drafting", "Send for approval", SECTION_HEAD, 1),
	("assigner_farm_manager", "Assigner: Manager", "With the manager", "Sign off", MANAGER, 1),
	("assigner_hr_head", "Crew: People", "With people", "People sign off", HR_OFFICER, 0),
	("assigner_gm", "Crew: Director", "With the director", "Director sign off", MANAGER, 0),

	("actuals_submit", "Work done: Record", "Drafting", "Send for approval", HR_OFFICER, 1),
	("actuals_farm_manager", "Work done: Section", "With the section", "Section sign off",
		MANAGER, 1),
	("actuals_hr_head", "Work done: People", "With people", "People sign off", HR_OFFICER, 0),
	("actuals_gm", "Work done: Manager", "With the manager", "Sign off", MANAGER, 1),

	("payment_accounts", "Pay: Release", "Not yet paid", "Release", HR_OFFICER, 1),
]

#: Which steps are switched off, spelled out so the count in the docstring is
#: checked rather than claimed.
OFF = tuple(key for key, _l, _s, _a, _r, on in STEPS if not on)

#: The farm-scoped steps keep their scoping: Altura relabelled the chain, it did
#: not stop scoping work by farm.
SCOPED = {stage.key for stage in approvals.CATALOGUE if stage.scoped}

#: The farm this site works. One, which is what makes the farm dimension easy to
#: read here: a person either decides it or decides nothing.
FARM = "Altura"
OTHER_FARM = "Kitale"


def farm_approver_role():
	"""{farm: role} as `get_config()["farm_approver_role"]` computes it.

	Mirrors api/config._farm_approver_role(): with no per-farm approver rows
	named, every farm falls back to the first farm-scoped stage's own role. That
	is the fallback every existing site runs on, and it is what makes `farms`
	answerable at all -- so the tests derive `farms` from it rather than asserting
	a person decides a farm the configuration never gave them.
	"""
	config = settings()
	stage_rows = approvals.stage_rows(config)
	mapping = {}
	for stage in approvals.CATALOGUE:
		if not stage.scoped:
			continue
		mapping.setdefault(FARM, approvals.stage_role(stage, stage_rows))
	return mapping


def farms_for(roles):
	"""The farms these roles decide -- ACT_FARMS / ASG_FARMS, computed as the
	dispatchers compute them."""
	held = set(roles or [])
	return [farm for farm, role in farm_approver_role().items() if role in held]


def rows():
	"""The `approval_stages` child rows, as Settings holds them."""
	out = []
	shipped = {stage.key: stage for stage in approvals.CATALOGUE}
	for idx, (key, label, state, action, role, on) in enumerate(STEPS, start=1):
		out.append(Row({
			"idx": idx,
			"stage": key,
			"stage_label": label,
			"document_type": shipped[key].document_type,
			"kind": shipped[key].kind,
			"state": state,
			"action": action,
			"role": role,
			"enabled": on,
			"scoped": 1 if key in SCOPED else 0,
			"required": 1 if shipped[key].required else 0,
		}))
	return out


def settings(stage_approvers=None):
	"""What `approvals.configured_stages(settings)` and friends read."""
	return Settings(approval_stages=rows(),
		stage_approvers=[Row(r) for r in (stage_approvers or [])])


def chain_rows(document_type=None):
	"""What `get_config()["stage_rows"]` hands the dispatchers, Altura-shaped."""
	config = settings()
	return approvals.effective_chain(
		config, rows=approvals.stage_rows(config), document_type=document_type)


def states(document_type):
	"""What `get_config()["stage_states"][document_type]` would hold."""
	config = settings()
	return approvals.pipeline_states(
		config, rows=approvals.stage_rows(config), document_type=document_type)


def step(key):
	"""One effective-chain row by key."""
	for row in chain_rows():
		if row["key"] == key:
			return row
	return None
