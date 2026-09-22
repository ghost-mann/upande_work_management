# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Addressing a step of the approval chain, by the one name that is stable.

A step has four names and only one of them belongs to this app:

    key         `assigner_farm_manager` -- the catalogue's own identifier. It is
                the same on every site, it does not change when a step is
                relabelled or handed to another role, and it is what
                `effective_chain()` already keys everything by.
    label       what somebody typed into Settings. Altura's says
                `Assigner: Manager`.
    state       the workflow state documents wait in. Configurable.
    action      the workflow ACTION, `FM Approve`. This is Frappe's vocabulary,
                not this API's: it names a Workflow Transition and is what the
                desk button says.

The screens used to address the API by the fourth. `stage_pills` hands each tab
the step's `action` so the desk and the tab agree on wording, the assigner took
that string and posted it as its own `action` parameter, and the dispatcher --
which has never had an action called `FM Approve` -- answered

    unknown action: FM Approve

on Altura, where the pills were the first thing to carry a configured chain. The
bulk endpoints had the same fault one layer down: they whitelisted `fm`, `gm`,
`hr`, which the screen derived by splitting `a_fm_approve` on an underscore, so
a configured action produced `undefined` and

    stage must be one of fm, gm, hr -- the queue on screen decides it

Both are the same mistake: a screen holding a piece of the chain's vocabulary in
its own hands. So the wire now carries the **key**, which is the only one of the
four a screen may know, and even that it only ever learns from the server.

Everything here is pure -- it takes the chain as `approvals.effective_chain()`
returns it, a list of plain dicts -- so it can be tested without a site and
called from every dispatcher without another database read.
"""

#: A step somebody waits in. `Submit` moves a draft into the chain and is not a
#: queue; see stage_pills.QUEUE_KIND, which draws the same line for the tabs.
APPROVAL = "Approval"


def steps_of(steps, document_type):
	"""Every configured step of one document type, in chain order."""
	return [step for step in (steps or []) if step.get("document_type") == document_type]


def approval_steps(steps, document_type, enabled_only=False):
	"""The steps of one document type a document can wait in.

	`enabled_only` is what a WRITE asks: a switched-off step is still a real step
	-- documents sit in it and its tab still shows -- but nothing may be routed
	into it. A read wants both, which is the default.
	"""
	out = [step for step in steps_of(steps, document_type) if step.get("kind") == APPROVAL]
	return [step for step in out if step.get("on")] if enabled_only else out


def stage_keys(steps, document_type, enabled_only=False):
	"""The keys those steps are addressed by, in chain order."""
	return [step.get("key") for step in approval_steps(steps, document_type, enabled_only)
		if step.get("key")]


def by_key(steps, document_type, key):
	"""One step by its key, or None. Approval steps only -- Submit is not a queue."""
	wanted = (key or "").strip()
	if not wanted:
		return None
	for step in approval_steps(steps, document_type):
		if step.get("key") == wanted:
			return step
	return None


def at_state(steps, document_type, state):
	"""The step a document in `state` is waiting in, or None.

	Switched-off steps included, deliberately: a document stranded in a retired
	step still has to be identifiable, or nothing on screen can say why it cannot
	move. Whether the step may be TAKEN is the caller's next question, and
	`step["on"]` answers it.
	"""
	if not state:
		return None
	for step in approval_steps(steps, document_type):
		if step.get("state") == state:
			return step
	return None


def label_of(step, fallback=None):
	"""What to call a step in a sentence: its configured label, else its key."""
	if not step:
		return fallback
	for candidate in (step.get("label"), step.get("key")):
		if candidate and str(candidate).strip():
			return str(candidate).strip()
	return fallback


def state_labels(steps, document_type=None):
	"""{workflow state: the configured label of the step waiting in it}.

	What a screen prints instead of the raw state. Terminal, draft and reject
	states are absent by design -- they are not steps, nothing configures them,
	and a caller falls back to the raw string, which is already the right word
	for `Approved` or `Rejected`.
	"""
	out = {}
	rows = (approval_steps(steps, document_type) if document_type
		else [s for s in (steps or []) if s.get("kind") == APPROVAL])
	for step in rows:
		state = step.get("state")
		label = label_of(step)
		if state and label and state not in out:
			out[state] = label
	return out


def unknown_stage(key, steps, document_type):
	"""Why `key` is not a step of this chain, naming the ones that are.

	The old message named `fm, gm, hr` -- three abbreviations of the shipped
	chain, which on a reconfigured site are not merely wrong but meaningless.
	This lists what the site actually runs, which is both the correct answer and
	the one a person can act on.
	"""
	valid = stage_keys(steps, document_type)
	if not valid:
		return ("this document type has no approval steps configured, so there is "
			"no stage to approve at")
	given = (key or "").strip()
	return ("%s is not an approval step of this chain — it is one of %s. The queue "
		"on screen decides which." % (("'%s'" % given) if given else "no stage", ", ".join(valid)))


def resolve(steps, document_type, stage=None, state=None):
	"""The step a request means, as `(step, error)`. Exactly one is None.

	Two ways to name a step and one rule. A request that carries a `stage` means
	that step -- by its key, which is what the screens send, or by its workflow
	state, which is what `stage_pills` also publishes and what older callers
	pass. Both are the server's own vocabulary, handed to the screen by the
	server; neither is anything a screen may invent. Anything else is an error
	worth spelling out, because it is a screen and a configuration that have
	parted company -- precisely the failure this module exists to make loud.

	A request that carries no stage means "whichever step this document is
	waiting in", which is how the planner has always resolved it and the shape
	every screen now follows. No step there is not an error here: "not awaiting
	approval" is the caller's sentence to write, because only the caller knows
	the document's name and state.
	"""
	asked = (stage or "").strip()
	if asked:
		step = by_key(steps, document_type, asked) or at_state(steps, document_type, asked)
		if not step:
			return None, unknown_stage(asked, steps, document_type)
		return step, None
	return at_state(steps, document_type, state), None


def may_take(step, roles, farm=None, farms=None):
	"""Why this person may not take this step, or None.

	Two dimensions gate a step and only one applies to each, which is the
	distinction `effective_chain()` publishes as `scoped` so that no screen has
	to recognise a step by name to know which question to ask.

	A FARM-SCOPED step asks which farms this person decides. An unscoped step
	asks whether they hold the step's own role -- `approvals.may_take_step()`'s
	rule, where System Manager bypasses (somebody has to be able to unstick a
	pipeline) and General Manager deliberately does not, because a GM taking the
	HR step erases the separation the chain exists to express.

	Pure, and worded from the CONFIGURED label and role throughout: a refusal
	that names the shipped role sends the reader to the wrong desk.
	"""
	held = set(roles or [])
	role = step.get("role")
	label = label_of(step, "this")
	bypass = "System Manager" in held

	if not step.get("on"):
		return "The %s step is switched off for this project." % label

	if step.get("scoped"):
		# the farm dimension, where the GM oversees every farm
		if bypass or "General Manager" in held:
			return None
		mine = list(farms or [])
		if not mine:
			return ("You decide no farms at the %s step. Ask an administrator to name "
				"you an approver for your farm in Work Management Settings." % label)
		if farm is not None and farm not in mine:
			return ("You can only decide %s for your farm(s): %s. This one is for %s."
				% (label, ", ".join(mine), farm))
		return None

	if not role:
		return ("Nobody is configured to take the %s step, so it cannot be taken. "
			"Name a role for it in Work Management Settings." % label)
	if role in held or bypass:
		return None
	return "Only %s can take the %s step. You do not hold it." % (role, label)


def takeable(steps, document_type, roles, farms=None):
	"""The enabled steps of this chain this person may take, in chain order.

	What decides whether an Approvals tab is offered, and what the header suffix
	names. Read from the chain, so a site that renamed every step and handed each
	to a role of its own gets the same answer -- which the screens did not: the
	planner asked whether the user's role began with the shipped `Farm Manager`
	and hid the tab from Altura's Production Manager entirely.
	"""
	return [step for step in approval_steps(steps, document_type, enabled_only=True)
		if may_take(step, roles, farm=None, farms=farms) is None]


def approver_suffix(steps, document_types, roles, farms=None, neutral="Approver"):
	"""What to call this person in a header, from the chain. "" when they take none.

	The screens printed `· HR Head` -- a shipped role name -- for anyone the
	shipped HR question said yes to, so Altura's Production Manager was greeted
	as an HR Head. The honest answer is the step or steps they can actually act
	on; past two, naming them all is noise rather than information, so a neutral
	word stands in.
	"""
	labels = []
	for document_type in document_types:
		for step in takeable(steps, document_type, roles, farms=farms):
			label = short_label(step)
			if label and label not in labels:
				labels.append(label)
	if not labels:
		return ""
	if len(labels) > 2:
		return neutral
	return " / ".join(labels)


def short_label(step):
	"""A step's label without the `Screen: ` its Settings row carries.

	`stage_pills.build()` computes the same trim for a tab strip, where it can
	compare every label at once. One step on its own cannot, so this drops a
	single leading `Something: ` -- which is what the shipped convention puts
	there and what a header has no room to repeat.
	"""
	label = label_of(step) or ""
	head, sep, rest = label.partition(": ")
	return rest.strip() if (sep and rest.strip()) else label
