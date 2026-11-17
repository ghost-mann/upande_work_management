"""Team leaders may be any employee on the farm, with or without a login.

2026-11-17: the Planner's Team leaders tab offered only employees holding a
login (Vale 11 of 93). A team leader is now stored as their login when they
have one, else their Employee ID, in plain Data fields.
"""

import json
import os
import re
import unittest

from work_management.tests.mirror import SERVER_SCRIPTS as MIRROR

HERE = os.path.dirname(os.path.dirname(__file__))


def branch(action):
	src = open(os.path.join(MIRROR, "wm_masterplan.py")).read()
	return re.search(r'\nelif action == "%s":\n(.*?)\nelif action' % action, src, re.S).group(1)


class TestTeamLeadersWithoutLogin(unittest.TestCase):
	def test_candidates_do_not_require_a_login(self):
		body = branch("tl_list")
		self.assertIn("LEFT JOIN `tabUser` u ON u.name = e.user_id", body)
		self.assertNotIn("INNER JOIN `tabUser`", body)
		self.assertIn("IF(u.enabled = 1, e.user_id, e.name) user", body)

	def test_saves_accept_an_active_employee(self):
		for action in ("tl_save", "set_leaders"):
			self.assertIn('frappe.db.get_value("Employee", {"name"', branch(action), action)
			self.assertNotIn("is not an active user", branch(action), action)

	def test_leader_fields_are_plain_text(self):
		for dt, fields in (("work_management_planner", ["team_leader"]),
				("work_management_master_plan_activity", ["team_leader"]),
				("work_management_actuals", ["team_leader"]),
				("work_management_team_leader_stand_in", ["team_leader", "stand_in"]),
				("work_management_team_leader", ["user"])):
			meta = json.load(open(os.path.join(HERE, "work_management", "doctype", dt, dt + ".json")))
			for f in meta["fields"]:
				if f["fieldname"] in fields:
					self.assertEqual(f["fieldtype"], "Data", dt + "." + f["fieldname"])


if __name__ == "__main__":
	unittest.main()
