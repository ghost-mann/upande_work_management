# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class WorkManagementPayableEmploymentType(Document):
	"""An employment type whose holders are paid per unit.

	One row of a list in Work Management Settings. Any one of the three lists
	matching is enough for a person's work to be paid per unit.
	"""

	pass
