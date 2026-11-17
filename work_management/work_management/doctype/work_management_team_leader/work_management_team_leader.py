# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class WorkManagementTeamLeader(Document):
	"""A farm's team leader. The Planner's Team leaders tab writes these through
	wm_masterplan (tl_save); this guards the Desk form the same way."""

	def validate(self):
		# a login when the person has one, else their Employee ID (2026-11-17)
		if self.user and self.active and not (
			frappe.db.get_value("User", self.user, "enabled")
			or frappe.db.get_value("Employee", {"name": self.user, "status": "Active"}, "name")
		):
			frappe.throw(f"{self.user} is neither an active login nor an active employee.")
		if self.user and not self.full_name:
			self.full_name = frappe.db.get_value("User", self.user, "full_name") or frappe.db.get_value(
				"Employee", self.user, "employee_name"
			)
		if self.is_new():
			self.added_by = self.added_by or frappe.session.user
			self.added_on = self.added_on or frappe.utils.now()
		self.changed_by = frappe.session.user
		self.changed_on = frappe.utils.now()
