"""One worker, one day, one task (2026-11-12).

Live held 962 worker-days paid on two actuals. 238 of the rows since 1 Oct
belonged to a worker marked Left on the other assignment: being released took
them out of the busy check, but their days there were still recorded, and the
new assignment over the same dates paid those days again.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_one_worker_one_day -v
"""

import datetime
import os
import re
import textwrap
import types
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def source(module):
	with open(os.path.join(HERE, "api", module + ".py")) as handle:
		return handle.read()


def nested(module, name, scope):
	"""A helper defined inside a ported wm_x() body, dedented and exec'd."""
	src = source(module)
	start = src.index("    def " + name + "(")
	end = src.index("\n    def ", start + 1) if "\n    def " in src[start + 1:] else None
	nxt = re.search(r"\n    (?!\s|def )\S", src[start + 1:])
	stop = start + 1 + nxt.start() if nxt else len(src)
	if end is not None and end < stop:
		stop = end
	exec(textwrap.dedent(src[start:stop]), scope)
	return scope[name]


TODAY = "2026-11-12"


def fake_frappe(form=None):
	utils = types.SimpleNamespace(
		today=lambda: TODAY,
		add_days=lambda d, n: str(datetime.date.fromisoformat(str(d)) + datetime.timedelta(days=n)),
	)
	return types.SimpleNamespace(utils=utils, form_dict=dict(form or {}))


def backdate(gm, form=None, days=7):
	scope = {"frappe": fake_frappe(form), "WMG_BACKDATE_DAYS": days, "WMG_GM": gm}
	return nested("assigner", "wmg_backdate_err", scope)


class TestBusyIncludesReleasedWorkers(unittest.TestCase):
	"""Every busy-elsewhere query bounds a worker by their own window on the other
	assignment -- start to left_date -- and never by being Active."""

	def busy_queries(self, module):
		src = source(module)
		return [m.group(0) for m in re.finditer(
			r"FROM `tabWork Assignment Employee` we\s+INNER JOIN `tabWork Management Assigner` a"
			r"[\s\S]{0,700}?a\.name != %s[\s\S]{0,500}?\"\"\"", src)]

	def test_left_worker_still_blocks_their_dates(self):
		for module in ("assigner", "actuals"):
			queries = self.busy_queries(module)
			self.assertTrue(queries, module)
			for q in queries:
				with self.subTest(module=module):
					self.assertNotIn("IFNULL(we.status,'Active') = 'Active'", q)
					self.assertIn("COALESCE(we.start_date, a.from_date) <= %s", q)
					# ...up to the left date, but never past the assignment's own end
					self.assertIn("THEN we.left_date END, a.to_date), a.to_date) >= %s", q)

	def test_a_substitute_is_bounded_by_the_replacements_start(self):
		for module in ("assigner", "actuals"):
			with self.subTest(module=module):
				self.assertIn("str(start_date) if start_date and str(start_date) > str(rdates.from_date)",
					source(module))

	def test_no_refusal_offers_the_split_day_switch(self):
		self.assertNotIn("Allow a worker's day to be split", source("assigner"))


class TestBackdating(unittest.TestCase):
	def test_recent_start_passes(self):
		self.assertEqual(backdate(0)("2026-11-05"), "")

	def test_backdate_refused_for_clerk(self):
		self.assertIn("Ask the GM", backdate(0)("2026-09-28"))

	def test_gm_needs_a_reason(self):
		self.assertIn("Give a reason", backdate(1)("2026-09-28"))

	def test_backdate_allowed_for_gm_with_reason(self):
		self.assertEqual(backdate(1, {"backdate_reason": "late paperwork"})("2026-09-28"), "")

	def test_every_way_onto_work_checks_it(self):
		src = source("assigner")
		for action in ("a_submit", "a_add_crew", "a_substitute"):
			start = src.index('action == "' + action + '"')
			end = src.find("\n    elif action", start + 1)
			end = len(src) if end < 0 else end
			with self.subTest(action=action):
				self.assertIn("wmg_backdate_err(", src[start:end])
				self.assertIn("wmg_log_backdate(", src[start:end])


if __name__ == "__main__":
	unittest.main()


class Row(dict):
	__getattr__ = dict.get


class SqlFake:
	"""frappe.db.sql that answers from a list of rows and records the query."""

	def __init__(self, rows):
		self.rows = [Row(r) for r in rows]
		self.queries = []

	def __call__(self, query, args=None, as_dict=False):
		self.queries.append((query, args))
		return list(self.rows)


def guard_scope(rows, assignment=None):
	sql = SqlFake(rows)
	db = types.SimpleNamespace(sql=sql,
		get_value=lambda dt, name, fields=None, as_dict=False: Row(assignment or {}))
	scope = {"frappe": types.SimpleNamespace(db=db), "WMG_PC_DT": 1}
	return scope, sql


class TestTheDayClash(unittest.TestCase):
	def clashes(self, rows, pairs, exclude="WMAC-1"):
		scope, sql = guard_scope(rows)
		fn = nested("actuals", "wmg_day_clashes", scope)
		return fn(pairs, exclude), sql.queries[0]

	def test_clash_ignores_task_and_assignment(self):
		hits, (query, args) = self.clashes(
			[{"emp": "401151", "d": "2026-11-02", "doc": "WMAC-2", "task": "TASK-2026-00176",
			  "farm": "Endebess", "state": "CONFIRMED"}],
			[("401151", "2026-11-02")])
		self.assertIn(("401151", "2026-11-02"), hits)
		self.assertNotIn("ac.task =", query)
		self.assertNotIn("ac.assignment !=", query)

	def test_clash_excludes_own_doc(self):
		_, (query, args) = self.clashes([], [("401151", "2026-11-02")], exclude="WMAC-9")
		self.assertIn("ac.name != %s", query)
		self.assertEqual(args[0], "WMAC-9")

	def test_drafts_and_pending_count_but_rejected_and_zeroed_do_not(self):
		_, (query, _) = self.clashes([], [("401151", "2026-11-02")])
		self.assertIn("IFNULL(ac.workflow_state, '') != 'Rejected'", query)
		self.assertIn("(IFNULL(we.actual_quantity, 0) > 0 OR IFNULL(we.amount, 0) > 0)", query)

	def test_another_date_is_not_a_clash(self):
		hits, _ = self.clashes(
			[{"emp": "401151", "d": "2026-11-03", "doc": "WMAC-2", "task": "T", "farm": "E", "state": "Draft"}],
			[("401151", "2026-11-02")])
		self.assertEqual(hits, {})


class TestTheWorkersOwnWindow(unittest.TestCase):
	def off(self, crew, pairs):
		scope, sql = guard_scope(crew, {"from_date": "2026-09-28", "to_date": "2026-10-11"})
		return nested("actuals", "wmg_off_assignment", scope)("WMA-863710", pairs)

	def test_days_after_leaving_are_refused(self):
		crew = [{"employee": "E1", "start_date": None, "left_date": "2026-10-03", "status": "Left"}]
		self.assertEqual(self.off(crew, [("E1", "2026-10-03"), ("E1", "2026-10-04")]),
			[("E1", "2026-10-04")])

	def test_days_before_joining_are_refused(self):
		crew = [{"employee": "E2", "start_date": "2026-10-05", "left_date": None, "status": "Active"}]
		self.assertEqual(self.off(crew, [("E2", "2026-10-04"), ("E2", "2026-10-05")]),
			[("E2", "2026-10-04")])

	def test_someone_not_on_the_crew_is_refused(self):
		self.assertEqual(self.off([], [("E3", "2026-10-01")]), [("E3", "2026-10-01")])

	def test_released_and_added_back_counts_either_window(self):
		crew = [{"employee": "E4", "start_date": None, "left_date": "2026-09-30", "status": "Left"},
			{"employee": "E4", "start_date": "2026-10-06", "left_date": None, "status": "Active"}]
		self.assertEqual(self.off(crew, [("E4", "2026-09-29"), ("E4", "2026-10-02"), ("E4", "2026-10-07")]),
			[("E4", "2026-10-02")])


class TestEveryStepRechecks(unittest.TestCase):
	def block(self, action):
		src = source("actuals")
		start = src.index('    elif action == "' + action + '"')
		end = src.find("\n    elif action", start + 1)
		return src[start:end]

	def test_approve_rechecks(self):
		for action in ("act_fm_approve", "act_hr_approve", "act_gm_approve"):
			with self.subTest(action=action):
				self.assertIn("wmg_doc_err(nm)", self.block(action))

	def test_saving_refuses_without_override(self):
		block = self.block("act_submit")
		self.assertIn("wmg_guard_err(", block)
		self.assertNotIn("double pay\")", block)
		at = block.index("if wmg_err:")
		self.assertIn('out["error"] = wmg_err', block[at:at + 80])

	def test_reject_respects_the_lock(self):
		self.assertIn("wmg_locked(", self.block("act_reject"))

	def test_an_early_close_confirms_only_clean_records(self):
		self.assertIn("wmg_doc_err(ar.nm)", self.block("act_close_confirm"))

	def test_week_signoff_actions_gone(self):
		src = source("actuals")
		for gone in ('"ws_meta"', '"ws_week"', '"ws_signoff"', '"ws_reopen"', "Week Signoff"):
			with self.subTest(gone=gone):
				self.assertNotIn(gone, src)
		for kept in ('"ws_notify"', '"ws_delete_rejected"', '"hist_people"'):
			with self.subTest(kept=kept):
				self.assertIn(kept, src)


class TestTheDeskSaveHook(unittest.TestCase):
	def test_it_is_wired(self):
		with open(os.path.join(HERE, "hooks.py")) as handle:
			self.assertIn("work_management.duplicate_guard.validate_actuals", handle.read())

	def test_it_refuses_a_clash(self):
		import sys
		fake = types.ModuleType("frappe")
		thrown = []

		class Stop(Exception):
			pass

		def throw(msg, title=None):
			thrown.append(msg)
			raise Stop(msg)

		fake.throw = throw
		fake._ = lambda s: s
		fake.db = types.SimpleNamespace(sql=lambda q, a: [("401151", "2026-11-02", "WMAC-2")])
		saved = sys.modules.get("frappe")
		sys.modules["frappe"] = fake
		try:
			import importlib
			import work_management.duplicate_guard as guard
			importlib.reload(guard)
			doc = Row(name="WMAC-1", docstatus=0, workflow_state="Draft",
				flags=Row(wm_screen=1),
				employees=[Row(employee="401151", work_date="2026-11-02", actual_quantity=1, amount=387)])
			doc.get = lambda k, d=None: dict.get(doc, k, d)
			with self.assertRaises(Stop):
				guard.validate_actuals(doc)
			self.assertIn("WMAC-2", thrown[0])
		finally:
			if saved is not None:
				sys.modules["frappe"] = saved
			else:
				del sys.modules["frappe"]
