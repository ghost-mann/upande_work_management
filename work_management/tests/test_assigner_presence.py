"""Today's presence on the assigner is optional, and off unless asked for.

The assigner showed a chip on every worker -- `P · 07:14` when a biometric scan
or submitted attendance said they were on site, `A today` when marked Absent,
`? today` when neither, `night shift` for a shift crossing midnight. It was
unconditional: the comment said "always shown".

A deployment without biometric hardware, or without attendance being kept
current, gets `? today` on every worker -- which reads as information and is not.
So it is a setting, off by default, and off means the three attendance queries do
not run at all.

Everything else on the row is untouched: the name, designation, employment type,
off-days badge, the assigned-elsewhere block, and the warning badge that comes
from the att_block_* checks, which are separate settings and separately useful.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_assigner_presence -v
"""

import json
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLAG = "asg_show_today_presence"


def settings_field(fieldname):
	path = os.path.join(HERE, "work_management", "doctype",
		"work_management_settings", "work_management_settings.json")
	with open(path) as handle:
		for f in json.load(handle).get("fields", []):
			if f.get("fieldname") == fieldname:
				return f
	return None


def ported(module):
	with open(os.path.join(HERE, "api", module + ".py")) as handle:
		return handle.read()


def screen():
	with open(os.path.join(HERE, "public", "js", "work-assigner.js")) as handle:
		return handle.read()


class TestTheSetting(unittest.TestCase):
	def test_it_exists_as_a_checkbox(self):
		self.assertEqual(settings_field(FLAG)["fieldtype"], "Check")

	def test_it_is_off_by_default(self):
		"""A site with no biometric hardware must not be shown '? today' on every
		worker as though that were a finding."""
		self.assertIn(settings_field(FLAG).get("default"), (None, "0", 0))

	def test_it_says_what_it_reads(self):
		"""Employee Checkin and Attendance are somebody else's data; a setting
		that quietly depends on them should say so."""
		description = (settings_field(FLAG).get("description") or "").lower()
		self.assertIn("checkin", description.replace(" ", ""))
		self.assertIn("attendance", description)


class TestTheReadsAreSkippedWhenOff(unittest.TestCase):
	def setUp(self):
		self.src = ported("assigner")

	def test_the_flag_is_read(self):
		self.assertIn(FLAG, self.src)

	def test_the_three_today_queries_are_behind_it(self):
		"""Off should cost nothing, not merely hide the result."""
		block = self.src[self.src.index("scan_map"):][:3000]
		self.assertIn("asg_presence_on", block)

	def test_the_payload_tells_the_screen(self):
		"""The screen cannot guess, and must not render an empty chip."""
		self.assertIn('"show_today"', self.src)


class TestTheScreenRespectsIt(unittest.TestCase):
	def test_the_chip_is_conditional(self):
		self.assertIn("show_today", screen())

	def test_the_rest_of_the_row_is_untouched(self):
		"""The information that has nothing to do with attendance stays."""
		src = screen()
		for kept in ("employee_name", "designation", "employment_type",
		             "allocated_elsewhere", "off_days"):
			self.assertIn(kept, src, kept)

	def test_the_blocking_warnings_are_not_affected(self):
		"""attReasons() comes from att_block_absent / leave / off -- separate
		settings, separately useful, and not what this switch governs."""
		self.assertIn("attReasons", screen())
