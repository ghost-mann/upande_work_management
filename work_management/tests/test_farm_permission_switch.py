"""Enforcement is a switch, and it ships off.

The audit on live says 95 users are restricted and none of them worked a farm
they are not permitted, so enforcing there changes what nobody can do. That is
the reassuring answer, and it is still not a reason to enforce everywhere by
default: another site's 127 permissions have not been reconciled, and one of them
restricts a consultant to a single farm he does not only work.

So the app reads Frappe's User Permissions and then asks Settings whether to act
on them. Off -- the default -- is today's behaviour exactly, on every site, with
no migration to get wrong. A site turns it on once its own audit comes back
clean, and the switch goes away once every site has.

The switch is the whole of the safety argument, so these tests cover the two
things that would break it: a default that is not off, and a wording that does
not tell somebody what turning it on will do to their users.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_farm_permission_switch -v
"""

import json
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(HERE, "work_management", "doctype",
	"work_management_settings", "work_management_settings.json")
FIELD = "farms_respect_user_permissions"


def settings_doc():
	with open(SETTINGS) as handle:
		return json.load(handle)


def field(doc, fieldname):
	for f in doc.get("fields", []):
		if f.get("fieldname") == fieldname:
			return f
	return None


class TestTheSwitchExistsAndIsOff(unittest.TestCase):
	def setUp(self):
		self.doc = settings_doc()
		self.field = field(self.doc, FIELD)

	def test_the_field_is_there(self):
		self.assertIsNotNone(self.field, "%s is missing from Settings" % FIELD)

	def test_it_is_a_checkbox(self):
		self.assertEqual(self.field["fieldtype"], "Check")

	def test_it_defaults_to_off(self):
		"""Not "0" by accident -- explicitly, so a later edit that drops the
		default fails here rather than silently enforcing on every site that
		migrates."""
		self.assertEqual(str(self.field.get("default", "")), "0")

	def test_it_is_in_the_field_order(self):
		self.assertIn(FIELD, self.doc["field_order"])

	def test_it_sits_in_the_farms_tab(self):
		order = self.doc["field_order"]
		tabs = [f for f in order if f.startswith("tab_")]
		mine = order.index(FIELD)
		before = [t for t in tabs if order.index(t) < mine]
		self.assertEqual(before[-1], "tab_farms",
			"the farm permission switch belongs with the other farm settings")

	def test_it_sits_beside_the_other_narrowing_switch(self):
		"""Two switches narrow the farm list and they must be read together:
		one asks which farms this project works, the other which farms this
		person may touch."""
		order = self.doc["field_order"]
		self.assertLess(abs(order.index(FIELD) - order.index("farms_restrict")), 3)


class TestTheWordingSaysWhatWillHappen(unittest.TestCase):
	def setUp(self):
		self.field = field(settings_doc(), FIELD)

	def test_it_has_a_description(self):
		self.assertTrue((self.field.get("description") or "").strip())

	def test_it_names_user_permissions_so_somebody_knows_where_to_look(self):
		self.assertIn("User Permission", self.field["description"])

	def test_it_says_what_off_means(self):
		"""Somebody reading this needs to know the default is not enforcement."""
		self.assertIn("Off", self.field["description"])

	def test_it_warns_that_turning_it_on_removes_access(self):
		description = self.field["description"].lower()
		self.assertTrue(
			any(w in description for w in ("audit", "check", "before")),
			"the description must send somebody to the audit before they enable it")

	def test_the_label_is_about_people_not_mechanism(self):
		"""Whoever ticks this is thinking about who sees what, not about which
		Frappe table the answer lives in."""
		self.assertIn("farm", self.field["label"].lower())


class TestConfigHonoursTheSwitch(unittest.TestCase):
	"""get_config() is the choke point every screen's farm list comes through,
	so this is where the switch bites. The narrowing itself is tested in
	test_permitted_farms; this covers the wiring reading the flag at all."""

	def test_get_config_reads_the_flag(self):
		import inspect
		from work_management.api import config
		source = inspect.getsource(config.get_config)
		self.assertIn(FIELD, source)

	def test_get_config_narrows_through_the_tested_helper(self):
		import inspect
		from work_management.api import config
		source = inspect.getsource(config.get_config)
		self.assertIn("narrow_to_permitted", source)

	def test_the_flag_is_read_with_a_default_of_off(self):
		"""A Settings doc that predates the field returns None for it, and None
		must mean off -- not "falsy so who cares", because a later refactor to
		`is not None` would flip every site at once."""
		import inspect
		from work_management.api import config
		source = inspect.getsource(config.get_config)
		self.assertIn('settings.get("%s")' % FIELD, source)


if __name__ == "__main__":
	unittest.main()
