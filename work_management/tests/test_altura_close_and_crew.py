# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Closing a plan and changing a crew, asked of Altura's chain.

Finding #2. Seven gates decided who may close a plan, ask for a close, add a
worker to approved work, release one, or record actuals on a day somebody was
marked Absent. All seven asked the same kind of question:

    r.startswith("Farm Manager")
    r == "Production Section Head"
    "General Manager" in roles

On the shipped chain those three name the people who take the steps, so the gates
looked right and the tests passed. On Altura every one of those steps is taken by
a Production Manager, and Philip -- who holds it, and who signs off the last step
of all four chains -- was refused by his own pipeline. The workaround on site was
to grant him a role whose name means something else.

These are the assertions that would have caught it: the same question, put to
`chain.may_take()` and `chain.takeable()` against the chain Altura runs, for the
three people who exist there and for the three shipped job titles who do not.

    PYTHONPATH=. ~/frappe-bench3/env/bin/python -m unittest \\
        work_management.tests.test_altura_close_and_crew -v
"""

import unittest

from work_management import chain
from work_management.tests import altura

ACT = "Work Management Actuals"
ASG = "Work Management Assigner"

#: The roles this app used to ask for. Nobody on Altura holds any of them, which
#: is the point: a gate that answers yes to this list and no to Philip is the bug.
#:
#: `General Manager` is deliberately NOT here. chain.may_take() names it too, as
#: the FARM dimension's bypass -- somebody who oversees every farm is not narrowed
#: to one -- so it passes a farm-scoped step by design and is asserted separately
#: below. It is the one name in the old gates that was doing real work.
SHIPPED = ["Farm Manager", "HR Head", "HOD HR", "HR Clerk",
	"Production Section Head"]


def final_step(document_type):
	"""The enabled step whose approval reaches the end of the chain.

	The same resolution api/actuals.py does for ACT_FINAL_STEP. Written out here
	rather than imported because the dispatcher is one 1,900-line function that
	cannot be entered without a site -- so this pins the RULE, and
	test_the_screens_speak_the_configured_chain pins that the dispatcher uses it.
	"""
	terminal = altura.states(document_type)["terminal"]
	found = None
	for step in chain.approval_steps(altura.chain_rows(), document_type, enabled_only=True):
		if step.get("next_state") == terminal:
			found = step
	return found


class TestTheChainIsShapedLikeAltura(unittest.TestCase):
	"""The fixture itself, so a later edit to it cannot quietly defuse the tests
	below by making the chain shipped-shaped again."""

	def test_five_steps_are_off(self):
		self.assertEqual(len(altura.OFF), 5, altura.OFF)

	def test_no_step_carries_a_shipped_state(self):
		shipped_states = {"Pending Farm Manager", "Pending HR Head", "Pending GM",
			"Pending Approval", "Pending Consultant"}
		for row in altura.chain_rows():
			with self.subTest(step=row["key"]):
				self.assertNotIn(row["state"], shipped_states)

	def test_no_step_is_taken_by_a_role_the_app_ships(self):
		for row in altura.chain_rows():
			with self.subTest(step=row["key"]):
				self.assertIn(row["role"], (altura.MANAGER, altura.SECTION_HEAD,
					altura.HR_OFFICER))

	def test_one_person_ends_every_chain(self):
		"""Philip. This is why the shipped gates locked the pipeline rather than
		merely narrowing it."""
		for document_type in ("Work Management Master Plan", "Work Management Planner",
				ASG, ACT):
			with self.subTest(document_type=document_type):
				self.assertEqual(final_step(document_type)["role"], altura.MANAGER)


class TestWhoDecidesAClose(unittest.TestCase):
	"""`act_close_confirm` and `act_close_pending`: the step that ends the chain."""

	def setUp(self):
		self.step = final_step(ACT)

	def test_it_is_the_actuals_manager_step(self):
		self.assertEqual(self.step["key"], "actuals_gm")
		self.assertEqual(self.step["label"], "Work done: Manager")

	def test_philip_may_close(self):
		self.assertIsNone(chain.may_take(self.step, [altura.MANAGER]))

	def test_the_shipped_roles_may_not(self):
		"""The old gate said yes to every one of these and no to Philip."""
		for role in SHIPPED:
			with self.subTest(role=role):
				self.assertIsNotNone(chain.may_take(self.step, [role]))

	def test_the_refusal_names_the_configured_step(self):
		why = chain.may_take(self.step, [altura.HR_OFFICER])
		self.assertIn(altura.MANAGER, why)
		self.assertIn("Work done: Manager", why)
		self.assertNotIn("General Manager", why)

	def test_the_hr_officer_may_not_close(self):
		"""She records the work -- so she may ASK -- but the decision is not
		hers."""
		self.assertIsNotNone(chain.may_take(self.step, [altura.HR_OFFICER]))

	def test_system_manager_still_unsticks_the_pipeline(self):
		self.assertIsNone(chain.may_take(self.step, ["System Manager"]))

	def test_a_general_manager_does_not_inherit_the_step(self):
		"""The farm bypass is for the FARM dimension only. This step is unscoped,
		so holding `General Manager` buys nothing -- which is what keeps a GM from
		taking a step the chain gave to somebody else."""
		self.assertIsNotNone(chain.may_take(self.step, ["General Manager"]))


class TestWhoMayAskForAClose(unittest.TestCase):
	"""`act_close_request` and `act_close_roles`: anybody this chain involves --
	an approver at any enabled step, or whoever the Submit step names, who is the
	person recording the work. A request decides nothing; the decider above still
	confirms it."""

	def may_request(self, roles):
		rows = altura.chain_rows()
		if chain.takeable(rows, ACT, roles, farms=altura.farms_for(roles)):
			return True
		submit = [r for r in rows
			if r["document_type"] == ACT and r["kind"] == "Submit"]
		return any(r["role"] in roles for r in submit) or "System Manager" in roles

	def test_philip_may_ask(self):
		self.assertTrue(self.may_request([altura.MANAGER]))

	def test_the_clerk_who_records_the_work_may_ask(self):
		"""`Work done: Record` is the HR Officer's step on this site, and she is
		the one who finds out the crop finished early."""
		self.assertTrue(self.may_request([altura.HR_OFFICER]))

	def test_somebody_the_chain_never_names_may_not(self):
		self.assertFalse(self.may_request(["Employee"]))
		self.assertFalse(self.may_request([altura.SECTION_HEAD]))

	def test_the_shipped_roles_may_not(self):
		for role in SHIPPED:
			with self.subTest(role=role):
				self.assertFalse(self.may_request([role]))

	def test_system_manager_may(self):
		self.assertTrue(self.may_request(["System Manager"]))


class TestWhoMayChangeAnApprovedCrew(unittest.TestCase):
	"""`a_add_crew` and `a_release`: anybody who takes any enabled step of the
	ASSIGNER chain. On Altura that is one step and one role."""

	def takeable(self, roles):
		return chain.takeable(altura.chain_rows(), ASG, roles,
			farms=altura.farms_for(roles))

	def test_only_one_assigner_step_is_on(self):
		steps = chain.approval_steps(altura.chain_rows(), ASG, enabled_only=True)
		self.assertEqual([s["key"] for s in steps], ["assigner_farm_manager"])

	def test_philip_may_change_the_crew(self):
		self.assertTrue(self.takeable([altura.MANAGER]))

	def test_the_shipped_roles_may_not(self):
		for role in SHIPPED:
			with self.subTest(role=role):
				self.assertFalse(self.takeable([role]))

	def test_the_hr_officer_may_not(self):
		"""Her step on this chain is switched off, so she takes none of it --
		and `Crew: People` being off is exactly what the old HR_HEAD_ROLES gate
		could not see."""
		self.assertFalse(self.takeable([altura.HR_OFFICER]))

	def test_a_general_manager_passes_the_farm_question_by_design(self):
		"""The one shipped name chain.may_take() still knows, and it is not a
		relapse: the crew step is farm-scoped, and somebody who oversees every
		farm is not narrowed to one. Asserted so that removing it would be a
		visible decision rather than an accident."""
		self.assertTrue(self.takeable(["General Manager"]))

	def test_the_switched_off_steps_are_nobody_s(self):
		for key in ("assigner_hr_head", "assigner_gm"):
			step = altura.step(key)
			with self.subTest(step=key):
				self.assertIsNotNone(chain.may_take(step, [step["role"]]))
				self.assertIn("switched off", chain.may_take(step, [step["role"]]))


class TestWhoMayOverrideAnAbsentDay(unittest.TestCase):
	"""`act_submit`: the farm-scoped step of the actuals chain, asked for THIS
	assignment's farm, or the step that ends the chain.

	The old gate was `"System Manager" or "General Manager" or "Farm Manager" in
	roles, else the farm's configured approver role` -- so the three names came
	FIRST and the configured answer was the fallback. Reversed, and with the
	names gone.
	"""

	def setUp(self):
		self.scoped = [s for s in chain.approval_steps(
			altura.chain_rows(), ACT, enabled_only=True) if s.get("scoped")]

	def may_override(self, roles, farm):
		farms = altura.farms_for(roles)
		if chain.may_take(final_step(ACT), roles, farms=farms) is None:
			return True
		for step in self.scoped:
			if chain.may_take(step, roles, farm=farm, farms=farms) is None:
				return True
		return False

	def test_there_is_a_farm_scoped_actuals_step(self):
		self.assertEqual([s["key"] for s in self.scoped], ["actuals_farm_manager"])

	def test_the_farms_approver_may_override_their_own_farm(self):
		self.assertTrue(self.may_override([altura.MANAGER], altura.FARM))

	def test_a_farm_scoped_approver_is_held_to_their_own_farm(self):
		"""Philip decides Altura and this chain would let him decide any farm he
		is named for -- but the scoped step refuses a farm he is not. Proved on
		the step itself, since the final step is unscoped and would allow it."""
		why = chain.may_take(self.scoped[0], [altura.MANAGER],
			farm=altura.OTHER_FARM, farms=[altura.FARM])
		self.assertIsNotNone(why)
		self.assertIn(altura.OTHER_FARM, why)

	def test_the_clerk_who_typed_it_may_not_override_her_own_entry(self):
		"""The whole point of the gate: recording work on a day attendance says
		somebody was absent is an approver's decision, not the enterer's."""
		self.assertFalse(self.may_override([altura.HR_OFFICER], altura.FARM))

	def test_the_shipped_roles_may_override_nothing(self):
		for role in SHIPPED:
			with self.subTest(role=role):
				self.assertFalse(self.may_override([role], altura.FARM))


if __name__ == "__main__":
	unittest.main()
