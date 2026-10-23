"""The payroll pack recipients are seeded only where Kaitet exists, and never over a list someone set."""

import unittest

from work_management.patches.v1_0.seed_payroll_pack_recipients import seed_values

BLANK = {"payroll_pack_enabled": 0, "payroll_pack_sender": "", "payroll_pack_to": "", "payroll_pack_bcc": ""}


class TestSeedPayrollPackRecipients(unittest.TestCase):
	def test_other_sites_untouched(self):
		self.assertIsNone(seed_values(False, dict(BLANK)))

	def test_kaitet_blank_gets_everything(self):
		self.assertEqual(
			seed_values(True, dict(BLANK)),
			{
				"payroll_pack_enabled": 0,
				"payroll_pack_sender": "notifications@karenroses.com",
				"payroll_pack_to": "bob@karenroses.com\nhro@endebesscoffee.com\npeter@endebesscoffee.com\npkanda@endebesscoffee.com\nkoskey@lokitelaorchards.com\nibett@karenroses.com",
				"payroll_pack_bcc": "austin@upande.com\njeniffer@upande.com\nteresia@upande.com",
			},
		)

	def test_existing_list_is_never_overwritten(self):
		current = dict(BLANK, payroll_pack_to="someone@example.com")
		result = seed_values(True, current)
		self.assertNotIn("payroll_pack_to", result)
		self.assertIn("payroll_pack_bcc", result)

	def test_the_pack_arrives_switched_off(self):
		"""Nothing mails pay until someone has seen a test send and ticks the box."""
		current = dict(BLANK, payroll_pack_enabled=1, payroll_pack_to="a@b.c", payroll_pack_sender="x@y.z", payroll_pack_bcc="q@r.s")
		self.assertEqual(seed_values(True, current), {"payroll_pack_enabled": 0})
