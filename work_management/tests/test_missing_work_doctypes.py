"""Missing work: the excuse record, the Settings switches and the crew flag."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DT = ROOT / "work_management" / "doctype"
REASONS = ["Sent home – no work", "Rain / weather", "Sick / left early", "Scanned but not working", "Other"]


def load(name):
	return json.loads((DT / name / (name + ".json")).read_text())


def fields(doc):
	return {f["fieldname"]: f for f in doc["fields"]}


class TestExcuse(unittest.TestCase):
	def setUp(self):
		self.doc = load("work_missing_day_excuse")
		self.f = fields(self.doc)
		self.py = (DT / "work_missing_day_excuse" / "work_missing_day_excuse.py").read_text()

	def test_excuse_fields(self):
		want = {"employee": "Link", "employee_name": "Data", "farm": "Data", "work_date": "Date",
			"reason": "Select", "note": "Small Text", "assignment": "Link", "marked_by": "Link",
			"marked_at": "Datetime", "payroll_check": "Data"}
		for name, ftype in want.items():
			self.assertEqual(self.f[name]["fieldtype"], ftype, name)
		self.assertEqual(self.f["reason"]["options"], "\n".join(REASONS))
		self.assertEqual(self.f["assignment"]["options"], "Work Management Assigner")
		self.assertEqual(self.doc["name"], "Work Missing Day Excuse")
		self.assertEqual(self.doc["module"], "Work Management")
		self.assertEqual(self.doc["field_order"], [f["fieldname"] for f in self.doc["fields"]])

	def test_unique_employee_day(self):
		self.assertIn('frappe.db.exists("Work Missing Day Excuse", {"employee": self.employee, '
			'"work_date": self.work_date, "name": ["!=", self.name]})', self.py)

	def test_note_required_for_other(self):
		self.assertIn('self.reason == "Other"', self.py)
		self.assertIn("self.note", self.py)


class TestSettingsAndCrew(unittest.TestCase):
	def test_settings_fields(self):
		doc = load("work_management_settings")
		f = fields(doc)
		self.assertEqual(f["missing_work_reminder"]["fieldtype"], "Check")
		self.assertEqual(f["missing_work_reminder"].get("default"), "0")
		self.assertEqual(f["missing_work_notify"]["fieldtype"], "Small Text")
		self.assertIn("missing_work_reminder", doc["field_order"])
		self.assertIn("missing_work_notify", doc["field_order"])

	def test_crew_field(self):
		doc = load("work_assignment_employee")
		f = fields(doc)
		self.assertEqual(f["added_for_check"]["fieldtype"], "Data")
		self.assertEqual(f["added_for_check"].get("read_only"), 1)
		self.assertIn("added_for_check", doc["field_order"])


if __name__ == "__main__":
	unittest.main()
