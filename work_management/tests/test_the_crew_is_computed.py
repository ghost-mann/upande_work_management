"""How many people to send is the arithmetic's answer, not the planner's.

quantity / daily target / working days, rounded up because people come whole.
The screen reports it; nobody types over it.

**This was briefly the other way round.** The client asked for the reverse --
*"Allow us indicate the number of people we want to allocate. (The system
currently indicates the number needed.)"* -- it shipped in `ea089df` as an input
prefilled by the computed figure, and the client reversed the decision at the
meeting of **15 September 2026**. So this file is the same subject asserted the
opposite way, and the tests that pinned the input are gone rather than skipped:
a skipped test is a claim nobody is making any more that still reads like one.

What has to be true, and each is a way the input could crawl back:

  * the server computes `ppd` and does not read `people_per_day` off the form,
    so a hand-rolled POST cannot set a crew the screen refuses to offer
  * the markup has a figure where the field was, and the field id appears
    nowhere in the app
  * neither the estimate copy nor the submit payload mentions a chosen crew

**What the crew must still not move**, unchanged and still the point: cost is
quantity x rate and man-days are quantity / daily target, both properties of the
WORK rather than of how many people are sent at it. Those tests survive the
reversal untouched, because they were never about who chose the number.

**Existing requests.** A request saved while the field existed keeps whatever
was typed until its next save, which recomputes -- `d.people_per_day = ppd` runs
on the edit path as well as the insert. No patch: the figure is advisory, it
feeds no money, and rewriting approved paperwork to erase a decision somebody
made in good faith is worse than letting it age out.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_the_crew_is_computed -v
"""

import math
import os
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = os.path.join(APP, "api", "planner.py")
SCREEN = os.path.join(APP, "public", "js", "work-planner.js")
MARKUP = os.path.join(APP, "www", "work-planner.html")

#: The input's id, gone from every file. Named once so the sweep below cannot
#: drift from the tests that describe what it used to do.
FIELD_ID = "f-ppl"


def read(path):
	with open(path) as handle:
		return handle.read()


def submit_block():
	src = read(API)
	at = src.index("# HOW MANY PEOPLE, computed")
	return src[at:src.index('out["editing"] = editing', at)]


def crew(qty, daily_target, working_days):
	"""The figure, as the server computes it. Pure, so it can be asserted
	without a site -- and unchanged by the reversal, which only ever moved who
	was allowed to overrule it."""
	if daily_target <= 0 or working_days <= 0:
		return 0
	return math.ceil(qty / daily_target / working_days)


class TestTheArithmeticItself(unittest.TestCase):
	def test_it_is_the_man_days_spread_over_the_days(self):
		self.assertEqual(crew(90, 3, 3), 10)

	def test_it_rounds_up_because_people_come_whole(self):
		self.assertEqual(crew(10, 3, 3), 2)
		self.assertEqual(crew(9, 3, 3), 1)

	def test_no_target_or_no_days_answers_nothing(self):
		self.assertEqual(crew(90, 0, 3), 0)
		self.assertEqual(crew(90, 3, 0), 0)


class TestTheServerDecidesIt(unittest.TestCase):
	def setUp(self):
		self.block = submit_block()

	def test_the_figure_is_computed_here(self):
		self.assertIn("ppd = 0", self.block)
		self.assertIn("raw = qty / tgt / wd", self.block)
		self.assertIn("if ppd < raw: ppd = ppd + 1", self.block)

	def test_the_form_value_is_not_read(self):
		"""The screen offering no field is a courtesy; this is the rule. A POST
		by hand must not be able to set a crew the screen will not offer."""
		self.assertNotIn('frappe.form_dict.get("people_per_day")', self.block)

	def test_nothing_is_kept_from_the_requester(self):
		for gone in ("ppd_asked", "ppd_suggested"):
			with self.subTest(name=gone):
				self.assertNotIn(gone, self.block)

	def test_the_stored_figure_is_the_computed_one(self):
		self.assertIn("d.people_per_day = ppd", self.block)

	def test_an_edit_recomputes_it(self):
		"""Which is why a request carrying a typed figure needs no patch: it
		ages out the next time anybody saves it."""
		at = self.block.index("d.people_per_day = ppd")
		self.assertIn("d.save(ignore_permissions=True)", self.block[at:])

	def test_the_screen_is_told_one_number_not_three(self):
		self.assertIn('out["people_per_day"] = d.people_per_day', self.block)
		for gone in ('out["people_per_day_suggested"]', 'out["people_per_day_is_custom"]'):
			with self.subTest(key=gone):
				self.assertNotIn(gone, self.block)


class TestWhatTheCrewMustNotMove(unittest.TestCase):
	"""Unchanged by the reversal, and unchanged by the thing it reversed. Twelve
	people finish sooner than six; they do not finish more, and they do not cost
	more per unit."""

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


class TestTheScreenOnlyReportsIt(unittest.TestCase):
	def setUp(self):
		self.js = read(SCREEN)
		self.html = read(MARKUP)

	def test_the_markup_has_a_figure_where_the_field_was(self):
		self.assertIn('<div class="v" id="o-ppl">', self.html)

	def test_the_field_is_gone_from_every_file(self):
		"""The sweep. Half a revert is worse than none: a field the screen still
		renders but nothing sends is a control that silently does nothing."""
		for path in (MARKUP, SCREEN, API):
			with self.subTest(path=os.path.basename(path)):
				self.assertNotIn(FIELD_ID, read(path))

	def test_nothing_tracks_whether_it_was_typed_in(self):
		for gone in ("ppdTouched", "ppdSuggested"):
			with self.subTest(name=gone):
				self.assertNotIn(gone, self.js)

	def test_the_estimate_prints_the_computed_figure(self):
		self.assertIn('el("o-ppl").textContent = ppd>0?fmt(ppd):', self.js)

	def test_the_label_is_the_daily_target_again(self):
		self.assertIn('el("o-ppl-u").textContent = (info?fmt(tgt)+" "+(info.uom||"")+"/day":"crew size")',
			self.js)

	def test_the_two_numbers_copy_is_gone(self):
		"""The exact fragments, not the loose words -- "suggested" appears in an
		unrelated comment about draft wording, and a test that trips on that is
		a test people learn to edit rather than believe."""
		for gone in ('"suggested "+fmt(', "you planned", "day to finish",
				"Math.ceil(mandays/used)"):
			with self.subTest(copy=gone):
				self.assertNotIn(gone, self.js)

	def test_the_quantity_field_just_recalculates(self):
		self.assertIn('el("f-qty").oninput=recalc;', self.js)

	def test_no_crew_is_sent(self):
		at = self.js.index('action:"submit"')
		self.assertNotIn("people_per_day", self.js[at:at + 700])

	def test_opening_a_saved_plan_refills_no_crew(self):
		at = self.js.index("function openPlanForEdit(")
		self.assertNotIn("people_per_day", self.js[at:at + 2800])

	def test_the_stored_figure_is_still_shown_in_the_lists(self):
		"""Read-only is not invisible. Both tabs still print Ppl/Day, so a
		request saved with a typed crew still reads back honestly."""
		self.assertIn('<th class="n">Ppl/Day</th>', self.js)
		self.assertIn('fmt(r.people_per_day)', self.js)


class TestTheAssignerIsUnaffected(unittest.TestCase):
	"""It reads the plan's stored figure and warns rather than refuses where a
	day may be split -- true whoever put the number there, which is why this
	survived the change and the reversal without an edit."""

	def setUp(self):
		self.src = read(os.path.join(APP, "api", "assigner.py"))

	def test_it_warns_on_headcount_rather_than_refusing(self):
		self.assertIn('out["crew_warning"]', self.src)

	def test_the_refusal_only_applies_with_split_day_off(self):
		at = self.src.index('out["crew_warning"]')
		self.assertIn("if ALLOW_SPLIT_DAY:", self.src[at - 400:at])

	def test_it_reads_the_plan_s_stored_figure(self):
		self.assertIn("people_per_day", self.src)


if __name__ == "__main__":
	unittest.main()
