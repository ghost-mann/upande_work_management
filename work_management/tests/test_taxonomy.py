"""Guards on the taxonomy name resolver.

Pure: a template in, strings out. No site, no database::

    ./env/bin/python -m unittest work_management.tests.test_taxonomy -v
"""

import unittest

import frappe

from work_management import install, taxonomy


def settings(**overrides):
	base = {
		"tax_bu_enabled": 0,
		"tax_bu_singular": "", "tax_bu_plural": "",
		"tax_top_singular": "", "tax_top_plural": "",
		"tax_unit_singular": "", "tax_unit_plural": "",
		"tax_section_singular": "", "tax_section_plural": "",
	}
	base.update(overrides)
	return frappe._dict(base)


class TestResolve(unittest.TestCase):
	def test_an_empty_template_gives_the_shipped_defaults(self):
		names = taxonomy.resolve(settings())
		self.assertEqual(names["top_singular"], "Farm")
		self.assertEqual(names["top_plural"], "Farms")
		self.assertEqual(names["unit_singular"], "Block")
		self.assertEqual(names["unit_plural"], "Blocks")
		self.assertEqual(names["section_singular"], "Section")

	def test_a_configured_name_wins(self):
		names = taxonomy.resolve(settings(tax_top_singular="Estate", tax_top_plural="Estates"))
		self.assertEqual(names["top_singular"], "Estate")
		self.assertEqual(names["top_plural"], "Estates")

	def test_a_blank_name_falls_back_rather_than_showing_nothing(self):
		names = taxonomy.resolve(settings(tax_top_singular="   "))
		self.assertEqual(names["top_singular"], "Farm")

	def test_business_unit_is_off_by_default(self):
		self.assertFalse(taxonomy.resolve(settings())["bu_enabled"])

	def test_business_unit_can_be_turned_on_and_named(self):
		names = taxonomy.resolve(settings(tax_bu_enabled=1, tax_bu_singular="Division"))
		self.assertTrue(names["bu_enabled"])
		self.assertEqual(names["bu_singular"], "Division")

	def test_resolve_survives_settings_that_lack_the_fields(self):
		"""A site mid-migrate has the template fields missing, not blank."""
		names = taxonomy.resolve(frappe._dict({}))
		self.assertEqual(names["top_singular"], "Farm")


class TestLabelTemplates(unittest.TestCase):
	def test_a_bare_placeholder_is_substituted(self):
		names = taxonomy.resolve(settings(tax_unit_plural="Plots"))
		self.assertEqual(taxonomy.label_for("Additional {unit_plural}", names), "Additional Plots")

	def test_a_sentence_keeps_its_shape(self):
		names = taxonomy.resolve(settings(tax_top_plural="Estates"))
		self.assertEqual(taxonomy.label_for("Two {top_plural}, one day", names), "Two Estates, one day")

	def test_an_unknown_placeholder_is_left_alone_rather_than_raising(self):
		names = taxonomy.resolve(settings())
		self.assertEqual(taxonomy.label_for("{nope} here", names), "{nope} here")


class TestSettingsTemplate(unittest.TestCase):
	"""The resolver reads these fields; Settings must actually carry them."""

	@classmethod
	def setUpClass(cls):
		import json
		import os

		here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
		path = os.path.join(
			here, "work_management", "doctype", "work_management_settings",
			"work_management_settings.json",
		)
		with open(path) as handle:
			cls.doc = json.load(handle)
		cls.fields = {f["fieldname"]: f for f in cls.doc["fields"]}

	def test_every_level_has_a_singular_and_plural_field(self):
		for level in taxonomy.LEVELS:
			self.assertIn(f"tax_{level.key}_singular", self.fields, level.key)
			self.assertIn(f"tax_{level.key}_plural", self.fields, level.key)

	def test_business_unit_has_an_enable_flag(self):
		self.assertIn("tax_bu_enabled", self.fields)
		self.assertEqual(self.fields["tax_bu_enabled"]["fieldtype"], "Check")

	def test_the_template_fields_are_on_the_form(self):
		for level in taxonomy.LEVELS:
			self.assertIn(f"tax_{level.key}_singular", self.doc["field_order"], level.key)

	def test_every_template_field_is_documented(self):
		"""The user guide's settings chapter is generated from these."""
		for name, field in self.fields.items():
			if name.startswith("tax_"):
				self.assertTrue((field.get("description") or "").strip(), name)


def _shipped_doctypes():
	"""{doctype name: {fieldname: field dict}} for every DocType JSON the app ships."""
	import glob
	import json
	import os

	here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	shipped = {}
	for path in glob.glob(os.path.join(here, "work_management", "doctype", "*", "*.json")):
		with open(path) as handle:
			doc = json.load(handle)
		if doc.get("doctype") != "DocType":
			continue
		shipped[doc["name"]] = {f["fieldname"]: f for f in doc.get("fields", [])}
	return shipped


class TestFieldLabelCatalogue(unittest.TestCase):
	"""The 20 level-naming labels, and the one that must not be touched."""

	def test_every_entry_names_a_field_the_app_defines(self):
		known = _shipped_doctypes()
		for doctype, fieldname, _template in taxonomy.FIELD_LABELS:
			self.assertIn(doctype, known, doctype)
			self.assertIn(fieldname, known[doctype], f"{doctype}.{fieldname}")

	def test_the_verb_block_label_is_not_in_the_catalogue(self):
		"""'Check attendance (block employees marked Absent)' uses block as a verb."""
		entries = {(d, f) for d, f, _t in taxonomy.FIELD_LABELS}
		self.assertNotIn(("Work Management Settings", "att_block_absent"), entries)

	def test_every_template_renders_with_the_default_names(self):
		names = taxonomy.resolve(settings())
		for doctype, fieldname, template in taxonomy.FIELD_LABELS:
			rendered = taxonomy.label_for(template, names)
			self.assertNotIn("{", rendered, f"{doctype}.{fieldname}")
			self.assertTrue(rendered.strip(), f"{doctype}.{fieldname}")

	def test_the_defaults_reproduce_todays_wording(self):
		"""An upgraded site must look unchanged until someone edits the template.

		Generated against the shipped JSON rather than hardcoded, so it cannot
		drift out of sync as fields are added to FIELD_LABELS.
		"""
		names = taxonomy.resolve(settings())
		shipped = _shipped_doctypes()
		mismatches = []
		for doctype, fieldname, template in taxonomy.FIELD_LABELS:
			rendered = taxonomy.label_for(template, names)
			shipped_label = shipped[doctype][fieldname].get("label")
			if rendered != shipped_label:
				mismatches.append(
					f"{doctype}.{fieldname}: rendered {rendered!r} != shipped {shipped_label!r}"
				)
		self.assertEqual(mismatches, [], "\n".join(mismatches))

	def test_renaming_the_top_level_reaches_every_farm_label(self):
		names = taxonomy.resolve(settings(tax_top_singular="Estate", tax_top_plural="Estates"))
		rendered = {
			(d, f): taxonomy.label_for(t, names) for d, f, t in taxonomy.FIELD_LABELS
		}
		self.assertEqual(rendered[("Work Management Planner", "farm")], "Estate")
		self.assertEqual(rendered[("Work Management Settings", "disc_multi_farm")], "Two Estates, one day")


class TestBusinessUnitField(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		import json
		import os

		here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
		path = os.path.join(
			here, "work_management", "doctype", "work_management_farm",
			"work_management_farm.json",
		)
		with open(path) as handle:
			cls.doc = json.load(handle)
		cls.fields = {f["fieldname"]: f for f in cls.doc["fields"]}

	def test_the_farm_carries_a_business_unit(self):
		self.assertIn("business_unit", self.fields)

	def test_it_ships_as_data_so_a_standalone_install_works(self):
		"""upande_core owns the Business Unit doctype; it may not be installed."""
		self.assertEqual(self.fields["business_unit"]["fieldtype"], "Data")
		self.assertFalse(self.fields["business_unit"].get("options"))

	def test_it_is_on_the_form(self):
		self.assertIn("business_unit", self.doc["field_order"])


class TestBusinessUnitFieldPlan(unittest.TestCase):
	"""install.plan_business_unit_field() -- pure, no site, no database.

	Covers both directions of the Data<->Link degradation and the
	interrupted-write case a partial upgrade can leave behind.
	"""

	def test_doctype_absent_and_field_already_data_needs_nothing(self):
		self.assertEqual(install.plan_business_unit_field(False, "Data", None), "noop")

	def test_doctype_present_and_field_already_linked_needs_nothing(self):
		self.assertEqual(
			install.plan_business_unit_field(True, "Link", "Business Unit"), "noop"
		)

	def test_doctype_present_and_field_still_data_is_upgraded(self):
		self.assertEqual(install.plan_business_unit_field(True, "Data", None), "upgrade")

	def test_an_interrupted_upgrade_is_repaired_not_skipped(self):
		"""fieldtype flipped to Link but the options write never landed."""
		self.assertEqual(install.plan_business_unit_field(True, "Link", None), "upgrade")

	def test_doctype_removed_while_field_is_still_linked_is_downgraded(self):
		self.assertEqual(
			install.plan_business_unit_field(False, "Link", "Business Unit"), "downgrade"
		)

	def test_an_interrupted_downgrade_is_also_repaired(self):
		"""Same half-written state, but the doctype has since disappeared."""
		self.assertEqual(install.plan_business_unit_field(False, "Link", None), "downgrade")

	def test_an_interrupted_downgrade_leaves_options_behind_but_is_still_caught(self):
		"""fieldtype's Property Setter is gone but options's survived the interruption."""
		self.assertEqual(
			install.plan_business_unit_field(False, None, "Business Unit"), "downgrade"
		)


if __name__ == "__main__":
	unittest.main()
