# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from work_management import approvals


class WorkManagementSettings(Document):
	def validate(self):
		approvals.validate_configuration(self)

	def on_update(self):
		"""Push the approval configuration out to roles and workflows.

		`skip_approval_sync` is set by seed_stages(), which saves this document
		itself while filling in the stage catalogue. Without it, seeding would
		recurse.
		"""
		if self.flags.get("skip_approval_sync"):
			return
		frappe.clear_cache(doctype="Work Management Settings")
		approvals.sync_roles(self, previous=self.get_doc_before_save())
		approvals.build_workflows(self)
