"""Workflow-state Notifications for transitions Frappe never sees.

Frappe evaluates a "Value Change" Notification in
`Document.run_notifications("on_change")`, during an ordinary save -- and
never during an insert (`if not self.flags.in_insert`). The screens move most
documents by `frappe.db.set_value`, which runs no document hooks at all:

- an assignment is inserted as Draft and then written straight to its next
  state, so "Assigned" never fired;
- a plan's approval and rejection, every actuals step, and every master plan
  step are column writes.

So the thirteen "Value Change on workflow_state" Notifications a site sets up
for these doctypes fired for the one transition that happens to be a save (a
plan going Draft -> Pending Approval) and for nothing else.

`notify_state_change()` is called by every path that writes the state
directly. It evaluates exactly the Notifications Frappe would have -- enabled,
event "Value Change", watching `workflow_state` -- each against its own
condition, after the transaction commits.

NOT CALLED FROM A SAVE. A path that moves the state through `doc.save()`
already fires natively; calling this as well would send every email twice.
Not called from patches either: the rescue patch renames states, and a rename
is not news to anybody.

A NOTIFICATION NEVER UNDOES AN APPROVAL. Everything here is caught and
written to the Error Log. The send runs after commit, in a background job, so
by the time it can fail the approval is already on disk.
"""

import frappe

STATE_FIELD = "workflow_state"


def state_alerts(doctype):
	"""The Notifications Frappe would evaluate on a change of this doctype's state."""
	return frappe.get_all("Notification", filters={
		"enabled": 1,
		"document_type": doctype,
		"event": "Value Change",
		"value_changed": STATE_FIELD,
	}, pluck="name", order_by="name")


def notify_state_change(doctype, name, previous_state, new_state=None):
	"""Queue the state Notifications for one transition written without a save.

	`previous_state` is what the document held before the write -- None or
	"Draft" for a document inserted straight into a later state. `new_state`
	defaults to what is on the row now. Nothing happens when the two agree.
	"""
	try:
		if frappe.flags.in_patch or frappe.flags.in_install or frappe.flags.in_migrate:
			return
		if new_state is None:
			new_state = frappe.db.get_value(doctype, name, STATE_FIELD)
		if not new_state or new_state == previous_state:
			return
		if not state_alerts(doctype):
			return
		frappe.enqueue(
			"work_management.notify.send_state_change",
			queue="short",
			# a test has no worker to hand the job to, and rolls back rather
			# than commits: it sends in line instead, inside its transaction
			now=bool(frappe.in_test),
			enqueue_after_commit=True,
			doctype=doctype,
			name=name,
			previous_state=previous_state,
			new_state=new_state,
		)
	except Exception:
		frappe.log_error(title="Work Management: could not queue a state notification",
			reference_doctype=doctype, reference_name=name)


def send_state_change(doctype, name, previous_state, new_state):
	"""Evaluate and send each state Notification for one transition.

	Each Notification is judged against the document AS IT WAS at that
	transition: `workflow_state` is set to `new_state` even if the document has
	moved on since, so two quick approvals send two emails, each about its own
	step. And Frappe's own "did the value change?" test compares against
	`get_doc_before_save()`, so the document is handed a before-copy carrying
	`previous_state` -- otherwise a stale copy (or none) decides it.
	"""
	from frappe.email.doctype.notification.notification import evaluate_alert

	try:
		if not frappe.db.exists(doctype, name):
			return
		doc = frappe.get_doc(doctype, name)
		current = doc.get(STATE_FIELD)
		if current != new_state and current == previous_state:
			# the write this was queued for did not survive (a bulk run rolls a
			# failed document back to its savepoint): there is nothing to announce
			return
		before = frappe.get_doc(doc.as_dict())
		before.set(STATE_FIELD, previous_state)
		doc.set(STATE_FIELD, new_state)
		doc._doc_before_save = before
		doc.flags.notifications_executed = []
	except Exception:
		frappe.log_error(title="Work Management: could not load a document to notify about",
			reference_doctype=doctype, reference_name=name)
		return

	for alert in state_alerts(doctype):
		try:
			evaluate_alert(doc, alert, "Value Change")
			doc.flags.notifications_executed.append(alert)
		except Exception:
			# evaluate_alert logs a template error itself and then raises; anything
			# else is logged here. Either way the next Notification still runs.
			frappe.log_error(title="Work Management: notification " + str(alert) + " failed",
				reference_doctype=doctype, reference_name=name)
