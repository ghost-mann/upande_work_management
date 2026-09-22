# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Whether a generated workflow tells its approvers anything.

`build_workflows()` set `send_email_alert = 0` on all five workflows, every
time it ran. So a project could name its steps, point each at its own role,
name the people who hold it -- and nothing would ever tell any of them there
was work waiting. Nobody noticed while the desk's awaiting-approval inbox was
the only route in; on a site whose approvers live on the web screens, "nothing
tells me there is work" is the whole experience.

It is a Settings checkbox now, and the alert is **Frappe's own**: the
notification with inline Approve and Reject links that `frappe/workflow`
already sends, addressed by the transition's role. Not a notification layer of
this app's -- a second implementation of "who should hear about this" is a
second answer to it, and they disagree the first time either moves.

**Off unless a site turns it on.** Switching it on for everybody at migrate
would send mail from sites that have never sent any, about documents that have
been sitting in a queue for months.

    PYTHONPATH=. ~/frappe-bench3/env/bin/python -m unittest \\
        work_management.tests.test_approvers_can_be_emailed -v
"""

import json
import os
import unittest

from work_management import approvals

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_JSON = os.path.join(APP, "work_management", "doctype",
	"work_management_settings", "work_management_settings.json")


def read(path):
	with open(path, encoding="utf-8") as handle:
		return handle.read()


def settings_field(fieldname):
	doctype = json.loads(read(SETTINGS_JSON))
	for field in doctype["fields"]:
		if field["fieldname"] == fieldname:
			return field, doctype
	return None, doctype


class Settings(dict):
	"""A Settings stand-in: `.get()` is all `email_alerts_on()` asks of it."""


class TestTheSetting(unittest.TestCase):
	def test_the_field_exists(self):
		field, _ = settings_field(approvals.NOTIFY_FIELD)
		self.assertIsNotNone(field, "%s is not on Work Management Settings"
			% approvals.NOTIFY_FIELD)
		self.assertEqual(field["fieldtype"], "Check")

	def test_it_ships_off(self):
		"""An existing site migrates and nothing changes about who gets mail."""
		field, _ = settings_field(approvals.NOTIFY_FIELD)
		self.assertEqual(field.get("default"), "0")

	def test_it_says_what_it_does(self):
		field, _ = settings_field(approvals.NOTIFY_FIELD)
		self.assertIn("Approve", field.get("description", ""))
		self.assertIn("off by default", field.get("description", "").lower())

	def test_it_sits_with_the_chain_it_belongs_to(self):
		field, doctype = settings_field(approvals.NOTIFY_FIELD)
		order = doctype["field_order"]
		self.assertIn(approvals.NOTIFY_FIELD, order)
		self.assertLess(order.index("tab_approvals"), order.index(approvals.NOTIFY_FIELD))
		self.assertLess(order.index(approvals.NOTIFY_FIELD), order.index("stage_approvers"))


class TestReadingIt(unittest.TestCase):
	"""Pure: no site, so the "nothing said" cases can be read directly."""

	def test_on_when_the_box_is_ticked(self):
		self.assertTrue(approvals.email_alerts_on(Settings({approvals.NOTIFY_FIELD: 1})))

	def test_off_when_it_is_not(self):
		self.assertFalse(approvals.email_alerts_on(Settings({approvals.NOTIFY_FIELD: 0})))

	def test_off_when_the_field_is_not_there_at_all(self):
		"""A Settings document saved before this field existed. An attribute
		would raise here; `.get()` reads as off, which is today's behaviour."""
		self.assertFalse(approvals.email_alerts_on(Settings()))

	def test_off_on_a_site_with_no_settings_yet(self):
		self.assertFalse(approvals.email_alerts_on(None) or False)


class TestTheGeneratedWorkflowCarriesIt(unittest.TestCase):
	SOURCE = read(os.path.join(APP, "approvals.py"))

	def test_the_flag_is_no_longer_hardcoded_off(self):
		self.assertNotIn("workflow.send_email_alert = 0", self.SOURCE)

	def test_it_follows_the_setting(self):
		self.assertIn("workflow.send_email_alert = 1 if notify else 0", self.SOURCE)

	def test_the_setting_is_read_once_for_all_five(self):
		"""Read per workflow, a Settings reload mid-loop could leave two of the
		five disagreeing about whether this site sends mail."""
		at = self.SOURCE.index("def build_workflows(")
		body = self.SOURCE[at:self.SOURCE.index("\ndef ", at + 10)]
		self.assertLess(body.index("notify = email_alerts_on(settings)"),
			body.index("for document_type in CHAIN_ENDS:"))
		# comments stripped: one of them points the reader at the helper
		code = "\n".join(line for line in body.splitlines()
			if not line.lstrip().startswith("#"))
		self.assertEqual(code.count("email_alerts_on("), 1)

	def test_saving_settings_regenerates_the_workflows(self):
		"""Otherwise ticking the box changes nothing until the next migrate."""
		controller = read(os.path.join(APP, "work_management", "doctype",
			"work_management_settings", "work_management_settings.py"))
		self.assertIn("approvals.build_workflows(self)", controller)

	def test_no_notification_layer_of_our_own(self):
		"""The whole point of using Frappe's alert is that there is one answer to
		"who hears about this", and the workflow transition already holds it."""
		self.assertNotIn("sendmail", self.SOURCE)
		self.assertNotIn('"Notification"', self.SOURCE)


if __name__ == "__main__":
	unittest.main()
