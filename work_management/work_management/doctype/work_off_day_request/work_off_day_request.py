# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class WorkOffDayRequest(Document):
	"""Permission to record one worker's work on one of their off days.

	Raised from the Actuals grid against an assignment; the farm's Farm Manager
	(or the GM) approves or rejects it. Only an Approved request opens that
	worker's cell for that date.
	"""
