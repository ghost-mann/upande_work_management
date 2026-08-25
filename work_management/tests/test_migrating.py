"""Guards on the two helpers that keep a migrate on its feet.

Pure: callables in, notes out. No site, no database::

    ./env/bin/python -m unittest work_management.tests.test_migrating -v
"""

import contextlib
import io
import unittest

from work_management import migrating


@contextlib.contextmanager
def quiet():
	"""The notes are printed and logged on purpose; swallow them so a passing
	run stays quiet and a real failure still stands out."""
	noise = io.StringIO()
	with contextlib.redirect_stdout(noise), contextlib.redirect_stderr(noise):
		yield


class TestEachWithoutAborting(unittest.TestCase):
	def test_every_record_is_worked_when_nothing_fails(self):
		worked = []
		done, notes = migrating.each_without_aborting(
			["Alpha", "Bravo", "Charlie"], worked.append, "create the farm"
		)
		self.assertEqual(worked, ["Alpha", "Bravo", "Charlie"])
		self.assertEqual(done, 3)
		self.assertEqual(notes, [])

	def test_one_record_that_cannot_be_worked_does_not_stop_the_rest(self):
		"""The whole point: one bad legacy value must not abort a site's migrate."""
		worked = []

		def work(item):
			if item == "Bravo":
				raise ValueError("mandatory field farm_name is not set")
			worked.append(item)

		with quiet():
			done, notes = migrating.each_without_aborting(
				["Alpha", "Bravo", "Charlie"], work, "create the farm"
			)
		self.assertEqual(worked, ["Alpha", "Charlie"])
		self.assertEqual(done, 2)
		self.assertEqual(len(notes), 1)

	def test_the_note_names_the_record_that_failed(self):
		"""Migrate output has to say which record, or nobody can go fix it."""
		def work(item):
			raise ValueError("mandatory field farm_name is not set")

		with quiet():
			_done, notes = migrating.each_without_aborting(["Torongo"], work, "create the farm")
		self.assertIn("Torongo", notes[0])
		self.assertIn("create the farm", notes[0])
		self.assertIn("ValueError", notes[0])
		self.assertIn("mandatory field farm_name is not set", notes[0])

	def test_an_empty_run_reports_nothing_done_and_nothing_failed(self):
		self.assertEqual(migrating.each_without_aborting([], print, "create the farm"), (0, []))
