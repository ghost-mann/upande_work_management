"""The switch that permits a shared day has to reach the screen that picks people.

"Allow a worker's day to be split between tasks" was honoured everywhere a
decision was WRITTEN and nowhere a decision was OFFERED. Both assigner write
paths branch on it correctly -- a_submit returns `split_warning` instead of
refusing, a_add_crew the same -- and both pickers went on rendering the hard
block. So on a site with the switch ON, the people it exists to allow were the
exact people the screen hid, and the feature looked broken while being, in the
part nobody could see, entirely present.

Two separate faults, one per picker:

**The assign picker** got `allow_split_day` in its payload and used it only in
the click handler. The ROW was still drawn `.busy` -- opacity .55, a disabled
checkbox and a red ASSIGNED ELSEWHERE chip -- so it read as refused, and the
disabled checkbox could not show a tick even when the click was allowed.
Reproduced on kentrout.local: plan WM-KenTrout Farm-00174 (2026-10-07 -> 08),
Alfred Karanja Wambugu, busy on WMA-00203.

**The Manage crew picker** was worse: `a_sub_candidates` filtered busy workers
out of the payload entirely, so they were not greyed, they were absent. The
screen tried to compensate with `ST._empAll`, a list only the assign and edit
flows ever fill -- and Manage crew calls neither, so on a fresh page load the
flag it consulted was `undefined` and the pool fell back to free-workers-only.
A fix that never fired.

**The two pools are not the same pool.** a_substitute refuses a busy replacement
whatever the flag says; a_add_crew allows one when the flag is on. So swap is
offered free workers only and add is offered the tagged ones too -- each picker
matching its own write path, which is the property whose absence is this whole
bug.

What does NOT move, either way: a worker already on THIS roster is refused, and
the double-pay guards are untouched. Adding somebody twice is a mistake, not a
split day.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_the_picker_honours_the_split_switch -v
"""

import os
import re
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = os.path.join(APP, "api", "assigner.py")
SCREEN = os.path.join(APP, "public", "js", "work-assigner.js")
MARKUP = os.path.join(APP, "www", "work-assigner.html")


def read(path):
	with open(path) as handle:
		return handle.read()


def action_block(name, api=None):
	src = api or read(API)
	at = src.index('elif action == "%s":' % name)
	nxt = re.search(r"^    elif action == ", src[at + 40:], re.M)
	return src[at:at + 40 + (nxt.start() if nxt else len(src))]


class TestTheAssignPickerPayload(unittest.TestCase):
	"""This half was already right and must stay right -- the rows are tagged
	rather than dropped, and the flag travels with them."""

	def setUp(self):
		self.block = action_block("a_employees")

	def test_busy_workers_are_tagged_not_filtered_out(self):
		self.assertIn('e["allocated_elsewhere"] = 1', self.block)
		self.assertIn('e["allocated_task"]', self.block)
		self.assertIn('e["allocated_asg"]', self.block)

	def test_the_payload_carries_the_flag(self):
		self.assertIn('out["allow_split_day"] = 1 if ALLOW_SPLIT_DAY else 0', self.block)

	def test_the_screen_keeps_it(self):
		self.assertIn("ST._empSplitOk=!!d.allow_split_day", read(SCREEN))


class TestTheAssignPickerRendersTheFlag(unittest.TestCase):
	"""The fault: the payload said "selectable" and the markup said "refused"."""

	def setUp(self):
		self.js = read(SCREEN)
		at = self.js.index("var busy = e.allocated_elsewhere?true:false;")
		self.block = self.js[at:at + 1800]

	def test_the_row_class_depends_on_the_flag(self):
		"""`.busy` is opacity .55 and cursor not-allowed -- the hard block. It is
		now drawn only when the block is real."""
		self.assertIn('ST._empSplitOk?"split":"busy"', self.block)

	def test_the_checkbox_is_only_disabled_when_the_block_is_real(self):
		"""A disabled checkbox cannot show a tick, so even the click that WAS
		permitted left the row looking unselected."""
		self.assertIn('ST._empSplitOk?(ST.picked[e.name]?"checked":""):"disabled"', self.block)

	def test_the_chip_becomes_a_warning_rather_than_a_refusal(self):
		self.assertIn("on another task — day will split", self.block)
		self.assertIn('allocb warn', self.block)

	def test_the_hard_block_wording_survives_for_the_flag_off_case(self):
		self.assertIn("assigned elsewhere", self.block)

	def test_the_warning_chip_has_a_style_of_its_own(self):
		"""Without a rule it inherits `.allocb`, which is solid red -- a warning
		painted as a refusal."""
		css = read(MARKUP)
		self.assertIn("#wap .allocb.warn{", css)
		self.assertIn("#wap .emrow.split", css)

	def test_a_split_row_is_not_greyed_out(self):
		css = read(MARKUP)
		at = css.index("#wap .emrow.busy{")
		self.assertIn("opacity:.55", css[at:at + 120])
		at2 = css.index("#wap .emrow.split{")
		self.assertNotIn("opacity", css[at2:at2 + 120])

	def test_the_click_guard_no_longer_needs_the_flag(self):
		"""`.busy` is now only ever the real block, so the guard is one condition
		instead of two that could disagree."""
		self.assertIn('if(row.classList.contains("busy")) return;', self.js)

	def test_picking_a_shared_day_is_confirmed_not_assumed(self):
		"""Same shape as the attendance consent beside it."""
		at = self.js.index("emp.allocated_elsewhere && ST._empSplitOk")
		block = self.js[at:at + 700]
		self.assertIn("window.confirm(", block)
		self.assertIn("day will be split", block)
		self.assertIn("hours each task took", block)

	def test_the_confirmation_names_the_other_task(self):
		at = self.js.index("emp.allocated_elsewhere && ST._empSplitOk")
		self.assertIn("emp.allocated_task", self.js[at:at + 700])


class TestTheManageCrewPickers(unittest.TestCase):
	def setUp(self):
		self.block = action_block("a_sub_candidates")

	def test_busy_workers_are_no_longer_dropped_from_the_payload(self):
		"""They were filtered out before reaching the screen, so no amount of
		client-side flag reading could have brought them back."""
		self.assertNotIn("if not already_map.get(emp.name) and not busy_map.get(emp.name):",
			self.block)

	def test_the_add_pool_takes_them_only_when_the_flag_is_on(self):
		self.assertIn("if ALLOW_SPLIT_DAY:", self.block)
		self.assertIn("add_cands.append(tagged)", self.block)

	def test_they_are_tagged_with_what_they_are_busy_on(self):
		for key in ('"allocated_elsewhere"', '"allocated_asg"', '"allocated_task"'):
			with self.subTest(key=key):
				self.assertIn(key, self.block)

	def test_the_swap_pool_never_takes_them(self):
		"""a_substitute refuses a busy replacement whatever the flag says, so
		offering one would offer what the server then refuses -- this bug,
		inverted."""
		at = self.block.index("if not busy:")
		free_only = self.block[at:self.block.index("if ALLOW_SPLIT_DAY:", at)]
		self.assertIn("cands.append(emp)", free_only)
		after = self.block[self.block.index("if ALLOW_SPLIT_DAY:", at):]
		self.assertNotIn("cands.append(emp)", after)

	def test_both_pools_are_returned(self):
		self.assertIn('out["candidates"] = cands', self.block)
		self.assertIn('out["add_candidates"] = add_cands', self.block)

	def test_the_flag_travels_with_them(self):
		self.assertIn('out["allow_split_day"] = 1 if ALLOW_SPLIT_DAY else 0', self.block)

	def test_the_dialog_reads_the_payload_rather_than_stale_page_state(self):
		"""`ST._empAll` is filled by the assign and edit flows only; Manage crew
		calls neither, so it was undefined on a fresh load."""
		js = read(SCREEN)
		at = js.index('action:"a_sub_candidates"')
		block = js[at:at + 700]
		self.assertIn("ST._empSplitOk=!!cd.allow_split_day", block)
		self.assertIn("cd.add_candidates", block)

	def test_the_add_pool_is_no_longer_assembled_from_that_state(self):
		js = read(SCREEN)
		self.assertNotIn("ST._empSplitOk ? (ST._empAll || cands) : cands", js)
		self.assertIn("var addPool = addCands || cands;", js)

	def test_the_option_says_what_else_they_are_on(self):
		js = read(SCREEN)
		self.assertIn("c.allocated_elsewhere ?", js)
		self.assertIn("also on ", js)


class TestTheNonNegotiables(unittest.TestCase):
	"""The switch permits a day shared between two DIFFERENT tasks. It does not
	permit anything else, and none of it moves with the flag."""

	def setUp(self):
		self.api = read(API)

	def test_a_worker_already_on_this_roster_is_never_offered(self):
		block = action_block("a_sub_candidates", self.api)
		self.assertIn("if already_map.get(emp.name):", block)
		at = block.index("if already_map.get(emp.name):")
		self.assertIn("continue", block[at:at + 400])

	def test_and_is_refused_by_the_write_too(self):
		block = action_block("a_add_crew", self.api)
		self.assertIn("Already on this assignment: ", block)

	def test_that_refusal_does_not_consult_the_flag(self):
		block = action_block("a_add_crew", self.api)
		at = block.index("Already on this assignment: ")
		self.assertNotIn("ALLOW_SPLIT_DAY", block[at - 700:at])

	def test_the_substitute_path_still_refuses_a_busy_replacement(self):
		"""Deliberately NOT made flag-aware here: swap has different mechanics --
		one out, one in, the replacement inheriting the remaining target -- and
		changing what it permits is a decision, not a bug fix."""
		block = action_block("a_substitute", self.api)
		self.assertIn("already assigned elsewhere for an overlapping period", block)
		at = block.index("already assigned elsewhere for an overlapping period")
		self.assertNotIn("ALLOW_SPLIT_DAY", block[at - 800:at])

	def test_the_replacement_must_not_be_on_the_roster(self):
		block = action_block("a_substitute", self.api)
		self.assertIn("Replacement is already on this plan", block)

	def test_only_live_assignments_make_somebody_busy(self):
		"""A Rejected or Draft assignment is not a claim on anybody's day."""
		for act in ("a_employees", "a_sub_candidates"):
			with self.subTest(action=act):
				block = action_block(act, self.api)
				# in approval or assigned, read from the chain
				self.assertIn('IN (""" + sql_in(ST_ASG_ACTIVE) + """)', block)

	def test_a_released_worker_does_not_make_somebody_busy(self):
		for act in ("a_employees", "a_sub_candidates"):
			with self.subTest(action=act):
				block = action_block(act, self.api)
				self.assertIn("IFNULL(we.status,'Active') = 'Active'", block)


class TestTheServerStillDecides(unittest.TestCase):
	"""The picker is a courtesy. These are the gates, and this commit does not
	touch them -- it only stops the screen contradicting them."""

	def setUp(self):
		self.api = read(API)

	def test_submit_warns_with_the_flag_on_and_refuses_with_it_off(self):
		block = action_block("a_submit", self.api)
		at = block.index("DOUBLE-ALLOCATION GUARD (server enforcement)")
		guard = block[at:at + 3000]
		self.assertIn("if ALLOW_SPLIT_DAY:", guard)
		self.assertIn('out["split_warning"]', guard)
		self.assertIn("already assigned elsewhere for an overlapping period", guard)

	def test_add_crew_warns_with_the_flag_on_and_refuses_with_it_off(self):
		block = action_block("a_add_crew", self.api)
		self.assertIn("if busy and not ALLOW_SPLIT_DAY:", block)
		self.assertIn('out["split_warning"]', block)

	def test_the_screen_shows_the_warning_the_add_path_returns(self):
		js = read(SCREEN)
		at = js.index('action:"a_add_crew"')
		self.assertIn("r.split_warning", js[at:at + 900])

	def test_and_the_one_the_submit_path_returns(self):
		"""Both were computed server-side and dropped on the floor by
		afterSubmit(), so the one screen that could act on them never showed
		them."""
		js = read(SCREEN)
		at = js.index("function afterSubmit(")
		block = js[at:at + 1200]
		self.assertIn("d.split_warning", block)
		self.assertIn("d.crew_warning", block)
		self.assertIn("window.alert(", block)


if __name__ == "__main__":
	unittest.main()
