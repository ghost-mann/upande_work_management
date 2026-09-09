"""A day worked on a public holiday is worth double -- and a rest day is not.

Two features read the same table and mean opposite things by it, so the field
that separates them has to be written down once, loudly:

    Holiday.weekly_off = 1   the worker's REST day.  Working every OTHER day of
                             the week earns the off-day bonus for it (Phase 5).
    Holiday.weekly_off = 0   a PUBLIC holiday.  A working day, paid at the
                             multiplier, and missing it forfeits the bonus.

Get it backwards and every public holiday in the calendar pays a bonus, or every
rest day pays double. Both are money, both are silent, and neither shows up in a
figure anyone reconciles.

THE MULTIPLIER IS APPLIED AT VALUATION, so it changes new actuals only. A plan's
realised COST can now exceed rate x target where holidays fall in the period,
while the plan's QUANTITY cap is untouched -- quantity does not move, money does.
That is intended and Phase 6's arithmetic must not "fix" it.

WHAT MAKES IT EXPLAINABLE is that the row stores what it was multiplied by,
including the 1. That single field does three jobs: it is the ×2 marker on the
review sheet and in the Worker Task Day export, it is what the amount check
compares against, and -- being EMPTY on every row written before this shipped --
it is what stops 7,000 rows of history being reported as underpaid on the day
this goes out.

Measured on kentrout.local before this was written, with a list holding one row
of each kind, at a task rate of 13.114754 and 10 units a day:

    2026-09-13  rest day        131.15  stored x1   not doubled
    2026-09-15  public holiday  262.30  stored x2   doubled
    2026-09-16  ordinary day    131.15  stored x1

and the amount check: the doubled row clean; the same row put back to 131.15
with x1 stored reported as underpaid against an expected 262.30; the same row
again with NOTHING stored not reported at all.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_public_holiday_pay -v
"""

import json
import os
import re
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACTUALS = os.path.join(APP, "api", "actuals.py")
PAYMENT = os.path.join(APP, "api", "payment.py")
CONFIG = os.path.join(APP, "api", "config.py")
SCREEN = os.path.join(APP, "public", "js", "work-payment.js")
MARKUP = os.path.join(APP, "www", "work-payment.html")
SETTINGS = os.path.join(APP, "work_management", "doctype",
	"work_management_settings", "work_management_settings.json")
ROW = os.path.join(APP, "work_management", "doctype",
	"work_actuals_employee", "work_actuals_employee.json")
REPORT = os.path.join(APP, "work_management", "report", "worker_task_day",
	"worker_task_day.py")

FIELD = "public_holiday_pay_multiplier"
MARK = "holiday_multiplier"


def read(path):
	with open(path) as handle:
		return handle.read()


def doctype(path):
	return json.load(open(path))


def fields(path):
	return {f["fieldname"]: f for f in doctype(path)["fields"]}


class TestTheSetting(unittest.TestCase):
	def setUp(self):
		self.field = fields(SETTINGS).get(FIELD)

	def test_it_exists_and_is_a_number(self):
		self.assertIsNotNone(self.field)
		self.assertEqual(self.field["fieldtype"], "Float")

	def test_a_fresh_install_gets_two(self):
		self.assertEqual(str(self.field.get("default")), "2")

	def test_it_is_on_the_form(self):
		self.assertIn(FIELD, doctype(SETTINGS)["field_order"])

	def test_its_description_says_which_kind_of_holiday(self):
		"""The one thing a reader must not have to guess."""
		text = (self.field.get("description") or "").lower()
		self.assertIn("public", text)
		self.assertIn("weekly off", text)

	def test_it_says_how_to_switch_it_off(self):
		self.assertIn("1 switches it off", self.field.get("description") or "")


class TestAnExistingSiteIsNotSilentlySwitchedOn(unittest.TestCase):
	"""A `default` on a Single's field reaches a FRESH install only. On a site
	that already exists the field arrives as 0 -- this app has been bitten by
	exactly that before, when three standard-day fields defaulted to '0' and made
	every man-day figure zero and wrote zero hours onto 7,605 rows.

	Read literally, 0 here would value a public holiday's work at nothing. Read
	as 2, it would double every site's holiday pay because they migrated. So 0
	means "nothing said", and nothing said is 1.0."""

	def setUp(self):
		self.src = read(CONFIG)

	def test_the_default_in_code_is_one_not_two(self):
		at = self.src.index('"%s": ' % FIELD)
		self.assertIn("1.0", self.src[at:at + 40])

	def test_zero_is_read_as_nothing_said(self):
		at = self.src.index("_holiday_x = ")
		self.assertIn("if _holiday_x > 0:", self.src[at:at + 200])

	def test_the_reason_is_written_down_beside_it(self):
		at = self.src.index("PUBLIC HOLIDAY PAY")
		self.assertIn("FRESH", self.src[at:at + 900])


class TestTheRowRecordsHowItWasValued(unittest.TestCase):
	def setUp(self):
		self.field = fields(ROW).get(MARK)

	def test_the_field_exists_on_the_worker_row(self):
		self.assertIsNotNone(self.field, "nothing on the row says why it is doubled")
		self.assertEqual(self.field["fieldtype"], "Float")

	def test_it_is_read_only(self):
		"""It is a record of what happened, not an input."""
		self.assertTrue(self.field.get("read_only"))

	def test_it_sits_beside_the_amount_it_explains(self):
		order = doctype(ROW)["field_order"]
		self.assertEqual(order[order.index("amount") + 1], MARK)

	def test_its_description_says_what_empty_means(self):
		"""That is the whole historical-tolerance mechanism, in one field."""
		self.assertIn("EMPTY", self.field.get("description") or "")


class TestTheValuation(unittest.TestCase):
	def setUp(self):
		self.src = read(ACTUALS)
		at = self.src.index("hx_days = {}")
		self.block = self.src[at:self.src.index("row.holiday_multiplier") + 200]

	def test_the_multiplier_reaches_the_screen_s_script(self):
		self.assertIn('HOLIDAY_X = _cfg["public_holiday_pay_multiplier"]', self.src)

	def test_only_public_holidays_count(self):
		self.assertIn("IFNULL(weekly_off, 0) = 0", self.block)

	def test_it_is_the_worker_s_own_list(self):
		self.assertIn("SELECT name, holiday_list FROM `tabEmployee`", self.block)

	def test_the_amount_is_multiplied(self):
		self.assertIn("amt = round(qty * (unit_value or rate) * hol_x, 2) if in_pay else 0",
			self.src)

	def test_an_ordinary_day_multiplies_by_one(self):
		"""So the arithmetic on every other row is unchanged, exactly."""
		self.assertIn("hol_x = HOLIDAY_X if hx_days.get((emp, wdate)) else 1", self.src)

	def test_the_multiplier_is_stored_on_the_row(self):
		self.assertIn("row.holiday_multiplier = hol_x", self.src)

	def test_the_holiday_lookup_is_one_query_for_the_whole_grid(self):
		"""A full grid is one row per worker per day; asking the Holiday table
		for each of them is the same answer several hundred times."""
		self.assertIn("holiday_date IN %(d)s", self.block)
		self.assertIn("WHERE name IN %(e)s", self.block)

	def test_nothing_is_asked_at_all_when_the_feature_is_off(self):
		self.assertIn("if HOLIDAY_X != 1:", self.src)


class TestTheAmountCheckKnowsAboutHolidays(unittest.TestCase):
	def setUp(self):
		self.src = read(PAYMENT)
		at = self.src.index("# amount should equal qty x doc rate")
		self.block = self.src[at:at + 2200]

	def test_the_two_kinds_of_holiday_are_kept_apart(self):
		"""off_ev still holds both, because "work recorded on an off day" wants
		both. pub_ev is the narrower one the multiplier follows."""
		self.assertIn("pub_ev = {}", self.src)
		self.assertIn("if not frappe.utils.cint(r2.weekly_off):", self.src)

	def test_the_expected_amount_carries_the_multiplier(self):
		self.assertIn("* want_x", self.block)

	def test_a_holiday_row_is_expected_to_be_doubled(self):
		self.assertIn("want_x = HOLIDAY_X", self.block)

	def test_a_row_with_nothing_stored_is_judged_by_the_old_rule(self):
		"""Otherwise every historical holiday row lights up as underpaid on the
		day this ships -- thousands of them, none of them actionable."""
		self.assertIn("want_x = 1", self.block)
		self.assertIn("if frappe.utils.flt(r.hol_x) > 0:", self.block)

	def test_the_stored_multiplier_is_selected(self):
		self.assertIn("IFNULL(we.holiday_multiplier, 0) hol_x", self.src)

	def test_the_flagged_row_explains_itself(self):
		for key in ('rr3["multiplier"]', 'rr3["holiday"]', 'rr3["effective_rate"]'):
			with self.subTest(key=key):
				self.assertIn(key, self.block)


class TestRepairsDoNotCreateUnderpayment(unittest.TestCase):
	"""pay_fix_unvalued sets a zero-valued row to qty x rate. On a holiday that
	is a single rate, and the check above would then report the repair -- rightly
	-- as underpaid the moment it finished."""

	def setUp(self):
		src = read(PAYMENT)
		at = src.index("fz_x = 1")
		self.block = src[at - 400:at + 900]

	def test_the_repair_asks_whether_the_day_was_a_holiday(self):
		self.assertIn('"weekly_off": 0', self.block)

	def test_it_values_the_row_the_way_entry_would(self):
		self.assertIn("* fz_x", self.block)

	def test_it_records_the_multiplier_it_used(self):
		self.assertIn('"holiday_multiplier", fz_x', self.block)

	def test_a_quantity_edit_keeps_the_doubling(self):
		"""The two edit paths derive the rate from amount/qty, which already
		carries the multiplier -- so editing a doubled row's quantity keeps it
		doubled without knowing anything about holidays."""
		src = read(PAYMENT)
		self.assertEqual(src.count("rate = (old_amt / old_qty) if old_qty else frappe.utils.flt("), 2)


class TestHRCanSeeWhyAnAmountIsDouble(unittest.TestCase):
	def setUp(self):
		self.js = read(SCREEN)
		self.payment = read(PAYMENT)

	def test_the_review_sheet_is_told_the_multiplier(self):
		self.assertIn('"holiday_multiplier": frappe.utils.flt(r.hol_x)', self.payment)

	def test_and_the_effective_rate(self):
		self.assertIn('"effective_rate"', self.payment)

	def test_and_whether_the_day_was_a_public_holiday(self):
		self.assertIn('"day_public_holiday"', self.payment)

	def test_the_review_sheet_shows_the_marker(self):
		at = self.js.index("function renderWorkerReview(") if "function renderWorkerReview(" in self.js else 0
		self.assertIn("r.holiday_multiplier>1", self.js)
		self.assertIn("wr-holx", self.js)

	def test_the_marker_has_a_style(self):
		self.assertIn("#wpay .wr-holx{", read(MARKUP))

	def test_the_discrepancy_sheet_shows_it_too(self):
		at = self.js.index('c.key==="rate_mismatch"')
		block = self.js[at:at + 1400]
		self.assertIn("r.multiplier>1", block)
		self.assertIn("r.holiday", block)

	def test_the_report_carries_the_marker(self):
		src = read(REPORT)
		self.assertIn("IFNULL(we.holiday_multiplier, 0) holiday_multiplier", src)
		self.assertIn('"pay_multiplier"', src)

	def test_the_report_column_exists(self):
		src = read(REPORT)
		self.assertIn('{"fieldname": "pay_multiplier"', src)

	def test_an_ordinary_day_gets_no_marker_in_the_report(self):
		"""1 is not a fact worth a column, and a column of 1s hides the 2s."""
		src = read(REPORT)
		at = src.index('"pay_multiplier": ')
		self.assertIn("> 1 else None", src[at:at + 250])


class TestWhatMustNotChange(unittest.TestCase):
	def test_the_quantity_cap_is_untouched(self):
		"""Money doubles; quantity does not. A plan's realised cost can now exceed
		rate x target where holidays fall in the period, and that is intended."""
		src = read(ACTUALS)
		at = src.index("HARD TARGET CAP") if "HARD TARGET CAP" in src else None
		self.assertIsNotNone(at, "the target cap should still be here")
		block = src[at:at + 1800]
		self.assertNotIn("HOLIDAY_X", block,
			"the quantity cap must not consult the pay multiplier")

	def test_the_off_day_check_still_sees_both_kinds(self):
		"""disc_off_paid means "work recorded on an off day OR a holiday" and
		narrowing it to one kind would silently stop reporting the other."""
		src = read(PAYMENT)
		at = src.index("off_ev[(r2.parent, str(r2.holiday_date))] = 1")
		self.assertIn("off_ev", src[at - 200:at + 40])
		self.assertIn("if not onlv and hl_ev.get(r.employee) and off_ev.get(", src)


if __name__ == "__main__":
	unittest.main()
