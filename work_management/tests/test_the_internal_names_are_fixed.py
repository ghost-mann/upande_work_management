# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""A step's workflow state and action are internal and fixed; its label is not.

A document carries its workflow state BY NAME. On Altura, relabelling the
Actuals "FM" step meant typing new words into the grid's "Waits In" and "Action"
columns, the regenerated workflow no longer held the state nineteen actuals sat
in, and they vanished from every queue. Every deploy then reset those columns
(seed_stages) and stranded whatever had moved in the meantime.

On this branch:

    the catalogue holds ALTURA's names, by stage key, and seed_stages() writes
        them on every migrate -- which is now what keeps them fixed
    Settings cannot change them: the columns are read-only and
        fix_stage_names() puts them back on any save
    an added step is given a key, state and action once, at insert
    a migrate that changes nothing saves nothing (Settings or Workflow)
    deleting a step with documents in it is refused like switching it off
    the documents already waiting under the old names are moved by
        rescue_documents_in_renamed_states, in the same transaction as the
        workflows are rebuilt

    bench --site <site> run-tests --app work_management \\
        --module work_management.tests.test_the_internal_names_are_fixed
"""

import json
import os
import unittest
from unittest import mock

import frappe

from work_management import approvals, stage_pills
from work_management.patches.v1_0 import rescue_documents_in_renamed_states as rescue
from work_management.tests import altura

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACT = "Work Management Actuals"
ASG = "Work Management Assigner"
MP = "Work Management Master Plan"

#: The addendum's catalogue, 25 Sep: stage key -> (Waits In, Action).
ALTURA = {
	"masterplan_submit": ("Draft", "Send for Review"),
	"masterplan_consultant": ("Pending Consultant", "Send to GM"),
	"masterplan_gm": ("Pending Manager", "Manager Approve"),
	"planner_submit": ("Draft", "Submit for Approval"),
	"planner_farm_approval": ("Pending Approval", "Approve"),
	"planner_hr_approval": ("Pending HR Approval", "HR Approve"),
	"assigner_submit": ("Draft", "Submit for Approval"),
	"assigner_farm_manager": ("Pending Manager", "Approve"),
	"assigner_hr_head": ("Pending HR Head", "HR Approve"),
	"assigner_gm": ("Pending GM", "GM Approve"),
	"actuals_submit": ("Draft", "Submit for Approval"),
	"actuals_farm_manager": ("Pending Approval", "Approve"),
	"actuals_hr_head": ("Pending Manager", "Approve"),
	"actuals_gm": ("Pending GM", "GM Approve"),
	"payment_accounts": ("Unpaid", "Mark Paid"),
}


def read(*parts):
	with open(os.path.join(APP, *parts), encoding="utf-8") as handle:
		return handle.read()


def rows(**changes):
	"""Altura-shaped stage rows as frappe._dicts, with per-key overrides."""
	out = []
	for r in altura.rows():
		row = frappe._dict(dict(r))
		row.update(changes.get(row.stage, {}))
		out.append(row)
	return out


class Stored:
	"""A Settings doc with a stored version behind it."""

	def __init__(self, stage_rows, before=None):
		self.approval_stages = stage_rows
		self.stage_approvers = []
		self._before = before
		self.flags = frappe._dict()

	def get(self, key, default=None):
		return getattr(self, key, default)

	def get_doc_before_save(self):
		return self._before


class TestTheCatalogueIsAlturas(unittest.TestCase):
	def test_every_step_has_the_addendum_s_names(self):
		for stage in approvals.CATALOGUE:
			with self.subTest(step=stage.key):
				self.assertEqual((stage.state, stage.action), ALTURA[stage.key])

	def test_the_chain_ends_are_unchanged(self):
		self.assertEqual({dt: e["terminal"][0] for dt, e in approvals.CHAIN_ENDS.items()}, {
			MP: "Approved", "Work Management Planner": "Approved", ASG: "Assigned",
			ACT: "CONFIRMED", "Work Management Payment": "Paid"})

	def test_no_workflow_has_one_state_twice(self):
		"""`Pending Manager` is shared ACROSS three doctypes -- never within one."""
		for dt in approvals.CHAIN_ENDS:
			states = [s.state for s in approvals.CATALOGUE if s.document_type == dt
				and s.kind == "Approval"]
			with self.subTest(document_type=dt):
				self.assertEqual(len(states), len(set(states)))

	def test_the_masters_ship(self):
		states = {r["name"] for r in json.loads(read("fixtures", "workflow_state.json"))}
		actions = {r["name"] for r in json.loads(read("fixtures", "workflow_action_master.json"))}
		self.assertIn("Pending Manager", states)
		self.assertTrue({"Send for Review", "Manager Approve", "Approve"} <= actions)
		hooks = read("hooks.py")
		for name in ("Pending Manager", "Send for Review", "Manager Approve"):
			self.assertIn('"%s"' % name, hooks)


class TestSettingsCannotRenameAState(unittest.TestCase):
	def test_the_columns_are_read_only_in_the_grid(self):
		path = ("work_management", "doctype", "work_management_approval_stage",
			"work_management_approval_stage.json")
		fields = {f["fieldname"]: f for f in json.loads(read(*path))["fields"]}
		self.assertTrue(fields["state"].get("read_only"))
		self.assertTrue(fields["action"].get("read_only"))
		self.assertFalse(fields["stage_label"].get("read_only"))
		self.assertFalse(fields["role"].get("read_only"))
		self.assertFalse(fields["enabled"].get("read_only"))

	def test_relabelling_the_supervisor_changes_only_the_label(self):
		"""The Altura incident: label, state and action all typed over."""
		edited = rows(actuals_farm_manager={"stage_label": "Actuals: Foreman",
			"state": "Pending Foreman", "action": "Foreman Approve"})
		approvals.fix_stage_names(Stored(edited, Stored(rows())))
		row = [r for r in edited if r.stage == "actuals_farm_manager"][0]
		self.assertEqual((row.stage_label, row.state, row.action),
			("Actuals: Foreman", "Pending Approval", "Approve"))

	def test_role_and_on_stay_editable(self):
		edited = rows(actuals_hr_head={"role": "Somebody Else", "enabled": 0})
		approvals.fix_stage_names(Stored(edited))
		row = [r for r in edited if r.stage == "actuals_hr_head"][0]
		self.assertEqual((row.role, row.enabled), ("Somebody Else", 0))

	def test_a_relabelled_chain_generates_the_same_workflow(self):
		"""Documents in `Pending Approval` stay in a state their workflow has."""
		plain = approvals.plan_workflow(ACT, settings=altura.settings())
		relabelled = altura.settings()
		for r in relabelled["approval_stages"]:
			r["stage_label"] = "Renamed " + r["stage_label"]
		after = approvals.plan_workflow(ACT, settings=relabelled)
		self.assertEqual(plain["states"], after["states"])
		self.assertEqual(plain["transitions"], after["transitions"])

	def test_the_pill_shows_the_new_label_and_the_button_reads_approve(self):
		relabelled = altura.settings()
		for r in relabelled["approval_stages"]:
			if r["stage"] == "actuals_farm_manager":
				r["stage_label"] = "Actuals: Foreman"
		steps = [s for s in approvals.effective_chain(relabelled) if s["document_type"] == ACT]
		pill = [p for p in stage_pills.build(steps, {"Pending Approval": 19})
			if p["key"] == "actuals_farm_manager"][0]
		self.assertEqual((pill["label"], pill["state"], pill["action"], pill["count"]),
			("Actuals: Foreman", "Pending Approval", "Approve", 19))


class TestAnAddedStepIsNamedOnce(unittest.TestCase):
	def added(self, **extra):
		row = frappe._dict({"stage": "", "stage_label": "Actuals: Finance",
			"document_type": ACT, "kind": "Approval", "state": "", "action": "",
			"enabled": 1, "role": "Accounts User"})
		row.update(extra)
		return row

	def test_it_is_given_a_key_state_and_action(self):
		new = self.added()
		approvals.fix_stage_names(Stored(rows() + [new]))
		self.assertEqual((new.stage, new.state, new.action),
			("custom_actuals_finance", "Pending Finance", "Approve"))

	def test_renaming_it_later_changes_only_the_label(self):
		new = self.added()
		approvals.fix_stage_names(Stored(rows() + [new]))
		stored = frappe._dict(dict(new))
		again = frappe._dict(dict(new, stage_label="Actuals: Treasury",
			state="Pending Treasury", action="Treasury Approve"))
		approvals.fix_stage_names(Stored(rows() + [again], Stored(rows() + [stored])))
		self.assertEqual((again.stage, again.state, again.action),
			("custom_actuals_finance", "Pending Finance", "Approve"))

	def test_its_state_does_not_collide_within_its_document(self):
		new = self.added(stage_label="Actuals: Approval")
		approvals.fix_stage_names(Stored(rows() + [new]))
		self.assertEqual(new.state, "Pending Approval 2")

	def test_its_key_does_not_collide(self):
		one, two = self.added(), self.added()
		approvals.fix_stage_names(Stored(rows() + [one, two]))
		self.assertEqual((one.stage, two.stage),
			("custom_actuals_finance", "custom_actuals_finance_2"))


class TestAMigrateThatChangesNothingSavesNothing(unittest.TestCase):
	def test_the_seed_does_not_save_settings_already_right(self):
		settings = mock.MagicMock()
		settings.get.return_value = [frappe._dict(r) for r in altura.rows()]
		approvals.seed_stages(settings=settings)
		settings.save.assert_not_called()
		settings.set.assert_not_called()

	def test_the_seed_puts_the_catalogue_back_and_keeps_the_rest(self):
		changed = [frappe._dict(dict(r)) for r in altura.rows()]
		for r in changed:
			if r.stage == "actuals_farm_manager":
				r.update(state="Pending Farm Manager", action="FM Approve",
					stage_label="Actuals: Supervisor", role="Somebody", enabled=1)
		settings = mock.MagicMock()
		settings.get.return_value = changed
		approvals.seed_stages(settings=settings, save=False)
		written = [c.args[1] for c in settings.append.call_args_list
			if c.args[1]["stage"] == "actuals_farm_manager"][0]
		self.assertEqual((written["state"], written["action"], written["stage_label"],
			written["role"]), ("Pending Approval", "Approve", "Actuals: Supervisor", "Somebody"))

	def test_a_workflow_already_matching_its_plan_compares_equal(self):
		plan = approvals.plan_workflow(ACT, settings=altura.settings())
		workflow = frappe._dict({
			"document_type": ACT, "workflow_state_field": "workflow_state",
			"is_active": 1, "override_status": 0, "send_email_alert": 0,
			"states": [frappe._dict(s, doc_status=str(s["doc_status"])) for s in plan["states"]],
			"transitions": [frappe._dict(t) for t in plan["transitions"]],
		})
		self.assertEqual(approvals._workflow_as(workflow), approvals._plan_as(plan, ACT, False))
		workflow.transitions[0].next_state = "Somewhere else"
		self.assertNotEqual(approvals._workflow_as(workflow), approvals._plan_as(plan, ACT, False))

	def test_build_workflows_skips_the_save_when_equal(self):
		src = read("approvals.py")
		at = src.index("def build_workflows(")
		block = src[at:src.index("def _plan_as(", at)]
		self.assertIn("if _workflow_as(workflow) == _plan_as(plan, document_type, notify):", block)
		self.assertLess(block.index("_workflow_as(workflow) =="), block.index("workflow.save()"))


class TestAFreshSiteGetsTheCatalogue(unittest.TestCase):
	def test_an_empty_table_is_seeded_with_altura_s_names(self):
		settings = mock.MagicMock()
		settings.get.return_value = []
		approvals.seed_stages(settings=settings, save=False)
		written = {c.args[1]["stage"]: c.args[1] for c in settings.append.call_args_list}
		self.assertEqual(set(written), set(ALTURA))
		for key, (state, action) in ALTURA.items():
			with self.subTest(step=key):
				self.assertEqual((written[key]["state"], written[key]["action"]), (state, action))
		self.assertEqual(written["planner_hr_approval"]["enabled"], 0)  # default_off

	def test_its_workflows_hold_those_states(self):
		settings = frappe._dict({"approval_stages": [], "stage_approvers": []})
		plan = approvals.plan_workflow(ACT, settings=settings)
		self.assertEqual([s["state"] for s in plan["states"]],
			["Draft", "Pending Approval", "Pending Manager", "Pending GM", "CONFIRMED", "Rejected"])


class TestABusyStepCannotBeStranded(unittest.TestCase):
	def run_guard(self, after_rows):
		before = Stored(rows())
		settings = Stored(after_rows, before)

		def throw(message, title=None):
			raise frappe.ValidationError(message)

		with mock.patch.object(approvals, "_waiting_in", side_effect=lambda dt, st: 19
					if (dt, st) == (ACT, "Pending Manager") else 0), \
				mock.patch.object(approvals, "_", side_effect=lambda t: t), \
				mock.patch.object(approvals.frappe, "bold", side_effect=lambda t: t), \
				mock.patch.object(approvals.frappe, "throw", side_effect=throw):
			approvals.validate_switching_off(settings)

	def test_switching_off_the_manager_with_19_waiting_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			self.run_guard(rows(actuals_hr_head={"enabled": 0}))
		self.assertIn("19", str(caught.exception))
		self.assertIn("Actuals: Manager", str(caught.exception))

	def test_deleting_it_is_refused_too(self):
		with self.assertRaises(frappe.ValidationError):
			self.run_guard([r for r in rows() if r.stage != "actuals_hr_head"])

	def test_an_idle_step_may_go(self):
		self.run_guard(rows(actuals_farm_manager={"enabled": 0}))


class TestTheDispatchersReadTheChain(unittest.TestCase):
	"""No state list is spelled out on the server any more."""

	GROUPS = {"entered", "past_first", "waiting_past_first"}

	def test_the_derived_groups(self):
		states = approvals.pipeline_states(altura.settings(), document_type=ACT)
		self.assertEqual(states["waiting"], ["Pending Approval", "Pending Manager", "Pending GM"])
		self.assertEqual(states["past_first"], ["Pending Manager", "Pending GM", "CONFIRMED"])
		self.assertEqual(states["waiting_past_first"], ["Pending Manager", "Pending GM"])
		self.assertEqual(states["entered"],
			["Draft", "Pending Approval", "Pending Manager", "Pending GM", "CONFIRMED"])

	def test_no_api_module_names_a_waiting_state(self):
		import re

		banned = {st for st, _a in rescue.UPSTREAM.values()} | {
			s.state for s in approvals.CATALOGUE
			if s.kind == "Approval" and s.document_type in (ACT, ASG, MP)}
		banned.discard("Draft")  # a chain's start, allowed by name everywhere
		offenders = []
		folder = os.path.join(APP, "api")
		for name in sorted(os.listdir(folder)):
			if not name.endswith(".py") or name == "config.py":
				continue
			code = re.sub(r'""".*?"""', "", read("api", name), flags=re.S)
			code = "\n".join(line.split("#", 1)[0] for line in code.split("\n"))
			for state in banned:
				if state == "Pending Approval":
					continue  # the Planner's, unchanged, and still its own literal
				for quoted in ("'%s'" % state, '"%s"' % state):
					if quoted in code:
						offenders.append("%s: %s" % (name, quoted))
		self.assertEqual(offenders, [], "\n".join(offenders))


class TestTheRescuePatch(unittest.TestCase):
	def test_the_mapping_is_the_addendum_s(self):
		self.assertEqual(sorted((dt, old, new) for dt, old, new, _k in rescue.moves()), sorted([
			(ACT, "Pending Farm Manager", "Pending Approval"),
			(ACT, "Pending HR Head", "Pending Manager"),
			(ASG, "Pending Farm Manager", "Pending Manager"),
			(MP, "Pending GM", "Pending Manager"),
		]))

	def run_patch(self, docs):
		"""`docs` is {doctype: {name: state}}, mutated as the patch moves them."""
		calls = []

		def get_all(doctype, filters=None, pluck=None, fields=None, **kw):
			if doctype == rescue.STAGE_TABLE:
				return [frappe._dict(stage=s.key, name=s.key, state=s.state, action=s.action)
					for s in approvals.CATALOGUE]
			if doctype == "Workflow Document State":
				return []
			wanted = (filters or {}).get("workflow_state")
			if isinstance(wanted, str):
				return [n for n, st in docs.get(doctype, {}).items() if st == wanted]
			return []

		def set_value(doctype, name, field, value=None, **kw):
			if field == "workflow_state":
				docs[doctype][name] = value
				calls.append(("move", doctype, name))

		db = mock.MagicMock()
		db.table_exists.return_value = True
		db.exists.return_value = False
		db.set_value.side_effect = set_value
		db.sql.side_effect = lambda *a, **k: calls.append(("todo",))
		saved = getattr(frappe.local, "db", None)
		frappe.local.db = db
		try:
			with mock.patch.object(frappe, "get_all", side_effect=get_all), \
					mock.patch.object(frappe, "get_doc") as get_doc, \
					mock.patch.object(frappe, "clear_cache"), \
					mock.patch.object(approvals, "build_workflows",
						side_effect=lambda s: calls.append(("build",)) or []), \
					mock.patch("builtins.print") as printed:
				rescue.execute()
		finally:
			frappe.local.db = saved
		return calls, [" ".join(map(str, c.args)) for c in printed.call_args_list], get_doc

	def test_the_nineteen_actuals_move_and_are_logged(self):
		docs = {ACT: {"ACT-%02d" % i: "Pending Farm Manager" for i in range(19)}}
		calls, log, get_doc = self.run_patch(docs)
		self.assertEqual(set(docs[ACT].values()), {"Pending Approval"})
		self.assertEqual(len([l for l in log if "Pending Farm Manager -> Pending Approval" in l]), 19)
		self.assertIn("Moved 19 document(s)", log[-1] if log else "")

	def test_documents_move_before_the_workflows_are_rebuilt(self):
		docs = {ACT: {"ACT-01": "Pending Farm Manager"}}
		calls, _log, _gd = self.run_patch(docs)
		kinds = [c[0] for c in calls]
		self.assertLess(kinds.index("move"), kinds.index("build"))
		self.assertLess(kinds.index("todo"), kinds.index("build"))

	def test_only_their_own_document_type_moves(self):
		"""`Pending GM` still means the GM step on the Assigner."""
		docs = {ASG: {"ASG-1": "Pending GM"}, MP: {"MP-1": "Pending GM"}}
		self.run_patch(docs)
		self.assertEqual(docs, {ASG: {"ASG-1": "Pending GM"}, MP: {"MP-1": "Pending Manager"}})

	def test_a_second_run_moves_nothing(self):
		docs = {ACT: {"ACT-01": "Pending Farm Manager"}}
		self.run_patch(docs)
		calls, log, _gd = self.run_patch(docs)
		self.assertNotIn("move", [c[0] for c in calls])

	def test_it_runs_last_and_after_the_approver_re_key(self):
		lines = [l.strip() for l in read("patches.txt").split("\n")
			if l.strip() and not l.startswith(("#", "["))]
		self.assertEqual(lines[-1], "work_management.patches.v1_0.rescue_documents_in_renamed_states")
		self.assertLess(lines.index("work_management.patches.v1_0.key_stage_approvers_by_stage"),
			lines.index("work_management.patches.v1_0.rescue_documents_in_renamed_states"))

	def test_it_never_saves_settings(self):
		"""A Settings save validates every approver row and could refuse -- and
		take the migrate down with it."""
		self.assertNotIn(".save(", read("patches", "v1_0", "rescue_documents_in_renamed_states.py"))


if __name__ == "__main__":
	unittest.main()
