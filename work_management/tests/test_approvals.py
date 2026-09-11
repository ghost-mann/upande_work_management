# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Guards on the approval chain generated from Settings.

The chain used to be hand-written in a workflow fixture. It is now derived from
the stage catalogue and whatever Settings holds, which means a configuration
mistake can silently produce a workflow with a state nobody can leave. These
tests pin the shape of the generated plan.

``plan_workflow`` takes its configuration as an argument, so none of this needs
a site or a database::

    ./env/bin/python -m unittest work_management.tests.test_approvals -v
"""

import json
import os
import unittest

import frappe

from work_management import approvals

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def settings(overrides=None, approvers=()):
	"""A stand-in for Work Management Settings.

	Every catalogue stage is present and on, with the catalogue's own role, which
	is exactly what a fresh install looks like. `overrides` changes individual
	rows by stage key.
	"""
	overrides = overrides or {}
	rows = []
	for stage in approvals.CATALOGUE:
		row = {
			"stage": stage.key,
			"stage_label": stage.label,
			"document_type": stage.document_type,
			"kind": stage.kind,
			"enabled": 1,
			"role": stage.role,
		}
		row.update(overrides.get(stage.key, {}))
		rows.append(frappe._dict(row))
	return frappe._dict({
		"approval_stages": rows,
		"stage_approvers": [frappe._dict(row) for row in approvers],
	})


def approver(stage_label, user, scope=None, role=None):
	return {"stage_label": stage_label, "user": user, "scope": scope, "role": role}


def plan(document_type, config):
	return approvals.plan_workflow(document_type, rows=approvals.stage_rows(config), settings=config)


def states_of(plan_dict):
	return [state["state"] for state in plan_dict["states"]]


def moves(plan_dict):
	"""(from, action, to, allowed, condition) for every generated transition."""
	return [
		(t["state"], t["action"], t["next_state"], t["allowed"], t["condition"])
		for t in plan_dict["transitions"]
	]


def role_of(key):
	"""The role a shipped step defaults to.

	Read rather than hardcoded: these tests are about the *shape* of a chain --
	which states exist and what leads where -- and the role is an incidental
	element of each transition tuple. Spelling it out tied every shape test to
	one organisation's job titles, so changing the shipped defaults broke nine
	tests that had nothing to say about roles.
	"""
	for stage in approvals.CATALOGUE:
		if stage.key == key:
			return stage.role
	raise AssertionError("no such shipped step: " + key)


class TestChainShape(unittest.TestCase):
	def test_full_assigner_chain(self):
		result = plan("Work Management Assigner", settings())
		self.assertEqual(
			states_of(result),
			["Draft", "Pending Farm Manager", "Pending HR Head", "Pending GM", "Assigned", "Rejected"],
		)
		self.assertIn(
			("Draft", "Submit for Approval", "Pending Farm Manager", role_of("assigner_submit"), ""),
			moves(result),
		)
		self.assertIn(
			("Pending GM", "GM Approve", "Assigned", role_of("assigner_gm"), ""),
			moves(result),
		)

	def test_disabling_the_last_stage_relinks_to_the_terminal_state(self):
		result = plan("Work Management Assigner", settings({"assigner_gm": {"enabled": 0}}))
		self.assertNotIn("Pending GM", states_of(result))
		self.assertIn(
			("Pending HR Head", "HR Approve", "Assigned", role_of("assigner_hr_head"), ""),
			moves(result),
		)

	def test_disabling_a_middle_stage_relinks_across_it(self):
		result = plan("Work Management Assigner", settings({"assigner_hr_head": {"enabled": 0}}))
		self.assertNotIn("Pending HR Head", states_of(result))
		self.assertIn(
			("Pending Farm Manager", "FM Approve", "Pending GM", role_of("assigner_farm_manager"), ""),
			moves(result),
		)

	def test_disabling_every_approval_leaves_submit_going_straight_to_terminal(self):
		result = plan("Work Management Assigner", settings({
			"assigner_farm_manager": {"enabled": 0},
			"assigner_hr_head": {"enabled": 0},
			"assigner_gm": {"enabled": 0},
		}))
		self.assertEqual(states_of(result), ["Draft", "Assigned", "Rejected"])
		self.assertIn(
			("Draft", "Submit for Approval", "Assigned", role_of("assigner_submit"), ""),
			moves(result),
		)

	def test_submit_stages_cannot_be_switched_off(self):
		result = plan("Work Management Assigner", settings({"assigner_submit": {"enabled": 0}}))
		self.assertIn("Draft", states_of(result))

	def test_no_state_is_a_dead_end(self):
		"""Every state has a way out, bar the two that are meant to be final.

		A finished chain stops at its terminal state, and a rejection with no
		re-submit action stops at the reject state -- a cancelled payment stays
		cancelled. Every other state must be leavable, or a document parks there
		with no action available to anyone.
		"""
		for document_type, ends in approvals.CHAIN_ENDS.items():
			result = plan(document_type, settings())
			final = {ends["terminal"][0]}
			if not ends["resubmit"]:
				final.add(ends["reject"])
			leavable = {transition["state"] for transition in result["transitions"]}
			for state in states_of(result):
				if state in final:
					continue
				self.assertIn(
					state, leavable,
					f"{document_type}: nothing leaves {state!r}",
				)


class TestTerminalStates(unittest.TestCase):
	def test_each_document_type_ends_where_it_used_to(self):
		expected = {
			"Work Management Master Plan": ("Approved", 0),
			"Work Management Planner": ("Approved", 1),
			"Work Management Assigner": ("Assigned", 1),
			"Work Management Actuals": ("CONFIRMED", 1),
			"Work Management Payment": ("Paid", 0),
		}
		for document_type, (state, docstatus) in expected.items():
			result = plan(document_type, settings())
			match = [s for s in result["states"] if s["state"] == state]
			self.assertTrue(match, f"{document_type} has no {state} state")
			self.assertEqual(match[0]["doc_status"], docstatus, document_type)

	def test_payment_is_a_single_step_with_no_resubmit(self):
		result = plan("Work Management Payment", settings())
		self.assertEqual(states_of(result), ["Unpaid", "Paid", "Cancelled"])
		self.assertNotIn("Re-submit", [t["action"] for t in result["transitions"]])

	def test_a_paid_payment_can_still_be_cancelled(self):
		"""The workflow this replaced allowed it, and accounts rely on it."""
		self.assertIn(
			("Paid", "Cancel", "Cancelled", role_of("payment_accounts"), ""),
			moves(plan("Work Management Payment", settings())),
		)

	def test_nothing_can_manually_mark_a_payment_paid(self):
		"""payment_accounts ships with a blank action on purpose: a run
		becomes Paid exactly one way, payroll submitting the Salary Slip that
		carries its Additional Salary (on_salary_slip_submit() in
		api/payment.py) -- never a button. Cancel, the reject action, still
		works normally; only the forward one is suppressed."""
		result = plan("Work Management Payment", settings())
		self.assertNotIn("Mark Paid", [t["action"] for t in result["transitions"]])
		self.assertNotIn(
			"Unpaid", [t["state"] for t in result["transitions"] if t["next_state"] == "Paid"],
		)

	def test_rejection_returns_to_the_first_approval_not_the_draft(self):
		result = plan("Work Management Assigner", settings())
		resubmits = [t for t in result["transitions"] if t["action"] == "Re-submit"]
		self.assertEqual(len(resubmits), 1)
		self.assertEqual(resubmits[0]["state"], "Rejected")
		self.assertEqual(resubmits[0]["next_state"], "Pending Farm Manager")
		self.assertEqual(resubmits[0]["allowed"], role_of("assigner_submit"))


class TestRejection(unittest.TestCase):
	def test_approval_stages_can_reject_and_submit_stages_cannot(self):
		result = plan("Work Management Assigner", settings())
		rejects = {t["state"] for t in result["transitions"] if t["action"] == "Reject"}
		self.assertEqual(rejects, {"Pending Farm Manager", "Pending HR Head", "Pending GM"})
		self.assertNotIn("Draft", rejects)

	def test_payment_calls_it_cancelling_not_rejecting(self):
		result = plan("Work Management Payment", settings())
		self.assertNotIn("Reject", [t["action"] for t in result["transitions"]])
		cancels = [t for t in result["transitions"] if t["action"] == "Cancel"]
		self.assertTrue(cancels)
		self.assertEqual({t["next_state"] for t in cancels}, {"Cancelled"})


class TestFarmScoping(unittest.TestCase):
	def test_no_approvers_means_the_stage_role_covers_every_farm(self):
		result = plan("Work Management Assigner", settings())
		fm = [t for t in moves(result) if t[0] == "Pending Farm Manager" and t[1] == "FM Approve"]
		self.assertEqual(fm, [("Pending Farm Manager", "FM Approve", "Pending HR Head", role_of("assigner_farm_manager"), "")])

	def test_per_farm_approvers_generate_one_conditional_transition_each(self):
		config = settings(approvers=[
			approver("Assigner: Farm Manager", "sam@example.com", "Saboti", "Farm Manager Saboti"),
			approver("Assigner: Farm Manager", "lena@example.com", "Lokitela", "Farm Manager Lokitela"),
		])
		fm = [t for t in moves(plan("Work Management Assigner", config))
			if t[0] == "Pending Farm Manager" and t[1] == "FM Approve"]
		self.assertEqual(sorted(fm), sorted([
			("Pending Farm Manager", "FM Approve", "Pending HR Head", "Farm Manager Saboti",
				'doc.farm == "Saboti"'),
			("Pending Farm Manager", "FM Approve", "Pending HR Head", "Farm Manager Lokitela",
				'doc.farm == "Lokitela"'),
		]))

	def test_per_farm_approvers_do_not_leave_an_unconditional_way_through(self):
		"""The point of naming a farm's approver is that others cannot act for it."""
		config = settings(approvers=[
			approver("Assigner: Farm Manager", "sam@example.com", "Saboti", "Farm Manager Saboti"),
		])
		fm = [t for t in moves(plan("Work Management Assigner", config))
			if t[0] == "Pending Farm Manager" and t[1] == "FM Approve"]
		self.assertEqual([t[4] for t in fm], ['doc.farm == "Saboti"'])

	def test_an_approver_with_no_farm_covers_every_farm(self):
		config = settings(approvers=[
			approver("Assigner: Farm Manager", "sam@example.com", "Saboti", "Farm Manager Saboti"),
			approver("Assigner: Farm Manager", "gm@example.com"),
		])
		fm = [t for t in moves(plan("Work Management Assigner", config))
			if t[0] == "Pending Farm Manager" and t[1] == "FM Approve"]
		self.assertIn("", [t[4] for t in fm])

	def test_scoping_is_ignored_on_stages_that_are_not_farm_scoped(self):
		config = settings(approvers=[
			approver("Assigner: HR Head", "ann@example.com", "Saboti"),
		])
		hr = [t for t in moves(plan("Work Management Assigner", config))
			if t[0] == "Pending HR Head" and t[1] == "HR Approve"]
		self.assertEqual([t[4] for t in hr], [""])

	def test_two_approvers_of_one_farm_share_a_single_transition(self):
		config = settings(approvers=[
			approver("Assigner: Farm Manager", "sam@example.com", "Saboti", "Farm Manager Saboti"),
			approver("Assigner: Farm Manager", "sue@example.com", "Saboti", "Farm Manager Saboti"),
		])
		fm = [t for t in moves(plan("Work Management Assigner", config))
			if t[0] == "Pending Farm Manager" and t[1] == "FM Approve"]
		self.assertEqual(len(fm), 1)


class TestRoles(unittest.TestCase):
	def test_a_stage_role_change_reaches_the_transition_and_the_state(self):
		config = settings({"assigner_hr_head": {"role": "People Lead"}})
		result = plan("Work Management Assigner", config)
		self.assertIn(
			("Pending HR Head", "HR Approve", "Pending GM", "People Lead", ""),
			moves(result),
		)
		state = [s for s in result["states"] if s["state"] == "Pending HR Head"][0]
		self.assertEqual(state["allow_edit"], "People Lead")

	def test_an_approver_role_override_generates_its_own_transition(self):
		config = settings(approvers=[
			approver("Assigner: GM", "gm@example.com", role="Group MD"),
		])
		gm = [t for t in moves(plan("Work Management Assigner", config))
			if t[0] == "Pending GM" and t[1] == "GM Approve"]
		self.assertEqual([t[3] for t in gm], ["Group MD"])

	def test_desired_grants_pair_each_approver_with_their_stage_role(self):
		config = settings(approvers=[
			approver("Assigner: HR Head", "ann@example.com"),
			approver("Assigner: Farm Manager", "sam@example.com", "Saboti", "Farm Manager Saboti"),
		])
		grants = approvals._desired_grants(config)
		self.assertEqual(grants["ann@example.com"], {role_of("assigner_hr_head")})
		self.assertEqual(grants["sam@example.com"], {"Farm Manager Saboti"})

	def test_a_role_only_the_removed_row_named_is_still_revocable(self):
		"""The bug this pins: revoking read the new configuration only.

		Once the row naming "Farm Manager Saboti" is gone, that role is not in the
		new configuration's managed set, so a revoke filtered on it removed
		nothing and the approver kept the role for good.
		"""
		before = settings(approvers=[
			approver("Assigner: Farm Manager", "sam@example.com", "Saboti", "Farm Manager Saboti"),
		])
		after = settings()
		manageable = approvals.managed_roles(after) | approvals.managed_roles(before)
		self.assertIn("Farm Manager Saboti", manageable)
		self.assertNotIn("Farm Manager Saboti", approvals.managed_roles(after))
		stale = set(approvals._desired_grants(before)["sam@example.com"]) - set(
			approvals._desired_grants(after).get("sam@example.com", set())
		)
		self.assertEqual({role for role in stale if role in manageable}, {"Farm Manager Saboti"})

	def test_managed_roles_covers_overrides_so_revoking_can_reach_them(self):
		config = settings(approvers=[
			approver("Assigner: GM", "gm@example.com", role="Group MD"),
		])
		self.assertIn("Group MD", approvals.managed_roles(config))
		self.assertIn(role_of("assigner_hr_head"), approvals.managed_roles(config))


class TestIdempotence(unittest.TestCase):
	def test_planning_twice_from_the_same_configuration_gives_the_same_plan(self):
		config = settings(approvers=[
			approver("Actuals: Farm Manager", "sam@example.com", "Saboti", "Farm Manager Saboti"),
		])
		for document_type in approvals.CHAIN_ENDS:
			first = plan(document_type, config)
			second = plan(document_type, config)
			self.assertEqual(first, second, document_type)

	def test_no_transition_is_generated_twice(self):
		config = settings(approvers=[
			approver("Assigner: Farm Manager", "sam@example.com", "Saboti", "Farm Manager Saboti"),
			approver("Assigner: Farm Manager", "sue@example.com", "Saboti", "Farm Manager Saboti"),
			approver("Assigner: HR Head", "ann@example.com"),
			approver("Assigner: HR Head", "amy@example.com"),
		])
		for document_type in approvals.CHAIN_ENDS:
			transitions = moves(plan(document_type, config))
			self.assertEqual(len(transitions), len(set(transitions)), document_type)


class TestCatalogue(unittest.TestCase):
	def test_every_workflow_stage_belongs_to_a_document_type_with_a_chain_end(self):
		for stage in approvals.CATALOGUE:
			if stage.kind == "Gate":
				continue
			self.assertIn(stage.document_type, approvals.CHAIN_ENDS, stage.key)

	def test_every_document_type_starts_with_exactly_one_submit_stage(self):
		for document_type in approvals.CHAIN_ENDS:
			chain = approvals.chain_for(document_type)
			self.assertTrue(chain, document_type)
			submits = [stage for stage in chain if stage.kind == "Submit"]
			self.assertLessEqual(len(submits), 1, document_type)
			self.assertTrue(chain[0].required, f"{document_type}: first stage must be required")

	def test_stage_keys_and_labels_are_unique(self):
		keys = [stage.key for stage in approvals.CATALOGUE]
		labels = [stage.label for stage in approvals.CATALOGUE]
		self.assertEqual(len(keys), len(set(keys)))
		self.assertEqual(len(labels), len(set(labels)))

	def test_gates_have_no_workflow_state_or_action(self):
		for stage in approvals.CATALOGUE:
			if stage.kind != "Gate":
				continue
			self.assertIsNone(stage.state, stage.key)
			self.assertIsNone(stage.action, stage.key)

	def test_the_approver_select_options_match_the_catalogue(self):
		"""The child doctype's Select is a copy of the catalogue and must not drift."""
		path = os.path.join(
			APP, "work_management", "doctype", "work_management_stage_approver",
			"work_management_stage_approver.json",
		)
		with open(path) as handle:
			doc = json.load(handle)
		field = [f for f in doc["fields"] if f["fieldname"] == "stage_label"][0]
		self.assertEqual(field["options"].split("\n"), approvals.stage_labels())


if __name__ == "__main__":
	unittest.main()
