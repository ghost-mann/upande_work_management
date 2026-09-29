"""Rejecting an actual needs the role that could approve it at that stage.

`act_reject` checked the document's state and nothing about the person. Any
authenticated user who could reach /api/method/wm_actuals -- a Work Entry clerk
included -- could reject anybody's actuals at any stage, and rejecting a
CONFIRMED one flips it to docstatus 2, undoing an approved submission. The
screen only draws the Reject button in the approval queues, and a gate in the
browser is not a gate (see test_step_role_is_enforced).

The rule is the approve actions' own, applied to the stage the document is at:

    Pending Farm Manager   the FM step's role, a farm approver role for THAT
                           farm, General Manager or System Manager -- exactly
                           who act_fm_approve lets through
    Pending HR Head        the HR Head step's role, or System Manager
    Pending GM             the GM step's role, or System Manager
    CONFIRMED              the GM step's role, or System Manager: reversing a
                           confirmation is the confirmer's call

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_rejecting_takes_the_approvers_role -v
"""

import os
import re
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(APP, "api", "actuals.py")) as handle:
	API = handle.read()


def action_block(action):
	at = API.index('elif action == "%s":' % action)
	nxt = re.search(r"^\s*elif action ==", API[at + 30:], re.M)
	return API[at:at + 30 + (nxt.start() if nxt else len(API))]


class TestRejectingIsGatedByStage(unittest.TestCase):
	def setUp(self):
		self.block = action_block("act_reject")
		# everything before the first write is the gate
		self.gate = self.block[:self.block.index("frappe.db.set_value")]

	def test_each_stage_names_its_approvers_role(self):
		for stage in ("actuals_farm_manager", "actuals_hr_head", "actuals_gm"):
			with self.subTest(stage=stage):
				self.assertIn('STAGE_ROLE["%s"]' % stage, self.gate)

	def test_system_manager_passes(self):
		self.assertIn('"System Manager" in MY_ROLES', self.gate)

	def test_a_farm_manager_is_held_to_their_own_farms(self):
		self.assertIn("FARM_APPROVER_ROLE.items()", self.gate)
		self.assertIn("cur.farm not in", self.gate)

	def test_a_confirmed_actual_takes_the_gm_role(self):
		self.assertRegex(self.gate, r'"CONFIRMED"[^\n]*\n[^\n]*STAGE_ROLE\["actuals_gm"\]')

	def test_the_refusal_names_the_role_required(self):
		self.assertIn("can reject at this stage", self.gate)

	def test_the_gate_runs_before_anything_changes(self):
		self.assertIn("rej_err", self.gate)
		self.assertRegex(self.block, r"if rej_err:\s*\n\s*out\[\"error\"\] = rej_err\s*\n\s*else:")


if __name__ == "__main__":
	unittest.main()
