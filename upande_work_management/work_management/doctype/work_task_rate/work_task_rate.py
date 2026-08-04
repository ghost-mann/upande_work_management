# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, flt, getdate


class WorkTaskRate(Document):
	"""One rate period for one task.

	Periods for a task never overlap and at most one is left open (``valid_to``
	empty), which is the currently-active rate. Inserting a period that starts
	on D closes the previously-open one at D-1, so history stays contiguous
	without anyone having to maintain it by hand.
	"""

	def validate(self):
		self._check_dates()
		self._derive_rate()
		self._check_no_overlap()

	def after_insert(self):
		self._close_previous_open_period()
		self._sync_task()

	def on_update(self):
		self._sync_task()

	def on_trash(self):
		# remember the task; the row is gone by the time we resync
		self.flags.trashed_task = self.task

	def after_delete(self):
		task = self.flags.get("trashed_task") or self.task
		if task:
			from upande_work_management.rates import sync_task_from_periods

			sync_task_from_periods(task)

	# ---------------------------------------------------------------- checks

	def _check_dates(self):
		if self.valid_to and getdate(self.valid_to) < getdate(self.valid_from):
			frappe.throw(
				_("Valid To ({0}) cannot be before Valid From ({1}).").format(
					self.valid_to, self.valid_from
				)
			)

	def _derive_rate(self):
		"""A wage-derived period can compute its own rate.

		Only fills a blank rate — an explicitly supplied one is never
		overwritten, because backfilled periods must keep the legacy value that
		was actually used to pay people (e.g. Planting grass at 4.6 where the
		exact derivation is 4.5333).
		"""
		if flt(self.rate) or not self.derived:
			return
		if flt(self.daily_wage_basis) and flt(self.daily_target):
			self.rate = flt(self.daily_wage_basis) / flt(self.daily_target)

	def _check_no_overlap(self):
		"""No two periods for a task may cover the same day.

		The one exemption is the currently-open period that starts strictly
		before this one: inserting over it is the normal way to supersede a
		rate, and ``_close_previous_open_period`` will close it at D-1.
		"""
		rows = frappe.db.sql(
			"""
			SELECT name, valid_from, valid_to
			FROM `tabWork Task Rate`
			WHERE task = %(task)s
			  AND name != %(name)s
			  AND (valid_to IS NULL OR valid_to >= %(vfrom)s)
			""",
			{"task": self.task, "name": self.name or "", "vfrom": self.valid_from},
			as_dict=True,
		)
		for row in rows:
			# my period ends before theirs starts -> no clash
			if self.valid_to and getdate(row.valid_from) > getdate(self.valid_to):
				continue
			# an open period starting earlier is superseded, not clashing
			if not row.valid_to and getdate(row.valid_from) < getdate(self.valid_from):
				continue
			frappe.throw(
				_("Rate period {0} ({1} to {2}) already covers this range for {3}.").format(
					row.name, row.valid_from, row.valid_to or _("open"), self.task
				)
			)

	# ---------------------------------------------------------------- effects

	def _close_previous_open_period(self):
		"""Close the period this one supersedes at the day before it starts."""
		previous = frappe.db.sql(
			"""
			SELECT name FROM `tabWork Task Rate`
			WHERE task = %(task)s
			  AND name != %(name)s
			  AND valid_to IS NULL
			  AND valid_from < %(vfrom)s
			ORDER BY valid_from DESC
			""",
			{"task": self.task, "name": self.name, "vfrom": self.valid_from},
			as_dict=True,
		)
		for row in previous:
			frappe.db.set_value(
				"Work Task Rate", row.name, "valid_to", add_days(getdate(self.valid_from), -1)
			)

	def _sync_task(self):
		from upande_work_management.rates import sync_task_from_periods

		sync_task_from_periods(self.task)
