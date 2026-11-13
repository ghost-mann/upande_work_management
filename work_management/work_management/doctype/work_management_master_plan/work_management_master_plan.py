# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class WorkManagementMasterPlan(Document):
	def validate(self):
		self.refuse_duplicate_activities()

	def refuse_duplicate_activities(self):
		"""One row per activity (2026-11-13): a second row for the same activity
		splits its budget in two and lets plans draw on both. The Planner screen
		refuses it too; this holds the desk and imports to the same rule."""
		seen, dup = set(), []
		for row in self.get("activities") or []:
			if row.task and row.task in seen and row.task not in dup:
				dup.append(row.task)
			seen.add(row.task)
		if dup:
			frappe.throw(_("Each activity may appear only once in a master plan. Listed more than once: {0}").format(
				", ".join(frappe.db.get_value("Task", t, "subject") or t for t in dup[:6])))
