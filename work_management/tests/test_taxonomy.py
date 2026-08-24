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


if __name__ == "__main__":
	unittest.main()
