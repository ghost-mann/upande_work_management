# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""A note about one worker's day, readable wherever that day is read later.

Asked for by the client: "sent home 11am, rain", "machine down". A short day
with a reason beside it is a fact; the same short day on its own is a query
somebody has to chase a fortnight later, and the person who knew the answer has
forgotten.

Three things make it work, and all three are load-bearing:

    PER WORKER-DAY, not per document. "Sent home 11am" is about one person's
    Tuesday. A note on the actuals document would attach it to everybody on the
    grid -- thirty people, one of whom went home.

    CARRIED, not merely stored. It is read on the worker's review sheet, in the
    Worker Task Day report and in both exports. A note nobody can read later is
    decoration, and the review sheet is where somebody decides whether a day is
    payable.

    EDITABLE WHILE UNPAID. The grid resumes a draft with its notes, an approver
    editing a pending document keeps them, and a locked grid still opens them to
    be read.

    PYTHONPATH=. ~/frappe-bench3/env/bin/python -m unittest \\
        work_management.tests.test_a_note_per_worker_day -v
"""

import json
import os
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ROW = "work_actuals_employee"


def doctype(name):
	path = os.path.join(APP, "work_management", "doctype", name, name + ".json")
	with open(path, encoding="utf-8") as handle:
		return json.load(handle)


def field(name, fieldname):
	for f in doctype(name).get("fields", []):
		if f.get("fieldname") == fieldname:
			return f
	return None


def api(module):
	with open(os.path.join(APP, "api", module + ".py"), encoding="utf-8") as handle:
		return handle.read()


def screen(name):
	with open(os.path.join(APP, "public", "js", name), encoding="utf-8") as handle:
		return handle.read()


def page(name):
	with open(os.path.join(APP, "www", name), encoding="utf-8") as handle:
		return handle.read()


def report():
	path = os.path.join(APP, "work_management", "report", "worker_task_day",
		"worker_task_day.py")
	with open(path, encoding="utf-8") as handle:
		return handle.read()


class TestTheFieldIsOnTheRow(unittest.TestCase):
	"""The child table, which is the per-worker-day grain. Putting it on
	`Work Management Actuals` would make it a note about thirty people."""

	def test_it_exists_on_the_worker_day_row(self):
		self.assertIsNotNone(field(ROW, "note"))

	def test_it_is_free_text(self):
		self.assertEqual(field(ROW, "note")["fieldtype"], "Small Text")

	def test_it_is_optional(self):
		self.assertFalse(field(ROW, "note").get("reqd"))

	def test_it_is_not_read_only(self):
		"""It is entered on the grid and corrected on the grid."""
		self.assertFalse(field(ROW, "note").get("read_only"))

	def test_it_is_not_on_the_document(self):
		"""The trap this design avoids: one note for a grid of thirty people."""
		self.assertIsNone(field("work_management_actuals", "note"))

	def test_it_sits_beside_the_hours(self):
		"""Both describe the shape of the day rather than its output."""
		order = doctype(ROW)["field_order"]
		self.assertEqual(order[order.index("hours") + 1], "note")

	def test_its_description_says_where_it_is_read(self):
		"""A field that promises to be carried should say where to."""
		text = (field(ROW, "note").get("description") or "").lower()
		for place in ("review sheet", "worker task day", "excel"):
			with self.subTest(place=place):
				self.assertIn(place, text)


class TestItTravelsSeparatelyFromTheCells(unittest.TestCase):
	"""The grid posts `emp~date~qty~hours|...`. Free text cannot go in there: a
	comma is fine but a `|` splits a row and a `~` moves a quantity into the
	hours column, silently."""

	def setUp(self):
		self.src = api("actuals")

	def test_the_notes_arrive_as_their_own_parameter(self):
		self.assertIn('notes_raw = frappe.form_dict.get("notes")', self.src)

	def test_they_arrive_as_json(self):
		self.assertIn("json.loads(notes_raw)", self.src)

	def test_a_broken_payload_does_not_lose_the_quantities(self):
		"""Somebody typed that grid. A malformed notes blob must cost the notes,
		never the figures beside them."""
		at = self.src.index('notes_raw = frappe.form_dict.get("notes")')
		block = self.src[at:at + 1200]
		self.assertIn("except Exception:", block)
		self.assertIn("cell_note = {}", block)

	def test_the_screen_sends_it_the_same_way(self):
		js = screen("work-actuals.js")
		self.assertIn("args.notes=JSON.stringify(notes)", js)

	def test_the_screen_keys_a_note_as_it_keys_a_cell(self):
		"""One key shape, or the two halves of a row stop meeting."""
		js = screen("work-actuals.js")
		self.assertIn("ST.notes[ck(w.employee,iso)]", js)
		self.assertIn('function ck(emp,date){ return emp+"~"+date; }', js)


class TestItIsSavedWithTheRow(unittest.TestCase):
	def setUp(self):
		self.src = api("actuals")

	def test_the_row_takes_the_note_for_its_own_worker_and_date(self):
		self.assertIn('row.note = cell_note.get(emp + "~" + str(wdate)) or None', self.src)

	def test_an_absent_note_is_none_rather_than_empty(self):
		"""`or None`: an empty string would overwrite a note an approver had
		already typed, on every save."""
		at = self.src.index("row.note = cell_note.get")
		self.assertIn("or None", self.src[at:at + 120])

	def test_a_note_with_no_recorded_day_is_reported_not_dropped(self):
		"""Only a cell with a quantity becomes a row, so a note against an empty
		cell has nothing to live on. Somebody typed it; silence is the wrong
		answer."""
		self.assertIn('out["notes_dropped_warning"]', self.src)

	def test_the_length_is_bounded_at_the_server(self):
		"""The column is a Small Text and the report prints it in a cell."""
		self.assertIn("nt[:500]", self.src)


class TestItComesBackToTheGrid(unittest.TestCase):
	"""Editable while the row is unpaid means the grid has to resume with what is
	already there -- otherwise the next save silently clears every note."""

	def setUp(self):
		self.src = api("actuals")

	def test_a_resumed_draft_carries_its_notes(self):
		self.assertIn("SELECT employee, work_date, actual_quantity, hours, note", self.src)
		self.assertIn('a["cell_notes"] = cell_notes', self.src)

	def test_a_locked_grid_still_shows_them(self):
		"""After submit there is no draft to read, and this is the screen where
		the note was collected."""
		at = self.src.index('a["live_state"] = live[0].workflow_state if live else None')
		block = self.src[at:at + 900]
		self.assertIn("if live and not draft:", block)
		self.assertIn("IFNULL(note, '') != ''", block)

	def test_the_screen_loads_them_into_the_grid(self):
		js = screen("work-actuals.js")
		self.assertEqual(js.count("ST.notes = a.cell_notes || {};"), 2)

	def test_the_screen_clears_them_when_it_clears_the_cells(self):
		"""Three places reset the grid; a note left behind would attach itself to
		the next assignment opened."""
		js = screen("work-actuals.js")
		self.assertEqual(js.count("ST.notes={}"), 3)


class TestTheGridOffersIt(unittest.TestCase):
	def setUp(self):
		self.js = screen("work-actuals.js")
		self.html = page("work-actuals.html")

	def test_every_cell_carries_the_marker(self):
		self.assertIn('data-nemp="', self.js)
		self.assertIn('data-ndate="', self.js)

	def test_the_marker_says_whether_there_is_anything_to_read(self):
		"""`·` against an empty day and `✎` against one with a note, so the grid
		can be scanned for explanations without opening thirty dialogs."""
		self.assertIn('(nval?" has":"")', self.js)
		self.assertIn("#acp table.grid td.dcell button.ncell.has", self.html)

	def test_it_uses_the_same_dialog_as_the_other_four(self):
		"""Five dialogs on one screen should not be five shapes -- the rule
		test_adding_crew established when it replaced two browser prompts."""
		at = self.html.index('id="ac-notemodal"')
		window = self.html[at:at + 1800]
		for part in ("submodal-card", "submodal-head", "submodal-body", "submodal-foot"):
			with self.subTest(part=part):
				self.assertIn(part, window)

	def test_it_is_not_a_browser_prompt(self):
		self.assertNotIn("window.prompt", self.js)

	def test_a_locked_grid_opens_it_read_only(self):
		at = self.js.index("function openNoteModal(")
		block = self.js[at:at + 1600]
		self.assertIn("ta.readOnly = !!locked;", block)
		self.assertIn('el("ac-note-go").style.display = locked ? "none" : "";', block)

	def test_clearing_the_box_removes_the_note(self):
		"""There is no separate delete, because "clear the box" is what somebody
		reaches for."""
		at = self.js.index("function saveNoteModal(")
		block = self.js[at:at + 900]
		self.assertIn("delete ST.notes[key];", block)

	def test_the_legend_mentions_it(self):
		at = self.js.index("<span><b style=\"color:#bbb\">·</b> rest day / holiday</span>")
		block = self.js[at:self.js.index("'</div>'+", at)]
		self.assertIn("note", block)


class TestItIsReadOnTheReviewSheet(unittest.TestCase):
	"""Where somebody decides whether a day is payable."""

	def test_the_daily_log_selects_it(self):
		src = api("payment")
		at = src.index("SELECT ac.name actuals, we.name rowname, we.work_date wdate")
		self.assertIn("we.note note", src[at:at + 1200])

	def test_the_daily_log_returns_it(self):
		self.assertIn('"note": (r.note or "").strip() or None,', api("payment"))

	def test_the_sheet_prints_a_note_column(self):
		js = screen("work-payment.js")
		at = js.index("'<th>Day worked</th><th class=\"c\">Presence</th>")
		self.assertIn("<th>Note</th>", js[at:at + 400])

	def test_the_footer_still_spans_the_table(self):
		"""A column added without widening the colspan leaves the totals row a
		cell short and the table visibly crooked."""
		js = screen("work-payment.js")
		at = js.index("'<th>Day worked</th><th class=\"c\">Presence</th>")
		block = js[at:at + 3000]
		self.assertIn("colspan=\"3\"", block)
		self.assertNotIn("colspan=\"2\"", block)


class TestItIsInBothExports(unittest.TestCase):
	def setUp(self):
		self.js = screen("work-payment.js")

	def test_the_excel_sheet_has_the_column(self):
		self.assertIn('"Paid","Run","Note"', self.js)

	def test_the_excel_rows_carry_it(self):
		at = self.js.index('"Paid","Run","Note"')
		self.assertIn("r.note||\"\"", self.js[at:at + 900])

	def test_the_excel_columns_are_widened_for_it(self):
		"""Eight headers and six widths leaves the prose column unreadable."""
		at = self.js.index('ws2["!cols"]=')
		line = self.js[at:self.js.index("\n", at)]
		self.assertEqual(line.count("wch:"), 8)

	def test_the_csv_fallback_carries_it_too(self):
		"""The fallback runs when the spreadsheet library fails to load -- the
		reader has no less need of the explanation for that."""
		at = self.js.index("function exportWorkerCSV(")
		self.assertIn('Note:r.note||""', self.js[at:at + 900])


class TestItIsInTheWorkerTaskDayReport(unittest.TestCase):
	"""A Script Report's Excel and CSV export carry every column, so the column
	and the export are one change."""

	def setUp(self):
		self.src = report()

	def test_the_query_selects_it(self):
		self.assertIn("we.note,", self.src)

	def test_the_row_projection_returns_it(self):
		self.assertIn('"note": (str(r.get("note") or "").strip() or None),', self.src)

	def test_there_is_a_column_for_it(self):
		self.assertIn('{"fieldname": "note", "label": "Note"', self.src)

	def test_an_empty_note_is_empty_rather_than_a_blank_string(self):
		"""So the exported column is empty cells, not a column of "" ."""
		at = self.src.index('"note": (str(r.get("note")')
		self.assertIn("or None", self.src[at:at + 80])

	def test_it_is_the_last_column(self):
		"""Prose, usually empty, and read only once a figure above it has made
		somebody ask why."""
		at = self.src.index("COLUMNS = [")
		block = self.src[at:self.src.index("def _columns()", at)]
		self.assertLess(block.index('"fieldname": "workflow_state"'),
			block.index('"fieldname": "note"'))


if __name__ == "__main__":
	unittest.main()
