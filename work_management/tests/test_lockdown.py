"""Writes are POST-only and need their capability (2026-11-12 lock-down).

The review found the rate tools, payment repair tools and payroll endpoints
callable by anyone logged in, and every write reachable from a plain link.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest work_management.tests.test_lockdown -v
"""

import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def source(module):
	with open(os.path.join(HERE, "api", module + ".py")) as handle:
		return handle.read()


def writes(module):
	m = re.search(r"WMG_WRITES = \{(.*?)\}", source(module), re.S)
	return dict(re.findall(r'"([a-z_]+)": "([a-z_]*)"', m.group(1)))


EXPECT = {
	"payment": {"pay_purge_queue": "repair_payments", "pay_recalc_wages": "repair_payments",
		"pay_round_amounts": "repair_payments", "pay_fix_orphan_refs": "repair_payments",
		"pay_release_inactive": "repair_payments", "pay_fix_unvalued": "repair_payments",
		"pay_bulk_withdraw": "send_payment", "pay_run_withdraw": "send_payment",
		"pay_worker_edit_day": "send_payment", "pay_worker_edit_days": "send_payment",
		"pay_bulk_submit": "send_payment", "pay_worker_submit": "send_payment"},
	"rates": {a: "set_rates" for a in ("apply_wage", "recalc", "classify", "backfill", "revert_periods",
		"sync_task_rates", "sync_planner_rates", "sync_doc_rates", "new_rate", "reverse")},
	"actuals": {a: "" for a in ("act_submit", "act_fm_approve", "act_gm_approve", "act_reject",
		"a_substitute", "act_close_confirm", "ws_delete_rejected")},
	"assigner": {a: "" for a in ("a_add_crew", "a_release", "a_substitute", "a_reject", "a_submit")},
	"masterplan": {"save": "edit_master_plan", "plans_bulk": "", "send_to_gm": "", "tl_save": ""},
	"planner": {a: "" for a in ("approve", "reject", "submit")},
}


class TestEveryWriteIsListed(unittest.TestCase):
	def test_each_write_names_its_capability(self):
		for module, want in EXPECT.items():
			got = writes(module)
			for action, cap in want.items():
				with self.subTest(module=module, action=action):
					self.assertEqual(got.get(action), cap)

	def test_each_module_refuses_a_get(self):
		for module in EXPECT:
			with self.subTest(module=module):
				src = source(module)
				self.assertIn('if frappe.request and frappe.request.method != "POST":', src)
				self.assertIn('elif WMG_DENY:\n        out["error"] = WMG_DENY', src)

	def test_payroll_tools_are_gated(self):
		for module in ("payroll", "payroll_recompute"):
			with self.subTest(module=module):
				src = source(module)
				self.assertIn('CAPABILITIES.get("repair_payments")', src)
				self.assertIn('frappe.request.method != "POST"', src)
		self.assertIn('in ("Paid", "Cancelled")', source("payroll"))

	def test_recompute_never_redecides_a_paid_row(self):
		self.assertIn('rc_skip["row already paid or sent"]', source("payroll_recompute"))


class TestTheScreensPostWhatTheServerCallsWrites(unittest.TestCase):
	def test_every_listed_write_is_posted(self):
		js = {name: open(os.path.join(HERE, "public", "js", name)).read()
			for name in ("work-payment.js", "work-planner.js", "work-actuals.js", "work-assigner.js")}
		screen_of = {"payment": "work-payment.js", "rates": "work-planner.js", "masterplan": "work-planner.js",
			"planner": "work-planner.js", "assigner": "work-assigner.js", "actuals": "work-actuals.js"}
		for module, screen in screen_of.items():
			text = js[screen]
			for action in writes(module):
				if action not in text:
					continue  # not called from that screen
				with self.subTest(module=module, action=action):
					self.assertRegex(text, r"\b" + action + r":1")


class TestTheCapability(unittest.TestCase):
	def test_patch_is_registered(self):
		with open(os.path.join(HERE, "patches.txt")) as handle:
			self.assertIn("work_management.patches.v1_0.seed_repair_payments_capability", handle.read())

	def test_the_settings_grid_offers_it(self):
		import json
		p = os.path.join(HERE, "work_management", "doctype", "work_management_capability",
			"work_management_capability.json")
		opts = [f for f in json.load(open(p))["fields"] if f["fieldname"] == "capability"][0]["options"]
		self.assertIn("Repair payments and pay rows", opts)


if __name__ == "__main__":
	unittest.main()


class TestFarmScope(unittest.TestCase):
	def block(self, module, action):
		src = source(module)
		start = src.index('    elif action == "' + action + '"')
		end = src.find("\n    elif action", start + 1)
		return src[start:end if end > 0 else len(src)]

	def test_crew_changes_check_the_assignments_farm(self):
		for action, verb in (("a_add_crew", "add a worker"), ("a_release", "release a worker"),
				("a_substitute", "swap a worker")):
			with self.subTest(action=action):
				self.assertIn("wmg_farm_err(", self.block("assigner", action))
		self.assertIn("wmg_farm_err(", self.block("actuals", "a_substitute"))

	def test_farm_managers_are_listed_per_farm(self):
		src = source("assigner")
		self.assertIn("def wmg_farm_err(farm, verb):", src)
		self.assertNotIn('"Farm Manager Saboti" in MY_ROLES: wmg_fm', src)  # ported to config

	def test_a_reject_is_gated_per_step(self):
		b = self.block("assigner", "a_reject")
		self.assertIn("Only the HR head (or the GM) can reject at this step.", b)
		self.assertIn("Only the GM can reject at this step.", b)

	def test_recording_work_needs_enter_work_or_the_farms_manager(self):
		b = self.block("actuals", "act_submit")
		self.assertIn('CAPABILITIES.get("enter_work")', b)
		self.assertIn('wmg_farm_err(sub_farm, "record work")', b)


class TestDeskRates(unittest.TestCase):
	def test_task_rate_edits_need_set_rates(self):
		with open(os.path.join(HERE, "hooks.py")) as handle:
			self.assertIn("work_management.rates.task_validate", handle.read())
		with open(os.path.join(HERE, "rates.py")) as handle:
			self.assertIn('capabilities.may("set_rates"', handle.read())

	def test_hr_manager_reads_rate_periods_only(self):
		import json
		p = os.path.join(HERE, "work_management", "doctype", "work_task_rate", "work_task_rate.json")
		hr = [x for x in json.load(open(p))["permissions"] if x["role"] == "HR Manager"][0]
		self.assertFalse(hr.get("write"))
		self.assertFalse(hr.get("create"))
