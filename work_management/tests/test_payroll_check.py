"""The payroll check: who keeps a duplicate day, the payment gate, the
paid-stamp fix, and what send-back and overlap do.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_payroll_check -v
"""

import os
import re
import types
import unittest

import textwrap

from work_management.tests.test_one_worker_one_day import Row, source


def defined(module, name):
	"""The text of a helper defined at any depth inside a ported module."""
	src = source(module)
	m = re.search(r"\n([ \t]*)def " + name + r"\(", src)
	indent = len(m.group(1))
	lines = src[m.start() + 1:].split("\n")
	body = [lines[0]]
	for line in lines[1:]:
		if line.strip() and (len(line) - len(line.lstrip())) <= indent:
			break
		body.append(line)
	return textwrap.dedent("\n".join(body))


def nested(module, name, scope):
	exec(defined(module, name), scope)
	return scope[name]


def utils():
	return types.SimpleNamespace(cint=lambda v: int(v or 0), flt=lambda v: float(v or 0))


def keeper():
	return nested("payment", "wmpc_keeper", {"frappe": types.SimpleNamespace(utils=utils())})


def block(action):
	src = source("payment")
	start = src.index('    elif action == "' + action + '"')
	end = src.find("\n    elif action", start + 1)
	return src[start:end]


class TestWhoKeepsTheDay(unittest.TestCase):
	def test_keeper_is_first_assignment(self):
		"""Decision 2: the old assignment keeps the days already worked."""
		a = Row(row="r-new", asg_start="2026-09-28", asg_created="2026-10-23", ac_created="2026-10-24")
		b = Row(row="r-old", asg_start="2026-09-28", asg_created="2026-09-28", ac_created="2026-09-29")
		c = Row(row="r-late", asg_start="2026-10-01", asg_created="2026-09-01", ac_created="2026-09-01")
		self.assertEqual(keeper()([a, c, b])["row"], "r-old")

	def test_a_paid_copy_is_always_kept(self):
		a = Row(row="r-first", asg_start="2026-09-01", asg_created="2026-09-01", ac_created="2026-09-01")
		b = Row(row="r-paid", asg_start="2026-10-01", asg_created="2026-10-01", ac_created="2026-10-01",
			paid=1, payment_ref="WMPAY-1")
		self.assertEqual(keeper()([a, b])["row"], "r-paid")

	def test_a_copy_without_an_assignment_ranks_last(self):
		a = Row(row="r-none", ac_created="2026-09-01")
		b = Row(row="r-asg", asg_start="2026-10-01", asg_created="2026-10-01", ac_created="2026-10-02")
		self.assertEqual(keeper()([a, b])["row"], "r-asg")


class TestTheGate(unittest.TestCase):
	def test_checked_only_replaces_signed_only(self):
		src = source("payment")
		self.assertNotIn("SIGNED_ONLY", src)
		self.assertNotIn("Week Signoff", src)
		self.assertGreaterEqual(src.count("+ CHECKED_ONLY"), 8)
		self.assertIn("pchk.status IN ('Approved', 'Sent')", src)

	def test_the_gate_follows_the_setting(self):
		self.assertIn("field = 'payroll_check_required'", source("payment"))

	def test_a_finished_check_turns_sent(self):
		src = source("payment")
		at = src.index('action in ("pay_submit", "pay_worker_submit", "pay_bulk_submit")')
		self.assertIn('"status": "Sent"', src[at:at + 900])


class TestThePaidStamp(unittest.TestCase):
	"""_stamp_actuals_paid_for_payment stamps the rows the run carried, not every
	unpaid row its workers have in the period (the 2 Nov audit bug)."""

	def stamp(self, carried, lines=(), fallback=()):
		src = source("payment")
		start = src.index("def _stamp_actuals_paid_for_payment(")
		end = src.index("\ndef ", start + 1)
		stamped = []
		sql_calls = []

		def sql(query, args=None, as_dict=False):
			sql_calls.append(query)
			if "we.payment_ref = %s" in query:
				return [Row(r) for r in carried]
			if "we.parent = %s AND we.employee = %s" in query:
				return [Row(r) for r in fallback]
			if "COUNT(*) c" in query:
				return [Row(c=1)]
			return []

		meta = types.SimpleNamespace(fields=[types.SimpleNamespace(fieldtype="Table", fieldname="lines",
			options="Work Payment Line")])
		fake = types.SimpleNamespace(
			db=types.SimpleNamespace(
				get_value=lambda dt, n, f, as_dict=False: Row(period_from="2026-10-21", period_to="2026-10-27"),
				get_all=lambda dt, filters=None, fields=None: [Row(l) for l in lines],
				sql=sql,
				set_value=lambda dt, n, f, v, update_modified=False: stamped.append((n, f, v))),
			get_meta=lambda dt: meta)
		scope = {"frappe": fake}
		exec(src[start:end], scope)
		scope["_stamp_actuals_paid_for_payment"]("WMPAY-9")
		return stamped, sql_calls

	def test_stamp_uses_the_rows_the_run_carried(self):
		stamped, calls = self.stamp([{"rowname": "row-a", "parent": "WMAC-1"}])
		self.assertIn(("row-a", "paid", 1), stamped)
		self.assertFalse([q for q in calls if "we.employee=%s AND ac.workflow_state" in q],
			"the worker-wide sweep is back")

	def test_legacy_run_falls_back_to_its_lines_actuals(self):
		stamped, calls = self.stamp([], lines=[{"employee": "E1", "actuals": "WMAC-1",
			"work_from": "2026-10-21", "work_to": "2026-10-27"}],
			fallback=[{"rowname": "row-b", "parent": "WMAC-1"}])
		self.assertIn(("row-b", "paid", 1), stamped)

	def test_a_line_without_actuals_stamps_nothing(self):
		stamped, _ = self.stamp([], lines=[{"employee": "E1", "actuals": None}])
		self.assertEqual(stamped, [])


class TestTheCheckActions(unittest.TestCase):
	def test_send_back_unstamps_only_unsent(self):
		body = defined("payment", "wmpc_unstamp")
		self.assertIn("payroll_check = %s AND IFNULL(payment_ref, '') = ''", body)
		self.assertIn("wmpc_unstamp(pc)", block("chk_send_back"))

	def test_overlap_refused_except_top_up(self):
		b = block("chk_create")
		self.assertIn("is_top_up = 0 AND period_from <= %s AND period_to >= %s", b)
		self.assertIn("if not cerr and not ctop:", b)
		self.assertIn("must sit inside the dates of one check already sent", b)

	def test_a_farm_approval_is_blocked_by_its_own_problems(self):
		b = block("chk_farm_approve")
		self.assertIn("wmpc_duplicates(pc.period_from, pc.period_to, af)", b)
		self.assertIn("wmpc_unfinished(pc.period_from, pc.period_to, af)", b)
		self.assertIn("SET we.payroll_check = %(c)s", b)

	def test_hr_and_gm_are_blocked_by_every_problem(self):
		b = block("chk_hr_approve")
		self.assertIn("wmpc_duplicates(pc.period_from, pc.period_to, None)", b)

	def test_only_unstamped_unpaid_rows_join_a_check(self):
		body = defined("payment", "wmpc_payable_conds")
		for clause in ("IFNULL(we.payroll_check, '') = ''", "IFNULL(we.paid, 0) = 0",
				"IFNULL(we.payment_ref, '') = ''", "ac.workflow_state = 'CONFIRMED'"):
			with self.subTest(clause=clause):
				self.assertIn(clause, body)

	def test_a_paid_copy_is_never_zeroed(self):
		self.assertIn("That copy is already paid; zero the other one.", block("chk_fix_dup"))

	def test_cross_farm_duplicates_belong_to_hr(self):
		src = source("payment")
		self.assertIn('owner = g[0].farm if len(farms_in) == 1 else "HR"', src)
		self.assertIn("A duplicate across two farms is for HR to fix.", block("chk_fix_dup"))


if __name__ == "__main__":
	unittest.main()


class TestReviewFixes(unittest.TestCase):
	"""Final-review findings, 2026-11-12."""

	def test_a_part_sent_check_can_be_closed(self):
		b = block("chk_close_sent")
		self.assertIn("wmpc_unstamp(pc)", b)
		self.assertIn('"status": "Sent"', b)
		self.assertIn("pc_reason", b)

	def test_paid_twice_means_paid_not_merely_sent(self):
		src = defined("payment", "wmpc_duplicates")
		self.assertIn('"paid_twice": 1 if npaid_settled > 1 else 0', src)

	def test_a_copy_already_in_a_run_points_hr_to_withdraw_it(self):
		self.assertIn("withdraw that run on Awaiting accounts", block("chk_fix_dup"))

	def test_the_gm_cannot_approve_what_they_approved_for_hr(self):
		b = block("chk_hr_approve")
		self.assertIn("pc.hr_approved_by == frappe.session.user", b)

	def test_empty_drafts_do_not_block(self):
		src = defined("payment", "wmpc_unfinished")
		self.assertIn("IFNULL(w0.actual_quantity, 0) > 0 OR IFNULL(w0.amount, 0) > 0", src)

	def test_a_farm_manager_sees_only_their_farm(self):
		b = block("chk_detail")
		self.assertIn("fscope = pc_fm[0]", b)
		self.assertIn("out[\"fixes\"] = [x for x in out[\"fixes\"] if x.farm in pc_fm]", b)

	def test_reject_refuses_a_record_in_a_run(self):
		src = source("actuals")
		start = src.index('    elif action == "act_reject"')
		b = src[start:src.find("\n    elif action", start + 1)]
		self.assertIn("IFNULL(payment_ref, '') != ''", b)

	def test_editing_a_pending_assignment_is_not_backdating(self):
		src = source("assigner")
		self.assertIn("if not err and planner and not asg_name:", src)


class TestTheListShowsWhatCanBeSent(unittest.TestCase):
	def test_payable_column_obeys_the_gate(self):
		"""e2e 2026-11-12: with the gate on, Pay workers (include_all) showed 11,739
		KES payable for dates no check covered; the send would have refused it."""
		self.assertIn("THEN we.amount ELSE 0 END),0) payable_amt", block("pay_workers"))
		self.assertIn("IFNULL(we.payment_ref,'')=''\"\"\" + CHECKED_ONLY + \"\"\" THEN we.amount ELSE 0 END),0) payable_amt",
			block("pay_workers"))
