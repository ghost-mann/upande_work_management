# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Guards on the user guide.

Two of the guide's chapters are generated from the code they document -- the
approval stage catalogue and the Work Management Settings reference -- so they
cannot fall behind. These tests protect the things generation alone cannot: that
every settings field actually says what it does, that the numbering the table of
contents relies on is sound, and that the document still builds.

No site and no database needed::

    ./env/bin/python -m unittest work_management.tests.test_manual -v
"""

import json
import os
import sys
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(APP)
DOCS = os.path.join(REPO, "docs")

if DOCS not in sys.path:
	sys.path.insert(0, DOCS)
if REPO not in sys.path:
	sys.path.insert(0, REPO)

import build_manual  # noqa: E402
import manual_content  # noqa: E402

from work_management import approvals  # noqa: E402

SKIP_FIELDTYPES = {"Section Break", "Column Break", "HTML", "Tab Break"}


def settings_doc():
	with open(manual_content.SETTINGS_JSON) as handle:
		return json.load(handle)


class TestSettingsAreDocumented(unittest.TestCase):
	def test_every_settings_field_says_what_it_does(self):
		"""The reference chapter is generated from these descriptions.

		A field with no description turns into filler in the guide, so the guide
		is the reason to write one -- and this test is the reason it gets written
		when the field is added, not later.
		"""
		undocumented = [
			field["fieldname"]
			for field in settings_doc()["fields"]
			if field["fieldtype"] not in SKIP_FIELDTYPES
			and not (field.get("description") or "").strip()
		]
		self.assertEqual(undocumented, [], "settings fields with no description")

	def test_the_reference_covers_every_field(self):
		doc = settings_doc()
		documented = {
			row[0].replace(" (read-only)", "")
			for _kind, (_caption, _headers, rows) in manual_content.settings_blocks()
			for row in rows
		}
		expected = {
			field.get("label") or field["fieldname"]
			for field in doc["fields"]
			if field["fieldtype"] not in SKIP_FIELDTYPES
		}
		self.assertEqual(expected - documented, set(), "fields missing from the guide")

	def test_the_reference_is_grouped_the_way_the_form_is(self):
		captions = [caption for _kind, (caption, _h, _r) in manual_content.settings_blocks()]
		labels = [
			field.get("label")
			for field in settings_doc()["fields"]
			if field["fieldtype"] == "Section Break" and field.get("label")
		]
		for label in labels:
			self.assertIn(label, captions, f"settings section {label!r} is not in the guide")


class TestStageChapter(unittest.TestCase):
	def test_one_row_per_catalogue_stage(self):
		rows = manual_content.stage_rows()
		self.assertEqual(len(rows), len(approvals.CATALOGUE))
		self.assertEqual([row[0] for row in rows], [s.label for s in approvals.CATALOGUE])

	def test_farm_scoped_stages_are_marked_as_such(self):
		scoped = {s.label for s in approvals.CATALOGUE if s.scoped}
		marked = {row[0] for row in manual_content.stage_rows() if row[5] == "Yes"}
		self.assertEqual(marked, scoped)

	def test_gates_show_no_state_or_action(self):
		for row in manual_content.stage_rows():
			if row[2] != "Gate":
				continue
			self.assertEqual(row[3], "—")
			self.assertEqual(row[4], "—")


class TestStructure(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.blocks = build_manual.numbered(manual_content.sections())

	def test_every_block_has_a_known_kind(self):
		for kind, _payload, _number, _anchor in self.blocks:
			self.assertIn(kind, manual_content.KINDS, kind)

	def test_sections_are_numbered_from_one_without_gaps(self):
		numbers = [int(n) for k, _p, n, _a in self.blocks if k == "h2"]
		self.assertEqual(numbers, list(range(1, len(numbers) + 1)))

	def test_subsections_are_numbered_within_their_section(self):
		current, expected = None, 0
		for kind, _payload, number, _anchor in self.blocks:
			if kind == "h2":
				current, expected = number, 0
			elif kind == "h3":
				expected += 1
				self.assertEqual(number, f"{current}.{expected}")

	def test_anchors_are_unique_so_the_contents_links_resolve(self):
		anchors = [a for _k, _p, _n, a in self.blocks if a]
		self.assertEqual(len(anchors), len(set(anchors)))

	def test_no_subsection_appears_before_its_first_section(self):
		seen_section = False
		for kind, _payload, _number, _anchor in self.blocks:
			if kind == "h2":
				seen_section = True
			elif kind == "h3":
				self.assertTrue(seen_section, "a subsection precedes every section")

	def test_the_guide_has_both_parts(self):
		parts = [payload for kind, payload, _n, _a in self.blocks if kind == "part"]
		self.assertEqual(len(parts), 2)
		self.assertTrue(parts[0].startswith("Part I"))
		self.assertTrue(parts[1].startswith("Part II"))

	def test_tables_have_a_cell_for_every_column(self):
		for kind, payload, _number, _anchor in self.blocks:
			if kind != "table":
				continue
			caption, headers, rows = payload
			for row in rows:
				self.assertEqual(len(row), len(headers), f"{caption}: ragged row {row!r}")

	def test_the_contents_lists_every_section_and_subsection(self):
		toc = build_manual.toc_html(self.blocks)
		for kind, payload, _number, anchor in self.blocks:
			if kind in ("h2", "h3"):
				self.assertIn(f'href="#{anchor}"', toc)


class TestItBuilds(unittest.TestCase):
	def test_the_pdf_renders(self):
		try:
			import weasyprint  # noqa: F401
		except ImportError:
			self.skipTest("WeasyPrint is only in the bench environment")
		blocks = build_manual.numbered(manual_content.sections())
		path = build_manual.build_pdf(blocks)
		self.assertTrue(os.path.exists(path))
		with open(path, "rb") as handle:
			self.assertEqual(handle.read(5), b"%PDF-")
		self.assertGreater(os.path.getsize(path), 50_000)


if __name__ == "__main__":
	unittest.main()
