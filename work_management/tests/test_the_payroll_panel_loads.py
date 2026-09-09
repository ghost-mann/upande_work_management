"""Opening a panel must not attempt the write the panel exists to offer.

Two separate faults put a 417 on /work-payment's payroll panel, and only one of
them is the one it looked like.

**The 417 itself was an unroutable endpoint.** The screens address these scripts
by SHORT name -- `/api/method/wm_payment`, not the dotted path -- which works
only because `override_whitelisted_methods` in hooks.py maps each one. The
payroll feed shipped without a line there, so every call answered

    Failed to get method for command wm_payroll with 'wm_payroll'

which Frappe raises as a ValidationError and the browser sees as a 417. It reads
like the action refusing. It is the endpoint not existing, and it would have
failed by POST just as surely.

**The panel also loaded by calling its own write action.** That is the design
fault underneath, and it stands whatever the transport: a page load must not
attempt to write to live payroll records, must not need a CSRF token to render,
and must not fail when the feature is merely unconfigured. So `preview` reads and
`feed_week_to_payroll` writes, the write refuses anything but POST, and `preview`
answers "you cannot feed this yet, because ..." in a sentence rather than by
raising.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_the_payroll_panel_loads -v
"""

import os
import re
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAYROLL = os.path.join(APP, "api", "payroll.py")
HOOKS = os.path.join(APP, "hooks.py")
JS = os.path.join(APP, "public", "js")


def read(path):
	with open(path) as handle:
		return handle.read()


class TestEveryEndpointAScreenCallsIsRoutable(unittest.TestCase):
	"""The guard the 417 needed and did not have.

	A short name reaches a Python module only through
	`override_whitelisted_methods`. Nothing checked that the map covered what the
	screens actually ask for, so adding a call to a new script looked exactly like
	adding a call to an existing one -- right up until it 417'd in a browser.
	"""

	SCREENS = ("work-planner", "work-assigner", "work-actuals", "work-payment",
		"work-management-dashboard")

	def called_endpoints(self):
		"""Every `/api/method/<name>` and every `call(..., "<name>")` the screens use."""
		found = set()
		for screen in self.SCREENS:
			src = read(os.path.join(JS, screen + ".js"))
			found |= set(re.findall(r'"/api/method/(\w+)"', src))
			# the third argument of call() names another script by short name
			found |= set(re.findall(r'\bcall\([^;]{0,400}?,\s*"(wm_\w+)"\s*\)', src, re.S))
		return found

	def mapped(self):
		src = read(HOOKS)
		block = src[src.index("override_whitelisted_methods = {"):]
		block = block[:block.index("}")]
		return set(re.findall(r'"(\w+)":', block))

	def test_the_screens_call_something(self):
		"""A regex that matches nothing passes the assertion below."""
		self.assertGreaterEqual(len(self.called_endpoints()), 3)

	def test_every_one_of_them_is_mapped(self):
		unroutable = sorted(self.called_endpoints() - self.mapped())
		self.assertEqual(unroutable, [],
			"a screen calls /api/method/<name> for these and hooks.py maps none of "
			"them, so every call answers \"Failed to get method\" (a 417 in the "
			"browser): " + ", ".join(unroutable))

	def test_the_payroll_feed_in_particular(self):
		"""Named, because this is the one that shipped broken."""
		self.assertIn("wm_payroll", self.mapped())
		self.assertIn("work_management.api.payroll.wm_payroll", read(HOOKS))

	def test_every_mapping_points_at_something_importable(self):
		"""A typo in the dotted path fails the same way, one step later."""
		import importlib

		src = read(HOOKS)
		block = src[src.index("override_whitelisted_methods = {"):]
		block = block[:block.index("}")]
		for short, dotted in re.findall(r'"(\w+)":\s*"([\w.]+)"', block):
			with self.subTest(endpoint=short):
				module, _, attr = dotted.rpartition(".")
				self.assertTrue(hasattr(importlib.import_module(module), attr),
					dotted + " does not exist")


class TestTheLoaderReadsAndTheButtonWrites(unittest.TestCase):
	def setUp(self):
		self.js = read(os.path.join(JS, "work-payment.js"))
		self.src = read(PAYROLL)

	def test_the_loader_asks_for_a_preview(self):
		at = self.js.index("function feedWeek(")
		block = self.js[at:at + 900]
		self.assertIn('write ? "feed_week_to_payroll" : "preview"', block)

	def test_the_panel_is_loaded_without_writing(self):
		"""feedWeek(false) is what the tab calls, and false is what makes it a GET
		of the read action."""
		self.assertIn("feedWeek(false)", self.js)

	def test_the_write_is_a_post(self):
		at = self.js.index("function wireFeed(")
		self.assertIn("feedWeek(true)", self.js[at:at + 900])
		at2 = self.js.index("function feedWeek(")
		self.assertIn("write?true:false", self.js[at2:at2 + 900])

	def test_the_csrf_token_travels_with_a_post(self):
		"""The pages are bare fragments, so their stub carries the token."""
		at = self.js.index("function call(")
		self.assertIn("X-Frappe-CSRF-Token", self.js[at:at + 900])

	def test_the_preview_action_exists_and_writes_nothing(self):
		at = self.src.index("def feed_preview(")
		block = self.src[at:self.src.index("def feed_write(")]
		for forbidden in (".save(", "db.set_value", "db.commit", "add_comment", ".insert("):
			with self.subTest(call=forbidden):
				self.assertNotIn(forbidden, block,
					"feed_preview() is the panel's loader and must not write")

	def test_the_write_refuses_anything_but_post(self):
		self.assertIn("def wants_post():", self.src)
		at = self.src.index('elif action == "feed_week_to_payroll":')
		self.assertIn("if not wants_post():", self.src[at:at + 900])

	def test_a_console_run_is_still_allowed_to_write(self):
		"""No request at all is a bench console or a background job, and every
		hygiene action in this app is run that way."""
		at = self.src.index("def wants_post():")
		self.assertIn("request is None", self.src[at:at + 900])

	def test_the_write_re_reads_the_week_rather_than_trusting_the_client(self):
		at = self.src.index('elif action == "feed_week_to_payroll":')
		block = self.src[at:at + 1400]
		self.assertIn("feed_preview(", block)
		self.assertIn('if not out.get("can_feed")', block)

	def test_the_write_writes_what_the_preview_showed(self):
		"""feed_write() consumes the preview dict, so what somebody approved on
		screen is exactly what lands."""
		at = self.src.index("def feed_write(")
		self.assertIn("plan.get(\"rows\")", self.src[at:at + 900])


class TestThePanelExplainsItselfWhenItCannotFeed(unittest.TestCase):
	"""A panel must never fail to load for being unconfigured -- that tells its
	reader nothing except that something is broken."""

	def setUp(self):
		self.src = read(PAYROLL)
		at = self.src.index("    reason = None")
		self.block = self.src[at:self.src.index('out["cannot_feed"] = reason') + 60]
		self.js = read(os.path.join(JS, "work-payment.js"))

	def test_there_is_a_flag_and_a_sentence(self):
		self.assertIn('out["can_feed"]', self.src)
		self.assertIn('out["cannot_feed"]', self.src)

	def test_the_reasons_it_can_give(self):
		for reason, gist in (
			("not configured: ", "the custom field is missing"),
			("has not closed yet", "the week is still being worked"),
			("already been fed", "the week is done"),
			("none can be fed", "everyone is skipped for their own reason"),
			("no confirmed unpaid work", "there is nothing there"),
		):
			with self.subTest(reason=gist):
				self.assertIn(reason, self.block)

	def test_configuration_is_reported_before_anything_else(self):
		"""Tell the reader the thing they have to fix first."""
		self.assertLess(self.block.index("not configured: "),
			self.block.index("has not closed yet"))

	def test_the_reason_is_a_sentence_not_a_code(self):
		self.assertNotIn('"CONFIG_MISSING"', self.block)
		self.assertIn(" -- it can be fed ", self.block)

	def test_an_error_is_kept_for_things_that_are_actually_wrong(self):
		"""A week that does not exist is an error; a week that cannot be fed yet
		is not, and conflating them is what made the panel look broken."""
		self.assertIn("belongs to no pay", self.src)
		self.assertIn("is not one pay week", self.src)

	def test_the_screen_renders_the_reason(self):
		at = self.js.index("function renderFeed(")
		block = self.js[at:at + 2500]
		self.assertIn("d.cannot_feed", block)
		self.assertIn("Not yet:", block)

	def test_the_button_is_gated_on_the_flag_not_on_the_row_count(self):
		at = self.js.index("function renderFeed(")
		block = self.js[at:at + 2500]
		self.assertIn("can=!!d.can_feed", block)

	def test_the_button_says_what_it_will_pay(self):
		at = self.js.index("function renderFeed(")
		block = self.js[at:at + 2500]
		self.assertIn("'Feed week to payroll — '+money(d.total)", block)

	def test_the_already_fed_state_is_shown_rather_than_left_blank(self):
		self.assertIn("already_fed", self.js)


if __name__ == "__main__":
	unittest.main()
