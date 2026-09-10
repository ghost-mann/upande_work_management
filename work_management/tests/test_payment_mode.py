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


class TestNoSurfaceOffersASendInFeedMode(unittest.TestCase):
	"""The sweep, kept as a test.

	Gating the buttons one screenshot at a time is how two of them survived the
	first pass: the review sheet's primary footer button and the Pay workers
	banner both went on describing a step the project has not got. So every place
	the payment screen says "to accounts" is enumerated here, and each has to be
	either inside a `pays_by_feed` branch, downstream of a control that is, or
	named below as deliberately mode-neutral.
	"""

	# Sites that mention the accounts path and SHOULD, whatever the mode.
	# Each is a fact about data that already exists rather than an offer to act.
	MODE_NEUTRAL = (
		# a pay_status VALUE on historical rows -- a run sent before the switch
		# is still "Sent to accounts", and relabelling history would be a lie
		'w.pay_status==="Sent to accounts"',
		'var order={"Unpaid":0,"Sent to accounts":1,"Paid":2}',
		'"In run (awaiting accounts)":"submitted"',
		# a comment on ST.canSend's declaration
		'// only HR head / accounting / GM may send work to accounts',
	)

	def setUp(self):
		self.js = read(SCREEN)
		self.lines = self.js.splitlines()

	def offer_lines(self):
		"""Every line that names the accounts path, minus the neutral ones."""
		out = []
		for i, line in enumerate(self.lines, 1):
			if "to accounts" not in line and "Mark paid" not in line:
				continue
			if any(n in line for n in self.MODE_NEUTRAL):
				continue
			if line.strip().startswith("//"):
				continue
			out.append((i, line.strip()))
		return out

	def test_the_sweep_finds_something(self):
		"""A matcher that matches nothing passes every assertion below."""
		self.assertGreater(len(self.offer_lines()), 8)

	def test_every_send_control_is_gated_or_downstream_of_one(self):
		"""`approveWorker` is the single funnel for the send action and all three
		of its call sites are gated, so the check is that each RENDER site sits in
		a mode branch."""
		gated = ("ST.paysByFeed", "ST.canSend")
		for line_no, line in self.offer_lines():
			if 'data-send="' not in line and 'data-approve="' not in line:
				continue
			window = "\n".join(self.lines[max(0, line_no - 4):line_no])
			with self.subTest(line=line_no):
				self.assertTrue(any(g in window for g in gated),
					"a send control with no mode gate above it at line %d" % line_no)

	def test_the_send_funnel_refuses_in_feed_mode(self):
		at = self.js.index("function approveWorker(")
		block = self.js[at:at + 900]
		self.assertIn("if(ST.paysByFeed){", block)
		self.assertIn("return;", block)

	def test_the_bulk_send_button_is_gated_at_its_source(self):
		self.assertIn('ST.canSend?\'<button type="button" class="btn good sm" id="bulk-send"', self.js)
		self.assertIn("ST.canSend=!!d.can_send && !ST.paysByFeed", self.js)

	def test_mark_paid_is_gated_in_both_places_it_is_offered(self):
		"""The run card on the accounts queue, and the run-detail modal -- which
		is reachable from History and so survives the queue being hidden."""
		self.assertIn("if(canPay && !ST.paysByFeed){", self.js)
		self.assertIn('p.workflow_state==="Unpaid" && ST.isAccounts && !ST.paysByFeed', self.js)

	def test_the_release_queue_is_not_rendered_or_loaded(self):
		self.assertIn('if(!ST.paysByFeed) loadAccounts();', self.js)
		at = self.js.index("function applyPaymentMode(")
		self.assertIn('el("acc-queue-wrap")', self.js[at:at + 900])


class TestTheCopyThatDescribesTheAccountsPath(unittest.TestCase):
	"""A sentence naming a step this project has not got sends the reader looking
	for a button that is deliberately absent."""

	def setUp(self):
		self.js = read(SCREEN)

	def test_the_pay_workers_banner_has_a_feed_variant(self):
		at = self.js.index('id="bulk-hint"')
		block = self.js[at:at + 900]
		self.assertIn("ST.paysByFeed", block)
		self.assertIn("This project pays through the payroll feed", block)
		self.assertIn("feed the week on the Payroll tab", block)

	def test_it_still_has_both_accounts_variants(self):
		"""Can-send and cannot-send were the two states before; they stay."""
		at = self.js.index('id="bulk-hint"')
		block = self.js[at:at + 900]
		self.assertIn("Tick workers to send them to accounts", block)
		self.assertIn("done by the HR head, accounting or the general manager", block)

	def test_the_build_tab_note_has_one(self):
		self.assertIn("ST.paysByFeed\n      ? '<div class=\"note\">Unpaid &rarr; feed the week to payroll", self.js)

	def test_the_audit_workers_hint_has_one(self):
		at = self.js.index("function renderAuditWorkers(")
		block = self.js[at:at + 1200]
		self.assertIn("ST.paysByFeed", block)
		self.assertIn("paid by feeding payroll on the Payroll tab", block)

	def test_the_issues_empty_state_has_one(self):
		"""The four gates it reports block a feed exactly as they block a send, so
		the tab is mode-neutral and only the sentence changes."""
		at = self.js.index("function loadIssues(")
		block = self.js[at:at + 1200]
		self.assertIn("ST.paysByFeed", block)
		self.assertIn("when the week is fed", block)

	def test_the_discrepancy_hint_has_one(self):
		self.assertIn("ST.paysByFeed?'payroll feed':'send to accounts'", self.js)


class TestTheReviewSheetFooterReportsInsteadOfOffering(unittest.TestCase):
	"""The screenshot: "Submit & send KES 1,989.25 to accounts" on a project with
	no accounts step. The footer's job on this path is to say where the money
	stands."""

	def setUp(self):
		self.js = read(SCREEN)
		self.api = read(PAYMENT)
		at = self.js.index('var ap=el("pd-approve"), rv=el("pd-review");')
		self.block = self.js[at:at + 2200]

	def test_the_action_branch_is_second_now(self):
		self.assertIn("if(ST.paysByFeed){", self.block)
		self.assertLess(self.block.index("if(ST.paysByFeed){"),
			self.block.index("Submit & send "))

	def test_the_button_carries_no_handler_in_feed_mode(self):
		at = self.block.index("if(ST.paysByFeed){")
		branch = self.block[at:self.block.index("} else if(unpaid>0.001){")]
		self.assertIn("ap.onclick=null;", branch)
		self.assertIn("ap.disabled=true;", branch)
		self.assertNotIn("approveWorker(", branch)

	def test_the_accounts_footer_is_unchanged(self):
		self.assertIn('ap.textContent="Submit & send "+money(unpaid)+" to accounts";', self.block)
		self.assertIn("approveWorker(info.employee", self.block)

	def test_all_three_states_come_from_the_server(self):
		for state in ('"paid"', '"blocked"', '"eligible"'):
			with self.subTest(state=state):
				self.assertIn('out["feed_status"] = ' + state, self.api)

	def test_the_screen_renders_each_of_them(self):
		self.assertIn("Paid via payroll feed", self.block)
		self.assertIn("Cannot be fed to payroll", self.block)
		self.assertIn("Included in the next payroll feed", self.block)

	def test_the_sentence_is_the_server_s_not_the_screen_s(self):
		"""So the review sheet says what the payroll panel says about the same
		worker, rather than two screens inventing two wordings."""
		self.assertIn("info.feed_note", self.block)
		self.assertIn('out["feed_note"]', self.api)

	def test_the_blocked_reason_is_the_feed_s_own_reason(self):
		"""Not a second copy of the four gates -- payroll_preconditions() is
		shared, so 'no submitted Salary Structure Assignment' here is the same
		string the payroll panel gives."""
		self.assertIn("def payroll_preconditions(", self.api)
		self.assertIn("payroll_preconditions(emp, frappe.utils.today())", self.api)
		self.assertIn("payroll_preconditions(", read(PAYROLL))

	def test_the_feed_no_longer_carries_its_own_copy_of_those_gates(self):
		payroll = read(PAYROLL)
		at = payroll.index("PRECONDITIONS, checked before anything is written")
		block = payroll[at:at + 700]
		self.assertIn("payroll_preconditions(", block)
		self.assertNotIn('"employee is Inactive"', block)

	def test_which_path_made_a_run_survives_into_the_payload(self):
		"""The column was selected and the hand-built dict dropped it, so the
		"Paid via payroll feed" state could never fire."""
		at = self.api.index("runlist.append({")
		self.assertIn('"kind": r.kind or ""', self.api[at:at + 700])

	def test_row_editing_is_untouched(self):
		"""Correcting a day is not part of either payment path."""
		self.assertIn("wireDayEdits(", self.js)
		self.assertIn('elif action == "pay_worker_edit_day":', self.api)


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
