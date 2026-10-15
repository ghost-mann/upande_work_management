# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from work_management import approvals, desk, taxonomy


class WorkManagementSettings(Document):
	def validate(self):
		approvals.validate_configuration(self)
		self.validate_pay_month()

	def validate_pay_month(self):
		"""A pay month opens on a day every month has. The 29th to the 31st do
		not exist in February, so a month "from the 30th" has no honest answer."""
		if self.get("pay_frequency") != "Monthly":
			return
		day = frappe.utils.cint(self.get("pay_month_start_day"))
		if day < 1 or day > 28:
			frappe.throw(frappe._("Month start day must be between 1 and 28 (it is {0}).").format(day),
				title=frappe._("Pay frequency"))

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
		# a step added in this very save has to be choosable in the approver picker
		approvals.apply_stage_picker_options(self)
		taxonomy.apply_labels(self)
		# The desk navigation carries level names too, and no Property Setter
		# reaches a Workspace Link -- without this a rename shows on the forms
		# immediately and down the side of the desk only after a migrate.
		desk.relabel_navigation(self)
