# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from work_management.master_plan import master_plan_name


class WorkManagementMasterPlan(Document):
	def autoname(self):
		# Settings > Naming > Document names, when set (Altura: GH-3-MP-26-001).
		# Unset, nothing is assigned here and the doctype's WMMP-##### applies.
		name = master_plan_name(self)
		if name:
			self.name = name

	def validate(self):
		self.validate_greenhouse()

	def validate_greenhouse(self):
		"""The greenhouse has to be one of this farm's locations, and an approved
		plan's greenhouse is fixed: the requests drawing on it were matched to it."""
		if self.greenhouse:
			gh_farm = frappe.db.get_value("Warehouse", self.greenhouse, "custom_farm")
			if self.farm and gh_farm and gh_farm != self.farm:
				frappe.throw(_("{0} is on {1}, not on {2}.").format(
					self.greenhouse, gh_farm, self.farm))
		if not self.is_new():
			before = self.get_doc_before_save()
			if (before and before.workflow_state == "Approved"
					and (before.greenhouse or "") != (self.greenhouse or "")):
				frappe.throw(_("The greenhouse on an approved master plan cannot be changed: "
					"the weekly plans holding this budget were matched to {0}.").format(
					before.greenhouse or _("the whole farm")))
