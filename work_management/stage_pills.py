"""The approval queues a screen offers, built from the configured chain.

Every Approvals tab drew its own tab strip from a list written into the script:
`Farm Manager / HR Head / GM` on the assigner, `HR Head / GM / Close Requests`
on actuals, `Consultant / General Manager` on the master plan tab. The chain
stopped being those names when it became configurable, and on Altura the two
have now visibly parted company -- the workflows regenerated and the transitions
follow the new chain, while every strip still shows the old one. A step switched
off keeps a tab that can never have anything in it, a step renamed keeps its old
name, and a step ADDED gets no tab at all, so its documents are reachable only
from the desk.

Three rules, and the second is the one worth stating:

**A queue is a step of kind Approval.** `Submit` moves a draft into the chain and
is not somewhere documents wait.

**A switched-off step still shows while documents sit in it.** Turning a step off
says "stop routing work here", not "abandon what is already there". This is the
same reading `config.get_config()` takes for list filters -- `stage_states`
deliberately includes the states of disabled steps, so a report does not narrow
because somebody changed a setting. Such a tab is marked `legacy` and disappears
on its own once the last document leaves.

It is a tab you can READ, not one you can clear from. The approve actions refuse
a switched-off step outright -- "The HR Head step is switched off for this
project." -- and that gate is deliberate and is not this module's to move. So the
tab exists to make stranded work VISIBLE and countable, and its marker says what
actually clears it: switch the step back on, decide them, switch it off again.
Before this, those documents were invisible on every screen and reachable only
from the desk, which is the worse half of the same problem.

**Which tabs appear does not depend on who is looking.** An HR person may read
the farm manager's queue; whether they can act on what they find is the buttons'
question and the server's, and both already answer it. Hiding the tab instead
answered a different question -- "is this yours?" -- with "does this exist?".
"""

import frappe

#: Steps that are somewhere a document waits. Submit is not.
QUEUE_KIND = "Approval"


def label_for(step):
	"""What to call the tab.

	The configured label, because that is what somebody typed into Settings and
	what the desk shows them. Falling back to the role and then to the state
	means a half-filled row still gets a tab with a name on it rather than a
	blank one.
	"""
	for candidate in (step.get("label"), step.get("role"), step.get("state")):
		if candidate and str(candidate).strip():
			return str(candidate).strip()
	return step.get("key") or "Approval"


def shared_prefix(labels):
	"""The `"Something: "` every label starts with, or "".

	The shipped labels name their screen -- `Assigner: HR Head`, `Actuals: GM` --
	which reads well in Settings, where all fifteen sit in one grid, and reads as
	stutter on the Assigner's own tab strip where every tab says `Assigner:`.

	Trimmed only when EVERY label shares it, so a site that renames one step out
	of the convention gets all of them verbatim rather than a strip where some
	tabs are abbreviated and others are not. Nothing is lost either way: `label`
	stays exactly what was typed and `short_label` is what a tab prints.
	"""
	heads = []
	for label in labels:
		head, sep, rest = (label or "").partition(": ")
		if not sep or not rest.strip():
			return ""
		heads.append(head)
	if len(set(heads)) != 1 or not heads:
		return ""
	return heads[0] + ": "


def build(steps, counts):
	"""The tab strip for one document type. Pure.

	`steps` is the chain as `approvals.effective_chain()` returns it, already
	narrowed to one document type; `counts` is {workflow_state: how many}.
	"""
	pills = []
	for step in steps:
		if step.get("kind") != QUEUE_KIND:
			continue
		state = step.get("state")
		if not state:
			continue
		waiting = int(counts.get(state) or 0)
		on = bool(step.get("on"))
		if not on and not waiting:
			continue
		pills.append({
			"key": step.get("key"),
			"label": label_for(step),
			"state": state,
			"action": step.get("action"),
			"role": step.get("role"),
			"scoped": 1 if step.get("scoped") else 0,
			"on": 1 if on else 0,
			# switched off, and still holding work somebody has to get out of it
			"legacy": 0 if on else 1,
			"count": waiting,
		})
	trim = shared_prefix([pill["label"] for pill in pills])
	for pill in pills:
		pill["short_label"] = pill["label"][len(trim):] if trim else pill["label"]
	return pills


def scope_farms(step, farm_approver_role, roles):
	"""Which farms this step's count should be narrowed to, or None for all.

	A farm-scoped step shows a farm manager their own farms and nobody else's,
	so a badge that counted every farm's would promise a queue the tab does not
	then show. Read from the step's own `scoped` flag rather than from a state
	name, which is the thing that moves when a chain is reconfigured.
	"""
	if not step.get("scoped"):
		return None
	held = set(roles or [])
	if held & {"System Manager", "General Manager"}:
		return None
	return sorted(farm for farm, role in (farm_approver_role or {}).items()
		if role in held)


def _count(document_type, state, farms):
	filters = {"workflow_state": state}
	if farms is not None:
		filters["farm"] = ["in", farms or ["__none__"]]
	return frappe.db.count(document_type, filters)


def for_document_type(document_type, steps, farm_approver_role=None, roles=None):
	"""`build()` with the counts filled in from the database."""
	if not frappe.db.table_exists(document_type):
		return []
	mine = [step for step in (steps or [])
		if step.get("document_type") == document_type
		and step.get("kind") == QUEUE_KIND and step.get("state")]
	if not mine:
		return []
	roles = roles if roles is not None else frappe.get_roles()
	has_farm = frappe.db.has_column(document_type, "farm")
	counts = {}
	for step in mine:
		farms = scope_farms(step, farm_approver_role, roles) if has_farm else None
		counts[step["state"]] = _count(document_type, step["state"], farms)
	return build(mine, counts)
