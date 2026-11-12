# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class WorkManagementTeamLeader(Document):
	"""A farm's team leader. The Planner's Team leaders tab writes these through
	wm_masterplan (tl_save); this guards the Desk form the same way."""

	def validate(self):
		if self.user and not frappe.db.get_value("User", self.user, "enabled"):
			frappe.throw(f"{self.user} is not an active user.")
		if self.is_new():
			self.added_by = self.added_by or frappe.session.user
			self.added_on = self.added_on or frappe.utils.now()
		self.changed_by = frappe.session.user
		self.changed_on = frappe.utils.now()
