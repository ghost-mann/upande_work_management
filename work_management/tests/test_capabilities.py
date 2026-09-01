"""Who may do what, as named capabilities rather than someone's job titles.

The approval chain became configurable and everything else stayed hardcoded. Four
lists and a scatter of inline checks still carried Kaitet's org chart:

    MP_EDIT_ROLES = ["Farm Manager", "HOD HR", "General Manager", "System Manager"]
    RATE_ROLES    = ["General Manager", "HOD HR", "System Manager"]
    SEND_ROLES    = ["HOD HR", "Accounts Manager", "Accounts User", ...]
    is_clerk      = HR User or HR Manager or HR Clerk or HOD HR
    is_accounts   = Accounts Manager or Accounts User

So a farm could say who approves a plan and not who may change a rate.

Each of those is one question -- "who may set rates?" -- and a question with a
name can be configured. Five names, each pointing at any number of roles, seeded
into Settings the way the approval steps are, and defaulting to `System Manager`
alone so a fresh install invents nothing and grants nothing by accident.

Two things deliberately not turned into capabilities:

  MP_GM_ROLES     duplicated the approval chain's own `masterplan_gm` role. Two
                  places answering "who is the GM here" is the bug pattern this
                  whole week has been about, so it is deleted rather than renamed.
  the farm-scope  `fmbypass`, `AP_BYPASS` and friends answer "may this person act
  bypasses        outside their farm", which is the farm dimension, not a
                  capability -- and it already has a designed replacement in the
                  User Permission work. Making them capabilities would enshrine a
                  mechanism we intend to remove.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_capabilities -v
"""

import unittest

from work_management import capabilities


class Row(dict):
	def __getattr__(self, name):
		try:
			return self[name]
		except KeyError:
			return None


class Settings(dict):
	def __init__(self, rows):
		super().__init__(capabilities=rows)

	def get(self, key, default=None):
		return dict.get(self, key, default)


def settings(*pairs):
	"""A Settings doc holding these (capability, role) rows."""
	return Settings([Row({"capability": c, "role": r, "idx": i})
		for i, (c, r) in enumerate(pairs, 1)])


class TestTheCatalogue(unittest.TestCase):
	def test_the_five_are_there(self):
		keys = {c.key for c in capabilities.CATALOGUE}
		self.assertEqual(keys, {
			"edit_master_plan", "set_rates", "send_payment",
			"enter_work", "handle_payments",
		})

	def test_every_capability_defaults_to_system_manager_alone(self):
		"""A fresh install must invent no role and grant nothing by accident.
		System Manager is the only role Frappe guarantees, and it is what the
		approval chain already seeds to."""
		for cap in capabilities.CATALOGUE:
			with self.subTest(capability=cap.key):
				self.assertEqual(cap.roles, ["System Manager"])

	def test_each_has_a_label_and_a_description(self):
		"""Somebody reading Settings has to know what they are granting."""
		for cap in capabilities.CATALOGUE:
			with self.subTest(capability=cap.key):
				self.assertTrue(cap.label.strip())
				self.assertTrue(cap.description.strip())

	def test_the_labels_are_unique(self):
		"""The Settings row stores the label, as the approver table does, so two
		capabilities sharing one could not be told apart."""
		labels = [c.label for c in capabilities.CATALOGUE]
		self.assertEqual(len(labels), len(set(labels)))

	def test_no_label_names_a_job_title(self):
		"""A capability is a question about the work, not about the org chart --
		"set task rates", never "HR Head". Naming the title would put the thing
		being removed back into the configuration screen."""
		titles = ("HOD", "Manager", "Clerk", "Head", "GM", "Officer")
		for cap in capabilities.CATALOGUE:
			for title in titles:
				with self.subTest(capability=cap.key, title=title):
					self.assertNotIn(title.lower(), cap.label.lower())


class TestWhatSettingsSays(unittest.TestCase):
	def test_no_rows_falls_back_to_the_shipped_default(self):
		"""A site mid-install, or one whose grid somebody emptied. Falling back
		beats answering "nobody", which would lock the screen with no way in."""
		self.assertEqual(
			capabilities.roles_for("set_rates", settings()), ["System Manager"])

	def test_a_configured_role_replaces_the_default(self):
		self.assertEqual(
			capabilities.roles_for("set_rates", settings(("set_rates", "Agronomist"))),
			["Agronomist"])

	def test_several_roles_for_one_capability(self):
		self.assertEqual(
			capabilities.roles_for("send_payment", settings(
				("send_payment", "Finance Lead"),
				("send_payment", "Accounts Manager"))),
			["Finance Lead", "Accounts Manager"])

	def test_rows_for_other_capabilities_are_ignored(self):
		self.assertEqual(
			capabilities.roles_for("set_rates", settings(
				("send_payment", "Finance Lead"),
				("set_rates", "Agronomist"))),
			["Agronomist"])

	def test_a_row_with_no_role_is_skipped(self):
		"""A half-typed row in an open grid must not empty a capability."""
		self.assertEqual(
			capabilities.roles_for("set_rates", settings(
				("set_rates", None), ("set_rates", "Agronomist"))),
			["Agronomist"])

	def test_a_capability_configured_with_only_blank_rows_falls_back(self):
		self.assertEqual(
			capabilities.roles_for("set_rates", settings(("set_rates", ""))),
			["System Manager"])

	def test_an_unknown_capability_grants_nothing(self):
		"""Not the default, and not everybody. A key the code does not know is a
		typo or a deleted feature, and a gate that opens on a typo is a hole."""
		self.assertEqual(capabilities.roles_for("nonsense", settings()), [])

	def test_the_order_is_the_grids(self):
		self.assertEqual(
			capabilities.roles_for("send_payment", settings(
				("send_payment", "B"), ("send_payment", "A"))),
			["B", "A"])


class TestMay(unittest.TestCase):
	CONFIG = {"set_rates": ["Agronomist", "Accounts Manager"]}

	def test_holding_a_listed_role_passes(self):
		self.assertTrue(capabilities.may("set_rates", ["Agronomist"], self.CONFIG))

	def test_holding_none_of_them_is_refused(self):
		self.assertFalse(capabilities.may("set_rates", ["Employee"], self.CONFIG))

	def test_system_manager_always_passes(self):
		"""The same bypass the approval steps allow: somebody has to be able to
		configure a site that is not yet configured."""
		self.assertTrue(capabilities.may("set_rates", ["System Manager"], self.CONFIG))

	def test_no_roles_at_all_is_refused(self):
		self.assertFalse(capabilities.may("set_rates", [], self.CONFIG))
		self.assertFalse(capabilities.may("set_rates", None, self.CONFIG))

	def test_a_capability_missing_from_the_config_is_refused(self):
		"""Except for System Manager, who is never locked out."""
		self.assertFalse(capabilities.may("set_rates", ["Agronomist"], {}))
		self.assertTrue(capabilities.may("set_rates", ["System Manager"], {}))

	def test_the_comparison_is_exact(self):
		self.assertFalse(capabilities.may("set_rates", ["Agronomist Clerk"], self.CONFIG))


class TestSeeding(unittest.TestCase):
	"""Settings gets one row per capability so the grid is discoverable -- an
	empty grid tells a reader nothing about what can be granted."""

	def test_a_fresh_settings_gets_a_row_for_each(self):
		rows = capabilities.seeded_rows([])
		self.assertEqual([r["capability"] for r in rows],
			[c.label for c in capabilities.CATALOGUE])

	def test_the_seeded_row_carries_the_default_role(self):
		rows = {r["capability"]: r for r in capabilities.seeded_rows([])}
		label = capabilities.by_key("set_rates").label
		self.assertEqual(rows[label]["role"], "System Manager")

	def test_a_role_somebody_chose_is_kept(self):
		"""Re-seeding on every migrate must not undo the configuration."""
		label = capabilities.by_key("set_rates").label
		existing = [Row({"capability": label, "role": "Agronomist", "idx": 1})]
		rows = capabilities.seeded_rows(existing)
		mine = [r for r in rows if r["capability"] == label]
		self.assertEqual([r["role"] for r in mine], ["Agronomist"])

	def test_extra_rows_somebody_added_are_kept(self):
		"""Two roles for one capability is the normal way to widen it."""
		label = capabilities.by_key("send_payment").label
		existing = [
			Row({"capability": label, "role": "Finance Lead", "idx": 1}),
			Row({"capability": label, "role": "Accounts Manager", "idx": 2}),
		]
		rows = capabilities.seeded_rows(existing)
		mine = [r["role"] for r in rows if r["capability"] == label]
		self.assertEqual(mine, ["Finance Lead", "Accounts Manager"])

	def test_a_row_for_a_capability_the_code_dropped_is_kept(self):
		"""The approval stages learned this the hard way: rebuilding the table
		from the catalogue threw away what somebody had added."""
		existing = [Row({"capability": "Something removed", "role": "X", "idx": 1})]
		rows = capabilities.seeded_rows(existing)
		self.assertIn("Something removed", [r["capability"] for r in rows])

	def test_seeding_twice_changes_nothing(self):
		once = capabilities.seeded_rows([])
		twice = capabilities.seeded_rows([Row(r) for r in once])
		self.assertEqual(once, twice)


class TestNothingHardcodedSurvives(unittest.TestCase):
	"""The point of the exercise: the lists are gone from the shipped code."""

	def test_the_four_role_lists_are_gone_from_the_api(self):
		import glob
		import os

		here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
		offenders = []
		for path in glob.glob(os.path.join(here, "api", "*.py")):
			text = open(path).read()
			for name in ("MP_EDIT_ROLES", "MP_GM_ROLES", "RATE_ROLES", "SEND_ROLES"):
				if name in text:
					offenders.append("%s still defines %s" % (os.path.basename(path), name))
		self.assertEqual(offenders, [], "\n".join(offenders))


if __name__ == "__main__":
	unittest.main()
