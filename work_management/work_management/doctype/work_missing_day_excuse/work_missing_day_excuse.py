# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class WorkMissingDayExcuse(Document):
	def validate(self):
		if frappe.db.exists("Work Missing Day Excuse", {"employee": self.employee, "work_date": self.work_date, "name": ["!=", self.name]}):
			frappe.throw(f"{self.employee} already has a reason for {self.work_date}.")
		if self.reason == "Other" and not (self.note or "").strip():
			frappe.throw("Say what happened when the reason is Other.")
