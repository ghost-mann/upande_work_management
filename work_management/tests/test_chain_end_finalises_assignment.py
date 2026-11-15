"""Whichever assigner step ends the chain finalises the assignment.

2026-11-13 live switched the assigner HR and GM steps off, so the farm manager's
approval became the last step. Only the GM step submitted the assignment and set
`approval_date`, and the actuals list fetches Assigned assignments newest approval
first and shows 200 -- so every FM-final assignment (NULL approval_date) sorted
last and never reached the actuals screen (32 at Vale and Endebess by 11-15).
"""

import os
import re
import unittest

from work_management.tests.mirror import SERVER_SCRIPTS as MIRROR


def branch(action):
	src = open(os.path.join(MIRROR, "wm_assigner.py")).read()
	m = re.search(r'\nelif action == "%s":\n(.*?)\nelif action' % action, src, re.S)
	return m.group(1)


class TestChainEndFinalises(unittest.TestCase):
	def test_fm_and_hr_steps_finalise_when_next_state_is_assigned(self):
		for action, stage in (("a_fm_approve", "assigner_farm_manager"), ("a_hr_approve", "assigner_hr_head")):
			body = branch(action)
			self.assertIn('if STAGE_NEXT["%s"] == "Assigned":' % stage, body, action)
			self.assertIn('"approval_date": frappe.utils.today()', body, action)
			self.assertIn('"docstatus": 1', body, action)
			self.assertIn('"Work Assignment Employee"', body, action)


if __name__ == "__main__":
	unittest.main()
