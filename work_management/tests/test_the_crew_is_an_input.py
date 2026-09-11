"""How many people to send is the planner's decision, not the arithmetic's.

The client: *"Allow us indicate the number of people we want to allocate. (The
system currently indicates the number needed.)"*

The computed figure -- quantity / daily target / working days, rounded up
because people come whole -- stops being the answer and becomes the SUGGESTION.
It prefills the field; the requester may say otherwise; their number is what is
stored, shown to the assigner and kept through approval.

**It changes nothing else, and that is the point.** Cost is quantity x rate.
Man-days are quantity / daily target. Both are properties of the WORK, not of
how many people are sent at it: twelve people finish sooner than six, they do
not finish more and they do not cost more per unit. The only thing a bigger crew
buys is days, which is what the screen now says beside the number.

Measured on kentrout.local, 9 units of a task at 3/day over 3 days, rate
133.333333:

    crew given   stored   suggested   man-days   cost
    (none)         1          1          3      1199.999997
    5              5          1          3      1199.999997
    20            20          1          3      1199.999997
    0              1          1          3      1199.999997

and a request saved with 11 still reads 11 after approval, and reaches the
assigner as 11.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_the_crew_is_an_input -v
"""

import math
import os
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = os.path.join(APP, "api", "planner.py")
SCREEN = os.path.join(APP, "public", "js", "work-planner.js")
MARKUP = os.path.join(APP, "www", "work-planner.html")


def read(path):
	with open(path) as handle:
		return handle.read()


def submit_block():
	src = read(API)
	at = src.index("ppd_suggested = 0")
	return src[at:src.index('out["editing"] = editing', at)]


def suggest(qty, daily_target, working_days):
	"""The suggestion, as the server computes it. Pure, so the arithmetic this
	feature leaves alone can be asserted without a site."""
	if daily_target <= 0 or working_days <= 0:
		return 0
	return math.ceil(qty / daily_target / working_days)


class TestTheSuggestionItself(unittest.TestCase):
	"""Unchanged by this work -- it is what prefills the field."""

	def test_it_is_the_man_days_spread_over_the_days(self):
		self.assertEqual(suggest(90, 3, 3), 10)

	def test_it_rounds_up_because_people_come_whole(self):
		self.assertEqual(suggest(10, 3, 3), 2)
		self.assertEqual(suggest(9, 3, 3), 1)

	def test_no_target_or_no_days_suggests_nothing(self):
		self.assertEqual(suggest(90, 0, 3), 0)
		self.assertEqual(suggest(90, 3, 0), 0)


class TestTheServerKeepsTheRequestersNumber(unittest.TestCase):
	def setUp(self):
		self.block = submit_block()

	def test_the_computed_figure_is_named_a_suggestion(self):
		self.assertIn("ppd_suggested", self.block)

	def test_the_form_value_is_read(self):
		self.assertIn('frappe.utils.cint(frappe.form_dict.get("people_per_day"))', self.block)

	def test_a_given_number_wins(self):
		self.assertIn("ppd = ppd_asked if ppd_asked > 0 else ppd_suggested", self.block)

	def test_nothing_given_falls_back_to_the_suggestion(self):
		"""So a caller that does not know about the field is unaffected."""
		self.assertIn("else ppd_suggested", self.block)

	def test_zero_is_nothing_given_rather_than_a_crew_of_zero(self):
		self.assertIn("ppd_asked > 0", self.block)

	def test_the_stored_figure_is_the_resolved_one(self):
		self.assertIn("d.people_per_day = ppd", self.block)

	def test_both_numbers_come_back_so_the_screen_can_name_them(self):
		self.assertIn('out["people_per_day_suggested"]', self.block)
		self.assertIn('out["people_per_day_is_custom"]', self.block)


class TestWhatTheCrewMustNotMove(unittest.TestCase):
	"""The whole safety of this change: a bigger crew buys days, not money."""

	def setUp(self):
		self.block = submit_block()

	def test_cost_is_quantity_times_rate(self):
		self.assertIn("d.total_cost = qty * rate", self.block)

	def test_cost_does_not_mention_the_crew(self):
		at = self.block.index("d.total_cost = qty * rate")
		line = self.block[at:self.block.index("\n", at)]
		self.assertNotIn("ppd", line)

	def test_man_days_are_the_work_not_the_crew(self):
		"""quantity / daily target. The `ppd * wd` fallback is only for a task
		with no daily target at all, where there is nothing else to go on."""
		self.assertIn("d.person_days = frappe.utils.flt(qty / tgt, 2) if tgt > 0", self.block)

	def test_approving_does_not_recompute_it(self):
		src = read(API)
		at = src.index('elif action == "approve":')
		block = src[at:src.index('elif action == "reject":', at)]
		self.assertNotIn("people_per_day", block)


class TestTheScreenOffersIt(unittest.TestCase):
	def setUp(self):
		self.js = read(SCREEN)
		self.html = read(MARKUP)

	def test_the_figure_is_a_field_now(self):
		self.assertIn('id="f-ppl"', self.html)
		self.assertIn('type="number"', self.html[self.html.index('id="f-ppl"') - 120:
			self.html.index('id="f-ppl"') + 60])

	def test_a_crew_of_zero_cannot_be_typed(self):
		at = self.html.index('id="f-ppl"')
		self.assertIn('min="1"', self.html[at - 120:at + 120])

	def test_the_suggestion_prefills_it(self):
		self.assertIn("if(pf && !ST.ppdTouched) pf.value", self.js)

	def test_but_stops_once_the_requester_types(self):
		"""Or every keystroke is overwritten by the arithmetic being overruled."""
		self.assertIn("ST.ppdTouched", self.js)
		at = self.js.index('pfi.oninput=function()')
		self.assertIn('ST.ppdTouched=(String(this.value).trim()!=="")', self.js[at:at + 200])

	def test_a_new_quantity_starts_suggesting_again(self):
		at = self.js.index('el("f-qty").oninput=')
		self.assertIn("ST.ppdTouched=false", self.js[at:at + 300])

	def test_the_label_names_both_numbers(self):
		self.assertIn('"suggested "+fmt(ppd)+" · you planned "+fmt(want)', self.js)

	def test_and_says_what_the_bigger_crew_buys(self):
		"""Days. Not money, and not more work."""
		self.assertIn("day to finish", self.js.replace('"+(daysAt>1?"s":"")+"', " to finish"))

	def test_the_days_figure_is_the_work_over_the_crew(self):
		self.assertIn("Math.ceil(mandays/used)", self.js)

	def test_the_number_is_sent(self):
		at = self.js.index('action:"submit"')
		self.assertIn("people_per_day:", self.js[at:at + 700])

	def test_editing_a_plan_refills_what_was_saved(self):
		"""Not a fresh suggestion -- that would quietly undo the number somebody
		chose the first time."""
		at = self.js.index("function openPlanForEdit(")
		block = self.js[at:at + 2800]
		self.assertIn('el("f-ppl").value = p.people_per_day', block)
		self.assertIn("ST.ppdTouched = !!p.people_per_day", block)


class TestTheAssignerIsUnaffected(unittest.TestCase):
	"""It already warns rather than blocks when the crew does not match the
	plan's people/day, so a user-set figure flows through as any other would."""

	def test_it_warns_on_headcount_rather_than_refusing(self):
		src = read(os.path.join(APP, "api", "assigner.py"))
		self.assertIn('out["crew_warning"]', src)

	def test_the_refusal_only_applies_with_split_day_off(self):
		src = read(os.path.join(APP, "api", "assigner.py"))
		at = src.index('out["crew_warning"]')
		self.assertIn("if ALLOW_SPLIT_DAY:", src[at - 400:at])

	def test_it_reads_the_plan_s_stored_figure(self):
		src = read(os.path.join(APP, "api", "assigner.py"))
		self.assertIn("people_per_day", src)


if __name__ == "__main__":
	unittest.main()
