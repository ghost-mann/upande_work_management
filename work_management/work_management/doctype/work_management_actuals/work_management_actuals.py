# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from work_management import actuals_pay, day_guard


class WorkManagementActuals(Document):
	def validate(self):
		# whatever path the save came through -- the actuals screen, the desk
		# form, a script -- the money follows the quantity. See actuals_pay.
		actuals_pay.refuse_row_edits(self)
		actuals_pay.price(self)
		# and no worker-day is captured twice, or past the day's hours, on any
		# of those paths. See day_guard.
		day_guard.validate(self)
