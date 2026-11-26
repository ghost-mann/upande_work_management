"""Assign the day before (2026-11-26): every way onto work asks a reason when late.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_assign_day_before_gate -v
"""

import os
import re
import types
import unittest

from work_management import assign_ahead as aa
from work_management.tests import mirror
from work_management.tests.test_one_worker_one_day import nested, source

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(HERE, "public", "js", "work-assigner.js")


def action(src, name):
	start = src.index('action == "' + name + '"')
	end = src.find("\n    elif action", start + 1)
	return src[start:len(src) if end < 0 else end]


def late_fn(check, form):
	calls = []

	def call(method, **kw):
		calls.append((method, kw))
		if method.endswith(".check"):
			return dict(check)
		return getattr(aa, method.rsplit(".", 1)[1])(**kw)
	scope = {"frappe": types.SimpleNamespace(call=call, form_dict=dict(form))}
	return nested("assigner", "wmg_late", scope), calls


class TestWmgLate(unittest.TestCase):
	LATE = {"late": 1, "deadline": "2026-11-26 18:00:00", "auto_reason": None}

	def test_on_time_passes(self):
		fn, _ = late_fn({"late": 0, "deadline": "x", "auto_reason": None}, {})
		lt = fn("2026-11-27", "PL-1")
		self.assertEqual((lt["ask"], lt["err"]), (0, ""))

	def test_late_without_reason_asks(self):
		fn, _ = late_fn(self.LATE, {})
		self.assertEqual(fn("2026-11-27", "PL-1")["ask"], 1)

	def test_late_with_reason_passes(self):
		fn, _ = late_fn(self.LATE, {"late_reason": "Weather"})
		lt = fn("2026-11-27", "PL-1")
		self.assertEqual((lt["ask"], lt["err"], lt["reason"]), (0, "", "Weather"))

	def test_other_needs_note(self):
		fn, _ = late_fn(self.LATE, {"late_reason": "Other"})
		self.assertTrue(fn("2026-11-27", "PL-1")["err"])

	def test_plan_approved_late_never_asks(self):
		fn, _ = late_fn(dict(self.LATE, auto_reason="Plan approved late"), {})
		lt = fn("2026-11-27", "PL-1")
		self.assertEqual((lt["ask"], lt["reason"]), (0, "Plan approved late"))

	def test_passes_the_planner(self):
		fn, calls = late_fn(self.LATE, {})
		fn("2026-11-27", "PL-9")
		self.assertEqual(calls[0], ("work_management.assign_ahead.check", {"start": "2026-11-27", "planner": "PL-9"}))


class TestEveryWayOntoWork(unittest.TestCase):
	def setUp(self):
		self.src = source("assigner")

	def test_each_action_checks(self):
		for name in ("a_submit", "a_add_crew", "a_substitute"):
			with self.subTest(action=name):
				body = action(self.src, name)
				self.assertIn("wmg_late(", body)
				self.assertIn('out["needs_late_reason"] = 1', body)
				self.assertIn("wmg_late_comment(", body)

	def test_submit_asks_only_for_new_records(self):
		body = action(self.src, "a_submit")
		self.assertIn("lt_new = 0", body)
		self.assertIn("if lt_new:", body)

	def test_submit_stores_the_reason(self):
		body = action(self.src, "a_submit")
		for f in ("d.late_assignment = 1", "d.late_reason = lt_info[\"reason\"]", "d.late_note = lt_info[\"note\"]"):
			self.assertIn(f, body)

	def test_late_asked_before_attendance(self):
		body = action(self.src, "a_submit")
		self.assertLess(body.index('out["needs_late_reason"] = 1'), body.index('out["needs_att_override"] = 1'))

	def test_add_for_payroll_check_not_asked_twice(self):
		body = action(self.src, "a_add_crew")
		self.assertRegex(body, r"if not err and not add_for:\s+ac_late = wmg_late\(")

	def test_pending_lists_late_fields(self):
		body = action(self.src, "a_pending")
		for f in ("late_assignment", "late_reason", "late_note"):
			self.assertIn('"' + f + '"', body)


class TestPlanApprovalTime(unittest.TestCase):
	def test_approve_stamps_the_time_and_reject_clears_it(self):
		src = source("planner")
		self.assertIn('"custom_approved_at", frappe.utils.now()', src)
		self.assertIn('"custom_approved_at", None', action(src, "reject"))


class TestScreen(unittest.TestCase):
	def setUp(self):
		with open(JS) as h:
			self.js = h.read()

	def test_reasons_match(self):
		m = re.search(r"var LATE_REASONS=\[([^\]]*)\]", self.js)
		self.assertTrue(m)
		self.assertEqual(re.findall(r'"([^"]+)"', m.group(1)), aa.REASONS)

	def test_all_three_calls_handle_the_ask(self):
		for name in ("a_submit", "a_add_crew", "a_substitute"):
			with self.subTest(action=name):
				i = self.js.index('action:"' + name + '"')
				self.assertIn("needs_late_reason", self.js[i:i + 1500])

	def test_late_pill_on_the_approval_table(self):
		self.assertIn("r.late_assignment", self.js)

	@unittest.skipUnless(mirror.present(mirror.WEB_PAGES), "mirror not checked out")
	def test_same_as_mirror(self):
		with open(os.path.join(mirror.WEB_PAGES, "work-assigner.js")) as h:
			self.assertEqual(h.read(), self.js)


if __name__ == "__main__":
	unittest.main()
