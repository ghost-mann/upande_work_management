"""Drive one document through the real screens' endpoints, on a real site.

The rest of this suite reads source and fakes frappe. That proves the code says
the right thing; it cannot prove that a transition written with
`frappe.db.set_value` reaches a Notification, or that a rejected entry can be
edited and sent back. Those are facts about Frappe's document machinery, and
only a site can answer them.

So this module calls `wm_masterplan`, `wm_planner`, `wm_assigner` and
`wm_actuals` exactly as the browser does -- `frappe.form_dict` filled in,
`frappe.session.user` set -- and returns what the screen would have been
handed. Nothing here writes a document directly except the masters a pipeline
needs (a rate, a block), and every test that uses it runs inside a transaction
that is rolled back.

Not a test module (no `test_` prefix): the suites that need it import it, and
skip when there is no site to run against.
"""

import json

import frappe


class SiteTestCase:
	"""Mixin: skip off a site, and leave the site exactly as it was found.

	The master plan endpoints call `frappe.db.commit()` themselves, mid-action,
	so a rollback at the end would leave every master plan a test raised sitting
	on the site. Commits are made no-ops for the duration and the whole test is
	rolled back instead."""

	def setUp(self):
		if not on_a_site():
			self.skipTest("needs a site: run with bench --site <site> run-tests")
		from unittest import mock

		self._no_commit = mock.patch.object(frappe.db, "commit", lambda *a, **k: None)
		self._no_commit.start()
		self.addCleanup(self._undo)

	def _undo(self):
		self._no_commit.stop()
		frappe.db.rollback()
		frappe.set_user("Administrator")

	def settings(self, **values):
		"""Change Work Management Settings for this test only (rolled back)."""
		for field, value in values.items():
			frappe.db.set_single_value("Work Management Settings", field, value)
		frappe.clear_cache(doctype="Work Management Settings")


def on_a_site():
	"""True under `bench run-tests` / `bench console`, False under bare unittest."""
	try:
		return bool(frappe.local.site) and bool(frappe.db)
	except Exception:
		return False


def call(fn, user="Administrator", **params):
	"""One request to a screen endpoint, as `user`. Returns its `out` dict."""
	before = frappe.session.user
	frappe.set_user(user)
	try:
		frappe.local.form_dict = frappe._dict()
		for key, value in params.items():
			if isinstance(value, (list, dict)):
				value = json.dumps(value)
			frappe.local.form_dict[key] = value
		return fn() or {}
	finally:
		frappe.set_user(before)


def endpoints():
	from work_management.api.actuals import wm_actuals
	from work_management.api.assigner import wm_assigner
	from work_management.api.masterplan import wm_masterplan
	from work_management.api.planner import wm_planner

	return frappe._dict(mp=wm_masterplan, pl=wm_planner, asg=wm_assigner, act=wm_actuals)


class Pipeline:
	"""Master plan -> plan -> assignment -> actuals for one farm and task.

	Every step asserts nothing; it returns the endpoint's answer and raises only
	when the endpoint itself reported an error, with that error as the message,
	so a failing test names the refusal the screen would have shown.
	"""

	def __init__(self, user="Administrator", from_date=None, days=3):
		self.user = user
		self.ep = endpoints()
		self.farm = frappe.get_all("Farm", pluck="name", limit=1)[0]
		self.from_date = from_date or frappe.utils.add_days(frappe.utils.today(), -7)
		self.to_date = frappe.utils.add_days(self.from_date, days - 1)
		self.task = self._task_with_a_rate()
		self.block = self._a_block()
		self.workers = frappe.get_all("Employee",
			filters={"status": "Active", "designation": "Task Worker"},
			pluck="name", order_by="name", limit=2)

	# ── masters ───────────────────────────────────────────────────────────
	def _task_with_a_rate(self):
		rated = frappe.db.sql("""
			SELECT task FROM `tabWork Task Rate`
			WHERE valid_from <= %(d)s AND IFNULL(daily_target,0) > 0 AND IFNULL(rate,0) > 0
			  AND (valid_to IS NULL OR valid_to >= %(d)s)
			ORDER BY task LIMIT 1""", {"d": self.from_date}, pluck=True)
		return rated[0]

	def _a_block(self):
		rows = frappe.get_all("Warehouse",
			filters={"custom_farm": self.farm, "is_group": 0, "disabled": 0},
			pluck="name", limit=1)
		return rows[0]

	def days(self):
		out, d = [], frappe.utils.getdate(self.from_date)
		while d <= frappe.utils.getdate(self.to_date):
			out.append(str(d))
			d = frappe.utils.add_days(d, 1)
		return out

	# ── steps ─────────────────────────────────────────────────────────────
	def _ok(self, out, what):
		if out.get("error"):
			raise AssertionError(what + " refused: " + str(out["error"]))
		return out

	def master_plan(self, submit=True, approve=True):
		out = self._ok(call(self.ep.mp, self.user, action="save", farm=self.farm,
			plan_name="Notify test " + frappe.generate_hash(length=5),
			period_from=frappe.utils.add_days(self.from_date, -1),
			period_to=frappe.utils.add_days(self.to_date, 30),
			activities=[{"task": self.task, "work_qty": 1000, "man_days": 50, "days": 30}]),
			"master plan save")
		self.mp = out.get("name")
		if submit:
			self._ok(call(self.ep.mp, self.user, action="submit_for_review", name=self.mp), "master plan submit")
		if submit and approve:
			self._ok(call(self.ep.mp, self.user, action="gm_approve", name=self.mp), "master plan approve")
		return self.mp

	def plan(self, submit=True, approve=True, quantity=12):
		out = self._ok(call(self.ep.pl, self.user, action="submit", farm=self.farm,
			blocks=self.block, task=self.task, quantity=quantity,
			from_date=self.from_date, to_date=self.to_date, master_plan=self.mp,
			submit_now=1 if submit else 0), "plan submit")
		self.pl = out.get("name")
		if submit and approve:
			self._ok(self.approve_plan(), "plan approve")
		return self.pl

	def approve_plan(self):
		return call(self.ep.pl, self.user, action="approve", name=self.pl, stage="planner_farm_approval")

	def assignment(self, submit=True, approve=True):
		out = self._ok(call(self.ep.asg, self.user, action="a_submit", planner=self.pl,
			employees=",".join(self.workers), submit_now=1 if submit else 0, att_override=1),
			"assignment submit")
		self.asg = out.get("name")
		if submit and approve and out.get("workflow_state") != "Assigned":
			self._ok(call(self.ep.asg, self.user, action="a_approve", name=self.asg,
				stage="assigner_farm_manager"), "assignment approve")
		return self.asg

	def actuals_rows(self, qty=2):
		return "|".join(w + "~" + d + "~" + str(qty) for w in self.workers for d in self.days())

	def actuals(self, submit=True, edit_doc=None, qty=2, rows=None, att_override=1, check=True):
		params = dict(action="act_submit", assignment=self.asg,
			rows=rows if rows is not None else self.actuals_rows(qty),
			submit_now=1 if submit else 0, att_override=att_override)
		if edit_doc:
			params["edit_doc"] = edit_doc
		out = call(self.ep.act, self.user, **params)
		if check:
			self._ok(out, "actuals submit")
		self.act = out.get("name") or edit_doc
		return out

	def state(self, doctype, name):
		return frappe.db.get_value(doctype, name, "workflow_state")
