"""Requests of 2026-11-13: assignment approval is farm manager only (the screen
shows only the steps switched on), one row per activity on a master plan, and
no work on a day marked Absent.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest work_management.tests.test_requests_2026_11_13 -v
"""

import importlib
import json
import os
import sys
import types
import unittest

from work_management.tests.test_amount_sanity import block
from work_management.tests.test_one_worker_one_day import Row, source

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestAssignmentQueues(unittest.TestCase):
	def test_the_server_says_which_steps_are_on(self):
		self.assertIn('out["stage_on"] = {"fm": 1 if STAGE_ON["assigner_farm_manager"]', block("assigner", "a_roles"))

	def test_the_screen_hides_switched_off_steps(self):
		js = open(os.path.join(HERE, "public", "js", "work-assigner.js")).read()
		self.assertIn("].filter(function(q){ return on[q.key]!==0; });", js)


class TestOneRowPerActivity(unittest.TestCase):
	def test_the_screen_save_refuses_a_repeat(self):
		self.assertIn("Each activity may appear only once in a master plan.", block("masterplan", "save"))

	def test_the_desk_refuses_a_repeat(self):
		fake = types.ModuleType("frappe")

		class Stop(Exception):
			pass

		def throw(msg, *a, **k):
			raise Stop(msg)

		fake.throw = throw
		fake._ = lambda s: s
		fake.db = types.SimpleNamespace(get_value=lambda dt, n, f: "Pruning")
		model = types.ModuleType("frappe.model")
		document = types.ModuleType("frappe.model.document")
		document.Document = object
		saved = {k: sys.modules.get(k) for k in ("frappe", "frappe.model", "frappe.model.document")}
		sys.modules.update({"frappe": fake, "frappe.model": model, "frappe.model.document": document})
		try:
			mod = importlib.import_module("work_management.work_management.doctype.work_management_master_plan.work_management_master_plan")
			importlib.reload(mod)
			doc = mod.WorkManagementMasterPlan()
			doc.get = lambda k: [Row(task="TASK-1"), Row(task="TASK-2"), Row(task="TASK-1")]
			with self.assertRaises(Stop):
				doc.refuse_duplicate_activities()
			doc.get = lambda k: [Row(task="TASK-1"), Row(task="TASK-2")]
			doc.refuse_duplicate_activities()
		finally:
			for k, v in saved.items():
				if v is None:
					sys.modules.pop(k, None)
				else:
					sys.modules[k] = v


class TestNoWorkOnAbsentDays(unittest.TestCase):
	def test_the_setting_exists_and_defaults_on(self):
		p = os.path.join(HERE, "work_management", "doctype", "work_management_settings", "work_management_settings.json")
		f = [x for x in json.load(open(p))["fields"] if x["fieldname"] == "att_absent_never"][0]
		self.assertEqual(f["default"], "1")
		with open(os.path.join(HERE, "patches.txt")) as handle:
			self.assertIn("switch_on_no_work_on_absent_days", handle.read())

	def test_saving_refuses_without_any_override(self):
		b = block("actuals", "act_submit")
		self.assertIn("if not wmg_err and att_absent_never and has_absent_conflict:", b)
		self.assertIn("no work can be recorded on a day the worker is marked Absent", b)

	def test_the_check_treats_it_as_must_fix(self):
		self.assertIn("\"absent_paid\": (\"block\" if frappe.db.sql(", source("payment"))


if __name__ == "__main__":
	unittest.main()
