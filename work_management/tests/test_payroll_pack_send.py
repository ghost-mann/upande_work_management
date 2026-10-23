"""Guards on sending the payroll approval pack: who gets what, and when.

This is pay data, so a wrong recipient is the worst thing that can happen. The
frappe calls are mocked; nothing here needs a site or sends mail::

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_payroll_pack_send -v
"""

import unittest
from unittest import mock

from work_management import payroll_pack
from work_management.payroll_pack import should_send

ENTRY = "HR-PRUN-2026-00042"

ENTRIES = [{"name": ENTRY, "start_date": "2026-10-12", "end_date": "2026-10-18",
	"workflow_state": "Pending Accounts"}]


def line(employee, name, farm, amount):
	return {"wmpay": "WMPAY-1", "employee": employee, "employee_name": name, "farm": farm,
		"task": "Picking", "block": "B1", "work_from": "2026-10-12", "work_to": "2026-10-16",
		"days": 2, "qty": 20, "rate": 10, "amount": amount, "entered_by": "a@x.com",
		"fm_approved_by": "fm@x.com", "hr_approved_by": "hr@x.com", "gm_approved_by": "gm@x.com"}


LINES = [line("E1", "Alice", "Vale", 300), line("E2", "Bob", "Endebess", 200)]
SLIPS = [
	{"entry": ENTRY, "slip": "SS1", "employee": "E1", "employee_name": "Alice", "wmpay": "WMPAY-1", "wm_amount": 300},
	{"entry": ENTRY, "slip": "SS2", "employee": "E2", "employee_name": "Bob", "wmpay": "WMPAY-1", "wm_amount": 200},
]
ROWS = (ENTRIES, LINES, SLIPS, {"E1": 2, "E2": 2}, {("E1", "Vale"): 2, ("E2", "Endebess"): 2})

SETTINGS = {
	"payroll_pack_enabled": 1,
	"payroll_pack_sender": "notifications@karenroses.com",
	"payroll_pack_to": "gm@kaitet.com\nfd@kaitet.com",
	"payroll_pack_bcc": "audit@upande.com",
}

STAGE_ROWS = [
	{"stage_label": "Actuals: Farm Manager", "scope": "Vale", "user": "fm.vale@kaitet.com"},
	{"stage_label": "Actuals: Farm Manager", "scope": "Endebess", "user": "fm.endebess@kaitet.com"},
]
ENABLED = ["fm.vale@kaitet.com", "fm.endebess@kaitet.com"]


class Sending:
	"""Patches every frappe call send_pack makes, and records the mail."""

	def __init__(self, settings=None, stage_rows=STAGE_ROWS, enabled=ENABLED, already_sent=False, rows=ROWS):
		self.settings = dict(SETTINGS, **(settings or {}))
		self.stage_rows = stage_rows
		self.enabled = enabled
		self.already_sent = already_sent
		self.rows = rows

	def __enter__(self):
		self.patches = [
			mock.patch.object(payroll_pack, "load_rows", return_value=self.rows),
			mock.patch.object(payroll_pack, "_stage_rows", return_value=self.stage_rows),
			mock.patch.object(payroll_pack, "_enabled_users", side_effect=lambda users: [u for u in users if u in self.enabled]),
			mock.patch.object(payroll_pack, "_record", return_value="COMM-1"),
			mock.patch.object(payroll_pack, "frappe"),
		]
		mocks = [p.start() for p in self.patches]
		self.record, self.frappe = mocks[3], mocks[4]
		self.frappe.db.get_single_value.side_effect = lambda doctype, field: self.settings.get(field)
		self.frappe.db.exists.return_value = "COMM-0" if self.already_sent else None
		self.frappe.utils.get_url_to_form.return_value = "https://x/app/payroll-entry/" + ENTRY
		self.frappe.get_traceback.return_value = "trace"
		return self

	def __exit__(self, *exc):
		for p in self.patches:
			p.stop()

	@property
	def mails(self):
		return [c.kwargs for c in self.frappe.sendmail.call_args_list]


class TestShouldSend(unittest.TestCase):
	def test_the_one_case_that_sends(self):
		self.assertTrue(should_send("Kaitet Ltd.", True, "Pending Accounts", True, True))

	def test_each_condition_alone_stops_it(self):
		for args in [
			("Karen Roses", True, "Pending Accounts", True, True),
			("Kaitet Ltd.", False, "Pending Accounts", True, True),
			("Kaitet Ltd.", True, "Pending GM", True, True),
			("Kaitet Ltd.", True, "Pending Accounts", False, True),
			("Kaitet Ltd.", True, "Pending Accounts", True, False),
		]:
			with self.subTest(args=args):
				self.assertFalse(should_send(*args))


class TestHook(unittest.TestCase):
	def doc(self, company="Kaitet Ltd.", state="Pending Accounts", changed=True):
		doc = mock.Mock(company=company, workflow_state=state)
		doc.name = ENTRY
		doc.has_value_changed.return_value = changed
		return doc

	def test_hook_enqueues_after_commit(self):
		with mock.patch.object(payroll_pack, "frappe") as frappe, \
				mock.patch.object(payroll_pack, "has_task_pay", return_value=True):
			frappe.db.get_single_value.return_value = 1
			payroll_pack.on_payroll_entry_update(self.doc())
		frappe.enqueue.assert_called_once()
		args, kwargs = frappe.enqueue.call_args
		self.assertEqual(args[0], "work_management.payroll_pack.send_pack")
		self.assertTrue(kwargs["enqueue_after_commit"])
		self.assertEqual(kwargs["entry_name"], ENTRY)
		self.assertEqual(kwargs["queue"], "long")

	def test_hook_does_nothing_for_another_state_or_when_switched_off(self):
		for doc, enabled in [(self.doc(state="Pending GM"), 1), (self.doc(), 0), (self.doc(), None),
				(self.doc(changed=False), 1), (self.doc(company="Karen Roses"), 1)]:
			with self.subTest(state=doc.workflow_state, enabled=enabled), \
					mock.patch.object(payroll_pack, "frappe") as frappe, \
					mock.patch.object(payroll_pack, "has_task_pay", return_value=True):
				frappe.db.get_single_value.return_value = enabled
				payroll_pack.on_payroll_entry_update(doc)
			frappe.enqueue.assert_not_called()

	def test_hook_does_nothing_without_task_pay(self):
		with mock.patch.object(payroll_pack, "frappe") as frappe, \
				mock.patch.object(payroll_pack, "has_task_pay", return_value=False):
			frappe.db.get_single_value.return_value = 1
			payroll_pack.on_payroll_entry_update(self.doc())
		frappe.enqueue.assert_not_called()


class TestSendPack(unittest.TestCase):
	def test_first_send_is_not_revised(self):
		with Sending() as s:
			payroll_pack.send_pack(ENTRY)
		full = s.mails[0]
		self.assertEqual(full["subject"], f"Task pay for approval — {ENTRY} — KES 500")
		self.assertEqual(full["recipients"], ["gm@kaitet.com", "fd@kaitet.com"])
		self.assertEqual(full["bcc"], ["audit@upande.com"])
		self.assertEqual(full["sender"], "notifications@karenroses.com")
		self.assertEqual(full["reference_doctype"], "Payroll Entry")
		self.assertEqual(full["reference_name"], ENTRY)
		self.assertEqual(full["attachments"][0]["fname"], "Task-pay-2026-10-12-to-2026-10-18.xlsx")
		self.assertIsInstance(full["attachments"][0]["fcontent"], bytes)

	def test_second_send_is_revised(self):
		with Sending(already_sent=True) as s:
			payroll_pack.send_pack(ENTRY)
		self.assertTrue(all(m["subject"].startswith("Revised: Task pay for approval") for m in s.mails))
		# The check is the brief's: same entry, the pack's subject, and not a test.
		filters = s.frappe.db.exists.call_args.args[1]
		self.assertIn(["reference_doctype", "=", "Payroll Entry"], filters)
		self.assertIn(["reference_name", "=", ENTRY], filters)
		self.assertIn(["subject", "like", "%Task pay for approval%"], filters)
		self.assertIn(["subject", "not like", "TEST:%"], filters)
		self.assertIn(["communication_type", "=", "Communication"], filters)

	def test_each_farm_manager_gets_only_their_farm(self):
		with Sending() as s:
			result = payroll_pack.send_pack(ENTRY)
		by_to = {tuple(m["recipients"]): m for m in s.mails}
		vale = by_to[("fm.vale@kaitet.com",)]
		endebess = by_to[("fm.endebess@kaitet.com",)]
		self.assertIn("Vale", vale["subject"])
		self.assertIn("KES 300", vale["subject"])
		self.assertNotIn("Bob", vale["message"])
		self.assertIn("Endebess", endebess["subject"])
		self.assertIn("KES 200", endebess["subject"])
		self.assertFalse(vale.get("bcc"))
		self.assertFalse(endebess.get("bcc"))
		self.assertEqual(vale["attachments"][0]["fname"], "Task-pay-2026-10-12-to-2026-10-18-Vale.xlsx")
		self.assertEqual(len(s.mails), 3)
		self.assertEqual(len(result["sent"]), 3)

	def test_real_sends_are_recorded_so_the_next_one_is_revised(self):
		with Sending() as s:
			payroll_pack.send_pack(ENTRY)
		self.assertEqual(s.record.call_count, 3)
		self.assertTrue(all(m["communication"] == "COMM-1" for m in s.mails))

	def test_test_send_goes_only_to_test_recipients(self):
		test = ["hro@endebesscoffee.com", "austin@upande.com"]
		with Sending() as s:
			result = payroll_pack.send_pack(ENTRY, test)
		self.assertEqual(len(s.mails), 3)  # full pack + Vale + Endebess
		for m in s.mails:
			self.assertEqual(m["recipients"], test)
			self.assertFalse(m.get("bcc"))
			self.assertTrue(m["subject"].startswith("TEST: "))
			self.assertNotIn("communication", m)
		s.record.assert_not_called()
		self.assertTrue(all(r["to"] == test for r in result["sent"]))

	def test_an_empty_test_list_sends_nothing_rather_than_the_real_list(self):
		with Sending() as s:
			payroll_pack.send_pack(ENTRY, [])
		s.frappe.sendmail.assert_not_called()

	def test_farm_without_fm_is_named_in_the_full_body_and_gets_no_mail(self):
		with Sending(stage_rows=STAGE_ROWS[:1]) as s:
			result = payroll_pack.send_pack(ENTRY)
		self.assertEqual(len(s.mails), 2)
		self.assertIn("No farm manager is set up for: Endebess", s.mails[0]["message"])
		self.assertNotIn("fm.endebess@kaitet.com", str(s.mails))
		self.assertTrue(any("Endebess" in str(x) for x in result["skipped"]))

	def test_a_disabled_farm_manager_gets_no_mail(self):
		with Sending(enabled=["fm.vale@kaitet.com"]) as s:
			payroll_pack.send_pack(ENTRY)
		self.assertNotIn("fm.endebess@kaitet.com", str(s.mails))
		self.assertIn("No farm manager is set up for: Endebess", s.mails[0]["message"])

	def test_no_approver_list_sends_no_full_pack_and_logs(self):
		with Sending(settings={"payroll_pack_to": ""}) as s:
			payroll_pack.send_pack(ENTRY)
		self.assertNotIn(["gm@kaitet.com", "fd@kaitet.com"], [m["recipients"] for m in s.mails])
		self.assertFalse(any(m.get("bcc") for m in s.mails))
		self.assertTrue(all(m["recipients"][0].startswith("fm.") for m in s.mails))
		s.frappe.log_error.assert_called()

	def test_a_failure_is_logged_and_swallowed_on_a_real_send(self):
		with Sending() as s:
			s.frappe.sendmail.side_effect = RuntimeError("smtp down")
			payroll_pack.send_pack(ENTRY)
		s.frappe.log_error.assert_called_with(title="Payroll approval pack failed", message="trace")

	def test_a_failure_is_raised_on_a_test_send(self):
		with Sending() as s:
			s.frappe.sendmail.side_effect = RuntimeError("smtp down")
			with self.assertRaises(RuntimeError):
				payroll_pack.send_pack(ENTRY, ["austin@upande.com"])
		s.frappe.log_error.assert_called_with(title="Payroll approval pack failed", message="trace")


class TestSendTestPack(unittest.TestCase):
	def test_only_system_managers_and_addresses_are_split(self):
		with mock.patch.object(payroll_pack, "frappe") as frappe, \
				mock.patch.object(payroll_pack, "send_pack", return_value={"sent": [], "skipped": []}) as send:
			payroll_pack.send_test_pack(ENTRY, "a@x.com, b@x.com,a@x.com")
		frappe.only_for.assert_called_once_with("System Manager")
		send.assert_called_once_with(ENTRY, ["a@x.com", "b@x.com"])

	def test_no_addresses_is_refused(self):
		with mock.patch.object(payroll_pack, "frappe") as frappe, \
				mock.patch.object(payroll_pack, "send_pack") as send:
			frappe.throw.side_effect = ValueError("no recipients")
			with self.assertRaises(ValueError):
				payroll_pack.send_test_pack(ENTRY, " , ")
		send.assert_not_called()


class TestLoadRows(unittest.TestCase):
	def test_queries_are_parameterised_and_shapes_match_the_builder(self):
		calls = []

		def sql(query, values=None, as_dict=False):
			calls.append((query, values))
			q = " ".join(query.split())
			if "from `tabPayroll Entry`" in q:
				return [dict(ENTRIES[0])]
			if "from `tabSalary Slip`" in q:
				return [dict(SLIPS[0]), {"entry": ENTRY, "slip": "SS3", "employee": "E9",
					"employee_name": "Zed", "wmpay": None, "wm_amount": None}]
			if "from `tabWork Payment Line`" in q:
				return [dict(LINES[0])]
			if "group by wae.employee, wma.farm" in q:
				return [{"employee": "E1", "farm": "Vale", "days": 2}]
			if "from `tabWork Actuals Employee`" in q:
				return [{"employee": "E1", "days": 2}]
			raise AssertionError(q)

		with mock.patch.object(payroll_pack, "frappe") as frappe:
			frappe.db.sql.side_effect = sql
			entries, lines, slips, days, days_farm = payroll_pack.load_rows([ENTRY])
		self.assertEqual(entries[0]["name"], ENTRY)
		self.assertEqual(slips[1]["wm_amount"], 0)
		self.assertEqual(days, {"E1": 2})
		self.assertEqual(days_farm, {("E1", "Vale"): 2})
		for query, values in calls:
			self.assertNotIn(ENTRY, query)
			self.assertNotIn("WMPAY-1", query)
			self.assertIsNotNone(values)

	def test_no_slips_means_no_line_queries(self):
		with mock.patch.object(payroll_pack, "frappe") as frappe:
			frappe.db.sql.side_effect = lambda q, v=None, as_dict=False: (
				[dict(ENTRIES[0])] if "`tabPayroll Entry`" in q else [])
			rows = payroll_pack.load_rows([ENTRY])
		self.assertEqual(rows[1:], ([], [], {}, {}))
		self.assertEqual(frappe.db.sql.call_count, 2)


if __name__ == "__main__":
	unittest.main()
