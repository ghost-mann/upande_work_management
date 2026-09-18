# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class WorkManagementPayment(Document):
	pass


@frappe.whitelist()
def bulk_cancel(docnames):
	"""Cancel a batch of payments through the workflow - the same plain-save
	path a single Cancel already takes, so on_payment_update() still frees
	the claimed actuals rows and cancels the linked Additional Salary.

	Not the native bulk Cancel: Frappe hides that entirely once a doctype has
	a workflow (list_view.js's is_bulk_edit_allowed()), since the workflow's
	own transitions are meant to be the only path to Cancelled. This reaches
	the Actions menu instead via work_management_payment_list.js, and leaves
	the workflow's own permission rule (System Manager only) to doc.save().
	"""
	docnames = frappe.parse_json(docnames) if isinstance(docnames, str) else docnames
	cancelled, skipped = [], []
	for name in docnames:
		try:
			doc = frappe.get_doc("Work Management Payment", name)
			if doc.workflow_state not in ("Unpaid", "Paid"):
				skipped.append({"name": name, "reason": "already " + str(doc.workflow_state)})
				continue
			doc.workflow_state = "Cancelled"
			doc.save()
			cancelled.append(name)
		except Exception as e:
			frappe.clear_last_message()
			skipped.append({"name": name, "reason": str(e)})
	return {"cancelled": cancelled, "skipped": skipped}
