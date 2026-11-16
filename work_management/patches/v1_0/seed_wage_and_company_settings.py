"""Carry the old hard-coded wage tiers, worker type and pack company into Settings.

These used to be compiled into the app (340 and 350 wage tiers, the "Task Worker"
employment type, the "Kaitet Ltd." payroll pack company). They are Settings now, so
a site that was already running keeps behaving as before:

  - known_daily_wages is seeded "340, 350" only where current_daily_wage is already
    set, i.e. a site that has applied a rate card. A new site starts with no tiers.
  - default_worker_employment_type is seeded "Task Worker" where that Employment
    Type exists (the Link would not validate otherwise; blank already means it).
  - payroll_pack_company is seeded only where a Company called "Kaitet Ltd." exists.

Each is written only while its field is empty, so it never overwrites a choice.
"""

import frappe

SETTINGS = "Work Management Settings"


def execute():
	if not frappe.db.exists("DocType", SETTINGS):
		return

	def empty(field):
		return not frappe.db.get_single_value(SETTINGS, field)

	if empty("known_daily_wages") and frappe.utils.flt(
			frappe.db.get_single_value(SETTINGS, "current_daily_wage")) > 0:
		frappe.db.set_single_value(SETTINGS, "known_daily_wages", "340, 350")

	if empty("default_worker_employment_type") and frappe.db.exists("Employment Type", "Task Worker"):
		frappe.db.set_single_value(SETTINGS, "default_worker_employment_type", "Task Worker")

	if empty("payroll_pack_company") and frappe.db.exists("Company", "Kaitet Ltd."):
		frappe.db.set_single_value(SETTINGS, "payroll_pack_company", "Kaitet Ltd.")
