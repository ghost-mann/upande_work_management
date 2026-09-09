"""One payment path at a time, ever.

This app has always paid the same way: work is sent to accounts as a payment
run, accounts marks it paid, and the day-rows are stamped. Altura pays the other
way -- the weekly feed writes each worker's total to Employee.custom_basic_pay
and payroll pays them from the salary structure -- and the feed is then the
TERMINAL payment act, not a report about one.

`payment_mode` in Settings picks the path, defaulting to "Accounts release" so
that a site that migrates changes nothing about how anybody gets paid.

**The two paths must be mutually exclusive, and they are by construction rather
than by rule.** Every eligibility query in api/payment.py carries
`IFNULL(paid,0)=0 AND IFNULL(payment_ref,'')=''`, so once a fed run stamps a
worker's days they cannot also be sent to accounts, and once a sent run claims
them they cannot be fed. Nothing has to remember; the data says it. What the mode
adds is that the OTHER path's controls are gone from the screen and refuse on the
server, because a control that exists to say no is a control somebody presses.

Measured on kentrout.local, week 2026-08-30 → 09-05:

    accounts mode   feed panel can_feed=0, "this project's payment mode is
                    'Accounts release'..."; send to accounts works as it always has
    payroll mode    feed writes 4 runs, each Paid / docstatus 1 / payment_kind
                    "Payroll Feed", 5 day-rows stamped each, custom_basic_pay and
                    the week stamp written; the four accounts actions all refuse
    fed → send      the accounts path offers 0 weeks for that worker
    sent → feed     the worker is excluded and listed: "already sent to accounts
                    as WMPAY-00194"
    cancel          run → Cancelled/docstatus 2, 5 day-rows back to unpaid,
                    custom_basic_pay cleared, and the week feedable again

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_payment_mode -v
"""

import json
import os
import re
import unittest

from work_management.api.config import (ACCOUNTS_KIND, ACCOUNTS_RELEASE, FEED_KIND,
	PAYROLL_FEED)

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAYMENT = os.path.join(APP, "api", "payment.py")
PAYROLL = os.path.join(APP, "api", "payroll.py")
CONFIG = os.path.join(APP, "api", "config.py")
SCREEN = os.path.join(APP, "public", "js", "work-payment.js")
MARKUP = os.path.join(APP, "www", "work-payment.html")
SETTINGS = os.path.join(APP, "work_management", "doctype",
	"work_management_settings", "work_management_settings.json")
RUN = os.path.join(APP, "work_management", "doctype",
	"work_management_payment", "work_management_payment.json")


def read(path):
	with open(path) as handle:
		return handle.read()


def fields(path):
	return {f["fieldname"]: f for f in json.load(open(path))["fields"]}


class TestTheSwitch(unittest.TestCase):
	def setUp(self):
		self.field = fields(SETTINGS).get("payment_mode")

	def test_it_exists_and_offers_exactly_two_paths(self):
		self.assertIsNotNone(self.field)
		self.assertEqual(self.field["fieldtype"], "Select")
		self.assertEqual(self.field["options"].split("\n"),
			[ACCOUNTS_RELEASE, PAYROLL_FEED])

	def test_it_defaults_to_the_path_every_existing_site_runs(self):
		"""A migrate must not change how anybody gets paid."""
		self.assertEqual(self.field.get("default"), ACCOUNTS_RELEASE)

	def test_it_is_on_the_form(self):
		self.assertIn("payment_mode", json.load(open(SETTINGS))["field_order"])

	def test_nothing_said_reads_as_accounts_release(self):
		"""An unset Select on an existing Single is an empty string, and the safe
		reading of "nothing said" is the path the site was already running."""
		src = read(CONFIG)
		self.assertIn('"payment_mode": ACCOUNTS_RELEASE', src)
		self.assertIn('if settings.get("payment_mode") == PAYROLL_FEED:', src)

	def test_the_two_values_are_spelled_once(self):
		"""Eight places compare against these. A typo in one would silently put a
		site on the other path, which is money."""
		src = read(CONFIG)
		self.assertIn('ACCOUNTS_RELEASE = "Accounts release"', src)
		self.assertIn('PAYROLL_FEED = "Payroll feed"', src)
		for path in (PAYMENT, PAYROLL):
			with self.subTest(module=os.path.basename(path)):
				body = read(path)
				self.assertNotIn('"Payroll feed"', body,
					"compare against config.PAYROLL_FEED, not a repeated literal")


class TestWhatARunRecordsAboutItself(unittest.TestCase):
	def setUp(self):
		self.field = fields(RUN).get("payment_kind")

	def test_the_field_exists(self):
		self.assertIsNotNone(self.field)
		self.assertEqual(self.field["fieldtype"], "Select")

	def test_it_names_both_paths(self):
		self.assertEqual(self.field["options"].split("\n"), [ACCOUNTS_KIND, FEED_KIND])

	def test_it_is_read_only(self):
		"""It records how a run was made, which is not a thing to edit."""
		self.assertTrue(self.field.get("read_only"))

	def test_empty_means_accounts_release(self):
		"""Every run written before the field existed. Nothing else could have
		made them, and a migrate must not rewrite history to say so."""
		self.assertIn("EMPTY on every run", self.field.get("description") or "")

	def test_the_feed_stamps_the_kind(self):
		at = read(PAYMENT).index("def payroll_feed_run(")
		block = read(PAYMENT)[at:at + 6000]
		self.assertIn('"payment_kind": FEED_KIND', block)


class TestTheFeedIsTheTerminalPaymentAct(unittest.TestCase):
	def setUp(self):
		self.src = read(PAYMENT)
		at = self.src.index("def payroll_feed_run(")
		self.block = self.src[at:self.src.index("@frappe.whitelist()", at)]

	def test_the_run_is_created_already_paid(self):
		"""There is no accounts step to wait for."""
		self.assertIn('"workflow_state": "Paid"', self.block)
		self.assertIn('"docstatus": 1', self.block)

	def test_the_day_rows_are_stamped_paid_in_the_same_breath(self):
		"""Exactly what pay_mark_paid does at the end of the accounts path."""
		self.assertIn('"payment_ref": doc.name', self.block)
		self.assertIn('"paid": 1', self.block)

	def test_it_is_one_run_per_worker(self):
		self.assertIn("doc.total_workers = 1", self.block)
		self.assertIn("doc.employee = employee", self.block)

	def test_it_uses_the_payment_run_s_own_eligibility(self):
		"""So the total on a fed run equals the total the panel previewed."""
		self.assertIn("EARNINGS_CONDITIONS", self.block)
		self.assertIn('task_worker_sql("we")', self.block)

	def test_it_carries_the_same_accountability_chain_as_an_accounts_run(self):
		for field in ("line.assigned_by", "line.fm_approved_by", "line.entered_by",
				"line.hr_approved_by", "line.gm_approved_by", "line.actuals"):
			with self.subTest(field=field):
				self.assertIn(field, self.block)

	def test_the_accounts_path_writes_the_same_line_fields(self):
		"""The two are deliberately separate code -- the accounts path is what
		every existing site runs and this release must not touch it -- so a test
		holds them to the same shape instead."""
		legacy = self.src[self.src.index('elif action == "pay_worker_submit":'):]
		legacy = legacy[:legacy.index("elif action ==", 40)]
		for field in ("assigned_by", "fm_approved_by", "entered_by",
				"hr_approved_by", "gm_approved_by", "paid_workers"):
			with self.subTest(field=field):
				self.assertIn("row." + field, legacy)
				self.assertIn("line." + field, self.block)

	def test_a_worker_with_nothing_payable_gets_no_run(self):
		self.assertIn("if not rows or total <= 0:", self.block)
		self.assertIn("return None", self.block)


class TestItIsAllOrNothingPerWorker(unittest.TestCase):
	"""Half a feed is worse than none: a stamped row with no figure is unpaid
	work nobody can find, and a figure with no run is money with no evidence."""

	def setUp(self):
		src = read(PAYROLL)
		at = src.index("def feed_write(")
		self.block = src[at:src.index("def _write_basic_pay(")]

	def test_each_worker_is_wrapped_in_a_savepoint(self):
		self.assertIn("frappe.db.savepoint(point)", self.block)
		self.assertIn("frappe.db.rollback(save_point=point)", self.block)

	def test_the_run_and_the_figure_are_inside_it_together(self):
		at = self.block.index("frappe.db.savepoint(point)")
		inside = self.block[at:self.block.index("except Exception", at)]
		self.assertIn("payroll_feed_run(", inside)
		self.assertIn("_write_basic_pay(", inside)

	def test_one_worker_failing_does_not_stop_the_others(self):
		self.assertIn("failed.append(", self.block)
		self.assertIn('plan["failed"] = failed', self.block)

	def test_the_run_that_paid_them_is_named_on_the_employee_comment(self):
		src = read(PAYROLL)
		at = src.index("def _write_basic_pay(")
		self.assertIn("payment run", src[at:at + 1400])

	def test_no_run_is_created_in_accounts_mode(self):
		"""The feed still writes custom_basic_pay there? No -- it cannot run at
		all: can_feed is false. But the flag is what makes that structural."""
		self.assertIn("feeding = get_config().get(\"payment_mode\") == PAYROLL_FEED",
			self.block)


class TestTheOtherPathIsShut(unittest.TestCase):
	def setUp(self):
		self.src = read(PAYMENT)
		self.js = read(SCREEN)

	def test_every_accounts_action_is_named(self):
		at = self.src.index("ACCOUNTS_ACTIONS = (")
		block = self.src[at:at + 400]
		for act in ("pay_submit", "pay_worker_submit", "pay_bulk_submit", "pay_mark_paid"):
			with self.subTest(action=act):
				self.assertIn('"%s"' % act, block)

	def test_the_guard_runs_before_any_of_them(self):
		"""An elif chain, so position is the whole of what makes it a guard."""
		guard = self.src.index("elif action in ACCOUNTS_ACTIONS and payment_mode() == PAYROLL_FEED:")
		for act in ("pay_submit", "pay_worker_submit", "pay_bulk_submit", "pay_mark_paid"):
			with self.subTest(action=act):
				self.assertLess(guard, self.src.index('elif action == "%s"' % act))

	def test_the_refusal_says_what_to_do_instead(self):
		at = self.src.index("elif action in ACCOUNTS_ACTIONS")
		self.assertIn("feed the week", self.src[at:at + 700])

	def test_the_screen_asks_the_mode_once_at_boot(self):
		self.assertIn("ST.paysByFeed=!!d.pays_by_feed", self.js)
		self.assertIn('out["pays_by_feed"]', self.src)

	def test_the_send_buttons_are_absent_rather_than_refusing(self):
		"""A button that exists to say no is a button somebody presses."""
		self.assertIn("if(!ST.paysByFeed)\n          acts+=' <button", self.js)
		self.assertIn("ST.canSend=!!d.can_send && !ST.paysByFeed", self.js)

	def test_mark_paid_goes_too(self):
		self.assertIn("if(canPay && !ST.paysByFeed){", self.js)

	def test_the_release_queue_is_hidden_and_the_tab_renamed(self):
		self.assertIn('id="acc-queue-wrap"', read(MARKUP))
		at = self.js.index("function applyPaymentMode(")
		block = self.js[at:at + 900]
		self.assertIn('el("acc-queue-wrap")', block)
		self.assertIn('tab.textContent="Payroll"', block)

	def test_the_queue_is_not_even_loaded(self):
		self.assertIn('if(!ST.paysByFeed) loadAccounts();', self.js)

	def test_the_review_sheet_stops_promising_an_accounts_step(self):
		self.assertIn("Paid via payroll feed", self.js)
		self.assertIn("Included in the next payroll feed", self.js)

	def test_that_copy_is_gated_on_the_server_s_answer(self):
		"""Not on a guess the screen makes for itself."""
		at = self.js.index("Paid via payroll feed")
		self.assertIn("ST.paysByFeed", self.js[at - 400:at])

	def test_editing_unpaid_rows_is_untouched(self):
		"""Review-sheet correction is not part of either payment path."""
		self.assertIn("pay_worker_edit_day", self.js)
		self.assertIn('elif action == "pay_worker_edit_day":', self.src)


class TestTheExclusionIsVisibleFromBothSides(unittest.TestCase):
	def setUp(self):
		self.payment = read(PAYMENT)
		self.payroll = read(PAYROLL)

	def test_a_claimed_row_is_ineligible_for_either_path(self):
		"""The exclusion itself: one condition, in the constant both paths use."""
		at = self.payment.index("EARNINGS_CONDITIONS = ")
		block = self.payment[at:at + 400]
		self.assertIn("IFNULL(we.paid,0)=0", block)
		self.assertIn("IFNULL(we.payment_ref,'')=''", block)

	def test_a_sent_worker_is_reported_rather_than_vanishing(self):
		""""Where did Brian go" is a question the panel has to be able to
		answer."""
		self.assertIn("def weekly_spoken_for(", self.payment)
		self.assertIn("weekly_spoken_for(", self.payroll)
		self.assertIn("already sent to accounts as ", self.payroll)

	def test_and_a_fed_one_says_which_run_paid_them(self):
		self.assertIn("paid by payroll feed ", self.payroll)

	def test_the_lookup_uses_the_same_grain_as_the_feed(self):
		at = self.payment.index("def weekly_spoken_for(")
		block = self.payment[at:at + 2200]
		self.assertIn("ac.workflow_state='CONFIRMED'", block)
		self.assertIn("IFNULL(we.count_in_payroll,0)=1", block)
		self.assertIn('task_worker_sql("we")', block)


class TestAMisFedWeekIsCorrectable(unittest.TestCase):
	def setUp(self):
		src = read(PAYMENT)
		at = src.index('elif action == "pay_cancel_feed":')
		self.block = src[at:src.index('elif action == "pay_run_withdraw":')]

	def test_it_only_cancels_a_fed_run(self):
		"""An accounts run is returned to unpaid instead, which is a different
		thing: that money was never paid."""
		self.assertIn("cf.payment_kind != FEED_KIND", self.block)
		self.assertIn("return it to", self.block)

	def test_the_day_rows_go_back_to_unpaid(self):
		self.assertIn('"payment_ref": None', self.block)
		self.assertIn('"paid": 0', self.block)

	def test_the_basic_pay_figure_is_cleared(self):
		"""The part that must not be forgotten: custom_basic_pay is read by a
		Salary Structure, so leaving it holding a total whose backing run was
		cancelled pays for work that is now unpaid and back in the queue."""
		self.assertIn("cf_doc.custom_basic_pay = 0", self.block)
		self.assertIn("cf_doc.custom_basic_pay_week = None", self.block)

	def test_only_for_the_week_that_run_paid(self):
		"""A later week's figure is not this run's to clear."""
		self.assertIn("if str(cf_emp or \"\") == cf_stamp:", self.block)

	def test_it_is_a_versioned_save_like_the_feed_s_own_write(self):
		self.assertIn("cf_doc.save(ignore_permissions=True)", self.block)
		self.assertIn("add_comment", self.block)

	def test_the_run_is_kept_as_cancelled_rather_than_deleted(self):
		"""It paid somebody once. Deleting it loses that."""
		self.assertIn('"workflow_state": "Cancelled"', self.block)
		self.assertIn('"docstatus": 2', self.block)

	def test_payroll_having_consumed_it_stops_the_cancel(self):
		self.assertIn("Salary Slip has already paid this", self.block)

	def test_the_screen_offers_it_on_a_fed_run(self):
		js = read(SCREEN)
		self.assertIn("data-cancelfeed=", js)
		self.assertIn('action:"pay_cancel_feed"', js)

	def test_the_screen_says_what_cancelling_does(self):
		js = read(SCREEN)
		at = js.index("data-cancelfeed=")
		self.assertIn("back to unpaid", js[at:at + 1800])


class TestAccountsReleaseModeIsUntouched(unittest.TestCase):
	"""The guardrail on this release: default mode behaves exactly as before."""

	def setUp(self):
		self.payroll = read(PAYROLL)
		self.payment = read(PAYMENT)

	def test_the_feed_refuses_and_says_which_mode(self):
		at = self.payroll.index("if mode != PAYROLL_FEED:")
		block = self.payroll[at:at + 700]
		self.assertIn("payment mode is", block)
		self.assertIn("sending runs to accounts", block)

	def test_the_panel_is_still_there_to_explain_itself(self):
		"""Disabled with a reason, not hidden -- somebody switching a project over
		needs to find it."""
		self.assertIn('id="feed-week"', read(MARKUP))

	def test_the_mode_reason_is_checked_before_everything_else(self):
		at = self.payroll.index("    reason = None")
		block = self.payroll[at:at + 1800]
		self.assertLess(block.index("payment mode is"), block.index("not configured: "))

	def test_no_run_is_created_by_a_feed_in_accounts_mode(self):
		at = self.payroll.index("def feed_write(")
		block = self.payroll[at:self.payroll.index("def _write_basic_pay(")]
		self.assertIn("if feeding:", block)

	def test_the_accounts_actions_are_not_otherwise_changed(self):
		"""The guard is an added branch ahead of them; their own bodies keep the
		conditions they always had."""
		self.assertIn('elif action == "pay_submit" and not CAN_SEND:', self.payment)
		self.assertIn('elif action == "pay_worker_submit" and not CAN_SEND:', self.payment)
		self.assertIn('elif action == "pay_bulk_submit" and not CAN_SEND:', self.payment)
		self.assertIn('if not cur or cur.workflow_state != "Unpaid":', self.payment)


if __name__ == "__main__":
	unittest.main()
