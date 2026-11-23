# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from work_management import day_guard


class WorkManagementActuals(Document):
	def validate(self):
		# no worker-day is captured twice, or past the day's hours, on any path
		# that writes day-rows -- the actuals screen, the desk form, a script.
		# See day_guard.
		day_guard.validate(self)
