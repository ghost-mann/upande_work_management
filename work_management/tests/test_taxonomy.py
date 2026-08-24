"""Guards on the taxonomy name resolver.

Pure: a template in, strings out. No site, no database::

    ./env/bin/python -m unittest work_management.tests.test_taxonomy -v
"""

import unittest

import frappe

from work_management import taxonomy


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


class TestFieldLabelCatalogue(unittest.TestCase):
	"""The 21 level-naming labels, and the one that must not be touched."""

	def test_every_entry_names_a_field_the_app_defines(self):
		import glob
		import json
		import os

		here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
		known = {}
		for path in glob.glob(os.path.join(here, "work_management", "doctype", "*", "*.json")):
			with open(path) as handle:
				doc = json.load(handle)
			if doc.get("doctype") != "DocType":
				continue
			known[doc["name"]] = {f["fieldname"] for f in doc.get("fields", [])}
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
		"""An upgraded site must look unchanged until someone edits the template."""
		names = taxonomy.resolve(settings())
		rendered = {
			(d, f): taxonomy.label_for(t, names) for d, f, t in taxonomy.FIELD_LABELS
		}
		self.assertEqual(rendered[("Work Management Planner", "farm")], "Farm")
		self.assertEqual(rendered[("Work Management Planner", "extra_blocks")], "Additional Blocks")
		self.assertEqual(rendered[("Work Management Settings", "disc_multi_farm")], "Two Farms, one day")

	def test_renaming_the_top_level_reaches_every_farm_label(self):
		names = taxonomy.resolve(settings(tax_top_singular="Estate", tax_top_plural="Estates"))
		rendered = {
			(d, f): taxonomy.label_for(t, names) for d, f, t in taxonomy.FIELD_LABELS
		}
		self.assertEqual(rendered[("Work Management Planner", "farm")], "Estate")
		self.assertEqual(rendered[("Work Management Settings", "disc_multi_farm")], "Two Estates, one day")


if __name__ == "__main__":
	unittest.main()
