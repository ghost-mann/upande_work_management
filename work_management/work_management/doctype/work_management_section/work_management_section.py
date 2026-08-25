# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from work_management import sections


class WorkManagementSection(Document):
	def validate(self):
		self.refuse_the_reserved_name()
		self.refuse_duplicate_blocks()
		self.refuse_blocks_claimed_elsewhere()

	def refuse_the_reserved_name(self):
		if sections.is_reserved_name(self.section_name):
			frappe.throw(
				_("{0} is the name the cost-centre view gives to blocks that are in no "
				  "section, so a section cannot be called that. Its total and the "
				  "unclaimed blocks' total would be added together.").format(
					frappe.bold(self.section_name)),
				title=_("That name is taken by the unassigned group"),
			)

	def refuse_duplicate_blocks(self):
		repeated = sections.duplicate_blocks(self.get("blocks") or [])
		if repeated:
			frappe.throw(
				_("{0} appears more than once in this section. A block counted twice "
				  "doubles its cost in the section total.").format(
					frappe.bold(", ".join(repeated))),
				title=_("The same block is listed twice"),
			)

	def refuse_blocks_claimed_elsewhere(self):
		for row in self.get("blocks") or []:
			if not row.block:
				continue
			owner = sections.claimed_by(row.block, exclude=self.name)
			if owner:
				frappe.throw(
					_("{0} is already in section {1}. A block belongs to one section only, "
					  "so the section totals keep matching the block totals.").format(
						frappe.bold(row.block), frappe.bold(owner)),
					title=_("Block already in another section"),
				)
