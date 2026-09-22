"""Approving one document at a time, several at a time.

The client: *"the system allows submission and approval of one task at a
time... time consuming with a large number of people."* Master plans already
had a bulk path and Payment had bulk send; the three approval tabs between them
did not.

**There is no second approval path.** `run_bulk()` re-enters the calling
module's own dispatcher once per document with `action` and `name` swapped into
form_dict, so a bulk approve performs, to the letter, the transition the row's
own button performs -- the same role gate, the same stage check, the same
writes, the same comment. Copying each module's checks into a bulk branch is
what `wm_masterplan`'s `plans_bulk` does, and it is how the two drift: one gets
a fix, the other does not, and the one that does not is the one people use on a
busy Friday.

Measured on kentrout.local, and the reason strings come back identical because
they are the same strings:

    single  a_approve stage=assigner_hr_head GHOST-1
              -> "Not at the Assigner: HR Head step (state: None)"
    bulk    a_approve_bulk stage=assigner_hr_head
              -> "Not at the Assigner: HR Head step (state: None)"

...for every step of both chains, plus the planner's farm-scope refusal. The
stage is the step's KEY -- see work_management/chain.py and
TestStagesAreNotMixed below for why it is not its action.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_bulk_approvals -v
"""

import os
import re
import unittest

from work_management import bulk

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(APP, "public", "js")
API = os.path.join(APP, "api")


def read(path):
	with open(path) as handle:
		return handle.read()


def js_function(src, name):
	"""One JS function body, declaration to the next one at column 2.

	Every assertion about a screen affordance is scoped through this. Searching
	the whole FILE is what let the first version of this feature ship broken: the
	row checkbox was rendered, `assertIn('data-bpick=', src)` passed, and the
	checkbox was in loadMine -- the History tab -- while the bulk bar it was
	supposed to feed sat on the Approvals tab. Both halves existed; neither could
	see the other; the tests were happy.
	"""
	at = src.index("  function %s(" % name)
	nxt = src.find("\n  function ", at + 10)
	return src[at:nxt if nxt > 0 else len(src)]


def js_call_sites(src):
	"""Every `call(...)` in a screen, as a list of its top-level arguments.

	Paren-balanced rather than regexed, because the first argument is an object
	literal full of commas and a regex either stops inside it or swallows the
	rest of the file.
	"""
	out = []
	for hit in re.finditer(r"(?<![\w.])call\(", src):
		if src[:hit.start()].rstrip().endswith("function"):
			continue  # the declaration, not a call
		i = hit.end()
		depth, start, args = 1, i, []
		while depth:
			ch = src[i]
			if ch in "([{":
				depth += 1
			elif ch in ")]}":
				depth -= 1
				if not depth:
					break
			elif ch == "," and depth == 1:
				args.append(src[start:i].strip())
				start = i + 1
			i += 1
		args.append(src[start:i].strip())
		out.append([a for a in args if a])
	return out


def js_call_params(src):
	"""The parameter names a screen's own `call()` declares, in order.

	There are two conventions in this app, and mixing them is what broke the
	bulk bar. work-payment.js declares `call(args, isWrite, method)` -- its
	second argument really is a verb flag, and its own comment says so. The other
	screens declare `call(args, method)` and take the verb from a writes map.
	Read the declaration rather than assuming one of them.
	"""
	at = src.index("function call(")
	inner = src[at + len("function call("):src.index(")", at)]
	return [x.strip() for x in inner.split(",") if x.strip()]


def js_writes_map(src):
	"""The action names a screen declares as writes, from its `var writes` map.

	This map is not decoration. frappe/app.py:sync_database() commits when the
	request verb is unsafe and ROLLS BACK otherwise, so an action missing from
	here is answered 200 with a success payload by a server that then discards
	the work. Measured on kentrout.local: approve_bulk by GET answered
	`{"summary": "1 approved."}` and left the plan at Pending Approval.
	"""
	at = src.index("var writes")
	end = src.index("}", at)
	return set(re.findall(r"([a-z_]+)\s*:\s*1", src[at:end]))


def js_bulk_actions(src):
	"""The action names the bulk bar sends, from its own `send("...")` calls."""
	return sorted(set(re.findall(r'send\("([a-z_]+)"', src)))


def py_branch(src, action):
	"""One dispatcher branch, `elif action == "x":` to the next branch."""
	for opener in ('elif action == "%s":' % action, 'elif action in ("%s"' % action):
		at = src.find(opener)
		if at >= 0:
			break
	assert at >= 0, action
	nxt = src.find("\n    elif action", at + 10)
	return src[at:nxt if nxt > 0 else len(src)]


#: Which function renders each screen's approval queue -- the one place the
#: bar, the tick-boxes and the wiring all have to agree.
APPROVALS_RENDER = {
	"work-planner.js": "renderAppr",
	"work-assigner.js": "renderStage",
	"work-actuals.js": "loadStage",
}

#: The tab that must NOT grow bulk machinery. It has no bulk bar and no bulk
#: action; a tick-box there selects into a state nothing reads.
NO_BULK_RENDER = "loadMine"


class Recorder:
	"""A dispatcher stand-in: records what form_dict held when it was called.

	run_bulk()'s whole job is to drive somebody else's dispatcher correctly, so
	what it passes and what it restores is the behaviour worth pinning -- and it
	can be pinned without a database.
	"""

	def __init__(self, answers=None, raises=None):
		self.answers = answers or {}
		self.raises = raises or {}
		self.seen = []

	def __call__(self):
		import frappe

		name = frappe.form_dict.get("name")
		self.seen.append(dict(frappe.form_dict))
		if name in self.raises:
			raise self.raises[name]
		return self.answers.get(name, {"workflow_state": "Approved"})


class TestTheSelectionGuards(unittest.TestCase):
	"""Pure, so every module refuses the same shapes in the same words."""

	def test_nothing_ticked(self):
		self.assertIn("Nothing selected", bulk.check_selection([]))
		self.assertIn("Nothing selected", bulk.check_selection(None))
		self.assertIn("Nothing selected", bulk.check_selection(["", None]))

	def test_a_reasonable_selection_passes(self):
		self.assertIsNone(bulk.check_selection(["A", "B"]))

	def test_too_many_at_once(self):
		"""Not a technical ceiling -- the point past which somebody has stopped
		reviewing and is just clicking, and a bulk approve is still an approval."""
		why = bulk.check_selection(["x"] * (bulk.MAX_PER_CALL + 1))
		self.assertIn("Too many at once", why)
		self.assertIn(str(bulk.MAX_PER_CALL), why)

	def test_rejecting_needs_a_reason(self):
		self.assertEqual(bulk.check_selection(["A"], None, needs_reason=True),
			"A reason is required to reject.")
		self.assertEqual(bulk.check_selection(["A"], "   ", needs_reason=True),
			"A reason is required to reject.")
		self.assertIsNone(bulk.check_selection(["A"], "duplicate", needs_reason=True))

	def test_approving_does_not(self):
		self.assertIsNone(bulk.check_selection(["A"], None, needs_reason=False))


class TestTheSummarySentence(unittest.TestCase):
	def test_all_through(self):
		self.assertEqual(bulk.summarise([1, 2, 3], [], "approved"), "3 approved.")

	def test_partial(self):
		self.assertEqual(bulk.summarise([1], [2, 3], "approved"),
			"1 approved, 2 could not be.")

	def test_none(self):
		self.assertEqual(bulk.summarise([], [1], "rejected"),
			"None rejected — 1 could not be.")

	def test_the_verb_travels(self):
		self.assertIn("rejected", bulk.summarise([1], [], "rejected"))


class TestRunBulkDrivesTheRealDispatcher(unittest.TestCase):
	def setUp(self):
		import frappe

		self.frappe = frappe
		self.saved = dict(frappe.form_dict)

	def tearDown(self):
		self.frappe.form_dict.clear()
		self.frappe.form_dict.update(self.saved)

	def test_it_calls_once_per_document(self):
		rec = Recorder()
		ok, failed = bulk.run_bulk(rec, "approve", ["A", "B", "C"])
		self.assertEqual(len(rec.seen), 3)
		self.assertEqual([r["name"] for r in ok], ["A", "B", "C"])
		self.assertEqual(failed, [])

	def test_it_passes_the_single_action_name(self):
		rec = Recorder()
		bulk.run_bulk(rec, "act_gm_approve", ["A"])
		self.assertEqual(rec.seen[0]["action"], "act_gm_approve")

	def test_extra_arguments_travel(self):
		"""A rejection reason has to reach the single action, or the comment it
		writes says nothing."""
		rec = Recorder()
		bulk.run_bulk(rec, "reject", ["A"], base={"reason": "duplicate"})
		self.assertEqual(rec.seen[0]["reason"], "duplicate")

	def test_a_refusal_is_reported_in_the_single_action_s_own_words(self):
		rec = Recorder(answers={"B": {"error": "Not at HR stage (state: Draft)"}})
		ok, failed = bulk.run_bulk(rec, "approve", ["A", "B"])
		self.assertEqual([r["name"] for r in ok], ["A"])
		self.assertEqual(failed, [{"name": "B", "why": "Not at HR stage (state: Draft)"}])

	def test_one_bad_document_does_not_stop_the_rest(self):
		rec = Recorder(raises={"B": ValueError("boom")})
		ok, failed = bulk.run_bulk(rec, "approve", ["A", "B", "C"])
		self.assertEqual([r["name"] for r in ok], ["A", "C"])
		self.assertEqual(failed[0]["name"], "B")
		self.assertIn("boom", failed[0]["why"])

	def test_a_raised_error_is_flattened_to_one_line(self):
		rec = Recorder(raises={"A": ValueError("<b>no</b>\n\n  spaced   out ")})
		_, failed = bulk.run_bulk(rec, "approve", ["A"])
		self.assertNotIn("\n", failed[0]["why"])
		self.assertNotIn("<b>", failed[0]["why"])

	def test_the_callers_form_dict_is_put_back(self):
		"""run_bulk borrows form_dict. A caller that reads it afterwards -- and
		the dispatcher it returns into does -- must not find the last document."""
		self.frappe.form_dict.clear()
		self.frappe.form_dict.update({"action": "approve_bulk", "names": "[...]"})
		bulk.run_bulk(Recorder(), "approve", ["A", "B"])
		self.assertEqual(self.frappe.form_dict.get("action"), "approve_bulk")
		self.assertEqual(self.frappe.form_dict.get("names"), "[...]")
		self.assertIsNone(self.frappe.form_dict.get("name"))

	def test_it_is_put_back_even_when_a_document_raises(self):
		self.frappe.form_dict.clear()
		self.frappe.form_dict.update({"action": "approve_bulk"})
		bulk.run_bulk(Recorder(raises={"A": ValueError("x")}), "approve", ["A"])
		self.assertEqual(self.frappe.form_dict.get("action"), "approve_bulk")


class TestEachModuleWiresItTheSameWay(unittest.TestCase):
	MODULES = {
		"planner.py": ("approve_bulk", "reject_bulk", "wm_planner", "approve", "reject"),
		"assigner.py": ("a_approve_bulk", "a_reject_bulk", "wm_assigner",
			"a_approve", "a_reject"),
		"actuals.py": ("act_approve_bulk", "act_reject_bulk", "wm_actuals",
			"act_approve", "act_reject"),
	}

	def src(self, module):
		return read(os.path.join(API, module))

	def test_every_module_answers_both_bulk_actions(self):
		for module, (app, rej, _fn, _s, _r) in self.MODULES.items():
			with self.subTest(module=module):
				src = self.src(module)
				self.assertIn('elif action in ("%s", "%s"):' % (app, rej), src)

	def test_each_re_enters_its_own_dispatcher(self):
		"""Not a copy of the checks -- the dispatcher itself, so there is one
		approval path and it cannot drift from itself."""
		for module, (_a, _r, fn, _s, _rj) in self.MODULES.items():
			with self.subTest(module=module):
				src = self.src(module)
				at = src.index("bulk.run_bulk(")
				self.assertIn(fn, src[at:at + 260])

	def test_each_uses_the_shared_selection_guard(self):
		for module in self.MODULES:
			with self.subTest(module=module):
				self.assertIn("bulk.check_selection(", self.src(module))

	def test_each_uses_the_shared_summary(self):
		for module in self.MODULES:
			with self.subTest(module=module):
				self.assertIn("bulk.summarise(", self.src(module))

	def test_rejecting_in_bulk_demands_a_reason(self):
		for module in self.MODULES:
			with self.subTest(module=module):
				self.assertIn("needs_reason=bk_reject", self.src(module))

	def test_the_reason_reaches_the_single_reject(self):
		for module in self.MODULES:
			with self.subTest(module=module):
				self.assertIn('{"reason": bk_reason}', self.src(module))

	def test_the_single_reject_records_it(self):
		"""A rejection with no reason sends the requester back to a screen that
		tells them nothing, and whoever rejected has moved on."""
		for module, (_a, _r, _fn, _s, _rj) in self.MODULES.items():
			with self.subTest(module=module):
				src = self.src(module)
				self.assertIn('frappe.form_dict.get("reason")', src)
				at = src.index('rj_why = str(frappe.form_dict.get("reason") or "").strip()')
				self.assertIn("add_comment", src[at:at + 700])

	def test_both_answers_are_returned_for_rendering(self):
		for module in self.MODULES:
			with self.subTest(module=module):
				src = self.src(module)
				self.assertIn('out["ok"] = bk_ok', src)
				self.assertIn('out["failed"] = bk_failed', src)


class TestStagesAreNotMixed(unittest.TestCase):
	"""The assigner and actuals tabs show one stage at a time. Approving across
	stages in one press would approve work the user is not looking at.

	WHICH stage is named by the step's KEY, validated against the chain the site
	runs. It used to be one of `fm`, `gm`, `hr` -- three abbreviations of the
	shipped chain -- which the screen derived by splitting the approve action on
	an underscore. Handed a configured action instead of `a_fm_approve`, that
	produced `undefined`, and the refusal it earned named three steps Altura does
	not have:

	    stage must be one of fm, gm, hr -- the queue on screen decides it
	"""

	def test_neither_whitelists_the_shipped_abbreviations(self):
		for module in ("assigner.py", "actuals.py"):
			with self.subTest(module=module):
				src = read(os.path.join(API, module))
				self.assertNotIn("bk_stages", src)
				self.assertNotIn('"fm": "', src)
				self.assertNotIn('"gm": "', src)
				self.assertNotIn('"hr": "', src)

	def test_both_validate_the_stage_against_the_configured_chain(self):
		for module, doctype in (("assigner.py", "ASG_DT"), ("actuals.py", "ACT_DT")):
			with self.subTest(module=module):
				src = read(os.path.join(API, module))
				branch = py_branch(src, "a_approve_bulk" if module == "assigner.py"
					else "act_approve_bulk")
				self.assertIn("chain.resolve(STAGE_ROWS, %s, stage=bk_stage)" % doctype,
					branch)
				self.assertIn("chain.unknown_stage(bk_stage, STAGE_ROWS, %s)" % doctype,
					branch)

	def test_the_refusal_lists_the_steps_this_chain_actually_has(self):
		"""Pure, and the reason the message is built in one place: a refusal that
		names the shipped chain is worse than useless on a site that renamed it."""
		from work_management import chain

		steps = [
			{"key": "assigner_manager", "document_type": "X", "kind": "Approval",
			 "state": "Awaiting Manager", "on": 1},
			{"key": "assigner_hr", "document_type": "X", "kind": "Approval",
			 "state": "Awaiting HR", "on": 1},
		]
		why = chain.unknown_stage("fm", steps, "X")
		self.assertIn("assigner_manager", why)
		self.assertIn("assigner_hr", why)
		for shipped in ("fm, gm, hr", "Farm Manager", "HR Head"):
			self.assertNotIn(shipped, why)

	def test_the_bulk_path_re_enters_the_one_generic_approve(self):
		"""Not three per-step branches. There is one approval action and it takes
		the step, so bulk and the row button cannot diverge."""
		for module, single in (("assigner.py", "a_approve"), ("actuals.py", "act_approve")):
			with self.subTest(module=module):
				src = read(os.path.join(API, module))
				at = src.index("bulk.run_bulk(")
				self.assertIn('"%s"' % single, src[at:at + 300])
				self.assertIn('{"stage": bk_step["key"]}', src[at:at + 300])

	def test_the_planner_needs_no_stage(self):
		"""Its approve action is chain-driven: it finds the step from the state
		the request is waiting in, so one action already serves every stage. A
		stage may still be SENT -- and is then validated the same way -- because
		its tab lists several steps at once."""
		src = read(os.path.join(API, "planner.py"))
		branch = py_branch(src, "approve_bulk")
		self.assertIn("if not bk_bad and bk_stage:", branch)
		self.assertIn("chain.resolve(STAGE_ROWS", branch)

	def test_the_screens_send_the_stage_key_they_are_showing(self):
		"""Never the step's workflow action, and never a substring of one. The
		key is the only name of a step a screen may hold, and it only ever learns
		it from the server."""
		for screen in ("work-assigner.js", "work-actuals.js"):
			with self.subTest(screen=screen):
				src = read(os.path.join(JS, screen))
				self.assertNotIn('.split("_")[1]', src)
				self.assertIn("wireBulk(body, ", src)
				# the tab's own key travels into the bar
				bar = src[src.index("wireBulk(body, "):]
				self.assertRegex(bar[:120], r"wireBulk\(body, \w+, (c\.stage|stageKey),")


class TestTheControlsAndTheRowsAreOnTheSameTab(unittest.TestCase):
	"""The bug this class exists for.

	The bar rendered on the Approvals tab and the tick-box rendered on the
	History tab, so "Select all shown" ticked nothing, the counter stayed at 0
	and "Approve selected" never enabled. Every assertion below is scoped to ONE
	function, because the previous ones searched the whole file and a feature
	split across two tabs satisfied all of them.
	"""

	SCREENS = ("work-planner.js", "work-assigner.js", "work-actuals.js")

	def render(self, screen):
		return js_function(read(os.path.join(JS, screen)), APPROVALS_RENDER[screen])

	def test_the_bar_is_in_the_approvals_render(self):
		for screen in self.SCREENS:
			with self.subTest(screen=screen):
				self.assertIn("bulkBar(", self.render(screen))

	def test_the_row_checkbox_is_in_the_SAME_function(self):
		"""The assertion the first version needed and did not have."""
		for screen in self.SCREENS:
			with self.subTest(screen=screen):
				self.assertIn('data-bpick="', self.render(screen),
					"%s renders the bulk bar but no row tick-box, so the "
					"selection is always empty" % APPROVALS_RENDER[screen])

	def test_the_wiring_is_in_the_same_function_too(self):
		"""A checkbox nothing wires is a checkbox that ticks and does nothing."""
		for screen in self.SCREENS:
			with self.subTest(screen=screen):
				self.assertIn("wireBulk(", self.render(screen))

	def test_the_checkbox_carries_the_row_s_own_name(self):
		for screen in self.SCREENS:
			with self.subTest(screen=screen):
				self.assertIn('data-bpick="\'+esc(r.name)+\'"', self.render(screen))

	def test_it_reflects_a_selection_already_made(self):
		"""Filter or reload the list and a ticked row must come back ticked."""
		for screen in self.SCREENS:
			with self.subTest(screen=screen):
				self.assertIn('(BULK.picked[r.name]?" checked":"")', self.render(screen))

	def test_the_header_offers_select_all(self):
		for screen in self.SCREENS:
			with self.subTest(screen=screen):
				src = read(os.path.join(JS, screen))
				self.assertIn('id="bulk-all"', js_function(src, "bulkBar"))

	def test_the_selection_column_has_a_header_cell(self):
		"""Without one the header is a column short of its rows and every cell
		after it sits under the wrong title."""
		for screen in self.SCREENS:
			with self.subTest(screen=screen):
				self.assertIn('<th class="c" style="width:34px"></th>',
					self.render(screen))

	def test_the_history_tab_grew_none_of_it(self):
		"""It has no bulk bar and no bulk action, so a tick-box there selects
		into a state nothing reads -- which is exactly where they were."""
		for screen in self.SCREENS:
			with self.subTest(screen=screen):
				mine = js_function(read(os.path.join(JS, screen)), NO_BULK_RENDER)
				self.assertNotIn("data-bpick", mine)
				self.assertNotIn("bulkBar(", mine)
				self.assertNotIn("wireBulk(", mine)


class TestTheApprovalTableIsNotMisaligned(unittest.TestCase):
	"""Adding a column to the header and not the rows -- or the reverse -- shifts
	every cell under the wrong title. It happened on the assigner: an
	eleven-column header over ten-column rows."""

	SCREENS = ("work-planner.js", "work-assigner.js", "work-actuals.js")

	def counts(self, screen):
		block = js_function(read(os.path.join(JS, screen)), APPROVALS_RENDER[screen])
		lines = block.split("\n")
		header = "".join(l for l in lines if "<thead><tr>" in l)
		row, grabbing = "", False
		for line in lines:
			if re.search(r"h\+='<tr", line) and "detailrow" not in line:
				grabbing = True
			if grabbing:
				row += line
			if grabbing and "</tr>'" in line:
				break
		return (header.replace("<thead", "").count("<th"), header.count("?'<th"),
			row.count("<td"), len(re.findall(r"\?\s*\(?'<td", row)))

	def test_the_header_and_the_rows_have_the_same_number_of_columns(self):
		for screen in self.SCREENS:
			with self.subTest(screen=screen):
				th, _cth, td, _ctd = self.counts(screen)
				self.assertEqual(th, td,
					"%s: %d header cells over %d row cells"
					% (APPROVALS_RENDER[screen], th, td))

	def test_and_the_same_number_of_conditional_ones(self):
		"""A column that appears only sometimes has to appear in both, or the
		table is aligned for one kind of user and skewed for the other."""
		for screen in self.SCREENS:
			with self.subTest(screen=screen):
				_th, cth, _td, ctd = self.counts(screen)
				self.assertEqual(cth, ctd)


class TestTheScreensOfferIt(unittest.TestCase):
	SCREENS = ("work-planner.js", "work-assigner.js", "work-actuals.js")

	def src(self, screen):
		return read(os.path.join(JS, screen))

	def test_every_approval_tab_has_the_controls(self):
		for screen in self.SCREENS:
			with self.subTest(screen=screen):
				src = self.src(screen)
				self.assertIn('id="bulk-all"', src)
				self.assertIn('id="bulk-app"', src)
				self.assertIn('id="bulk-rej"', src)

	def test_a_live_count_is_shown_beside_the_buttons(self):
		"""Parity with the master plan tab, which has had one all along."""
		for screen in self.SCREENS:
			with self.subTest(screen=screen):
				src = self.src(screen)
				self.assertIn('id="bulk-n"', src)
				self.assertIn('" selected"', src)

	def test_the_action_counts_what_is_selected(self):
		for screen in self.SCREENS:
			with self.subTest(screen=screen):
				self.assertIn('"Approve selected"+(n?" ("+fmt(n)+")":"")', self.src(screen))

	def test_partial_failure_renders_as_a_summary_not_an_alert_per_document(self):
		for screen in self.SCREENS:
			with self.subTest(screen=screen):
				src = self.src(screen)
				at = src.index("function bulkResult(")
				block = src[at:at + 900]
				self.assertIn("d.summary", block)
				self.assertIn("f.why", block)
				self.assertNotIn("alert(", block)

	def test_rejecting_asks_for_the_reason_in_a_field_not_a_browser_prompt(self):
		"""work-actuals.js has carried a standing rule against window.prompt --
		"a browser prompt is still doing the work of a form" -- and it is right:
		a prompt cannot be a textarea, cannot be styled, and hides the selection
		it is asking about. The field sits in the bar with the rows still
		visible."""
		for screen in self.SCREENS:
			with self.subTest(screen=screen):
				src = self.src(screen)
				self.assertIn('id="bulk-why-text"', src)
				self.assertIn("recorded on every one", src)
				at = src.index("var send=function(which, reason){")
				self.assertNotIn("window.prompt", src[at:at + 2400])

	def test_an_empty_reason_is_refused_before_the_round_trip(self):
		for screen in self.SCREENS:
			with self.subTest(screen=screen):
				src = self.src(screen)
				at = src.index('confirm.onclick=function(){')
				self.assertIn("A reason is required to reject", src[at:at + 500])

	def test_the_reason_field_is_hidden_until_reject_is_pressed(self):
		for screen in self.SCREENS:
			with self.subTest(screen=screen):
				src = self.src(screen)
				at = src.index('id="bulk-why"')
				self.assertIn('display:none', src[at:at + 160])

	def test_approving_does_not_go_through_the_reason_field(self):
		for screen in self.SCREENS:
			with self.subTest(screen=screen):
				src = self.src(screen)
				at = src.index('if(napp) napp.onclick=function(){ send(')
				self.assertNotIn("reason", src[at:at + 120])

	def test_selection_only_counts_rows_still_on_screen(self):
		"""Filter the list, and a tick on a row that is no longer shown must not
		be acted on silently."""
		for screen in self.SCREENS:
			with self.subTest(screen=screen):
				src = self.src(screen)
				at = src.index("function bulkPicked(")
				self.assertIn("live[r.name]", src[at:at + 400])

	def test_the_bulk_call_is_a_post(self):
		"""Not by an argument that says so -- by being in the screen's writes map.

		The version of this test that shipped the bug asserted
		`call(args, true)`, which is the author's INTENT written in a vocabulary
		the helper does not speak. `call(args, method)` takes a dispatcher name
		second, so `true` became the endpoint and every bulk click asked for
		/api/method/true. The verb is decided by `writes[args.action]`, so that
		map is where post-ness has to be asserted.
		"""
		for screen in self.SCREENS:
			with self.subTest(screen=screen):
				src = self.src(screen)
				declared = js_writes_map(src)
				for action in js_bulk_actions(src):
					self.assertIn(
						action, declared,
						"%s sends %s but does not declare it a write, so it goes by GET "
						"-- and frappe/app.py:sync_database() rolls a GET back after "
						"answering it 200." % (screen, action))


class TestTheCallHelperIsCalledTheWayItIsDeclared(unittest.TestCase):
	"""`call(args, method)` takes a DISPATCHER NAME second, never a verb flag.

	The bulk feature shipped with `call(args, true)` on all three screens and on
	the adjust-target Apply. `true` landed in the method position, the endpoint
	became /api/method/true, and every click came back:

	    Failed to get method for command true with 'true'

	Nothing caught it, because the test asserted the mistaken belief rather than
	the mechanism -- `assertIn("call(args, true)", src)`, under the name
	`test_the_bulk_call_is_a_post`. A test written in the same wrong vocabulary as
	the code agrees with it about everything, including what is wrong.
	"""

	SCREENS = ("work-planner.js", "work-assigner.js", "work-actuals.js",
			"work-payment.js", "work-management-dashboard.js")

	#: The short names hooks.py actually maps. A dispatcher not in here is a
	#: 417 in the browser and reads like the action refusing rather than the
	#: endpoint not existing -- which is how `wm_payroll` cost an afternoon.
	def dispatchers(self):
		src = read(os.path.join(APP, "hooks.py"))
		at = src.index("override_whitelisted_methods")
		return set(re.findall(r'"(wm_[a-z_]+)"\s*:', src[at:src.index("}", at)]))

	def test_nothing_is_passed_in_a_position_that_means_something_else(self):
		"""The one that would have caught it.

		A boolean in a `method` position is the bug verbatim; a dispatcher name
		in an `isWrite` position would be its mirror image.
		"""
		for screen in self.SCREENS:
			src = read(os.path.join(JS, screen))
			params = js_call_params(src)
			for args in js_call_sites(src):
				for i, given in list(enumerate(args))[1:]:
					with self.subTest(screen=screen, param=params[i], given=given):
						if params[i] == "method":
							self.assertNotIn(
								given, ("true", "false", "1", "0"),
								"%s: call() takes %s here, so this asks for "
								"/api/method/%s. Whether the request POSTs is decided "
								"by the writes map, not by an argument."
								% (screen, ", ".join(params), given))
						elif params[i] == "isWrite":
							self.assertNotRegex(given, r'^"wm_',
								"%s: %s is the verb flag here, not the endpoint"
								% (screen, params[i]))

	def test_every_endpoint_named_is_one_hooks_py_maps(self):
		known = self.dispatchers()
		for screen in self.SCREENS:
			src = read(os.path.join(JS, screen))
			params = js_call_params(src)
			for args in js_call_sites(src):
				for i, given in list(enumerate(args))[1:]:
					if params[i] != "method":
						continue
					named = given.strip('"\'')
					with self.subTest(screen=screen, endpoint=named):
						self.assertIn(named, known,
							"%s asks for /api/method/%s, which hooks.py does not map"
							% (screen, named))

	def test_an_endpoint_is_knowable_by_reading_the_line(self):
		"""No expressions in the method position."""
		for screen in self.SCREENS:
			src = read(os.path.join(JS, screen))
			params = js_call_params(src)
			for args in js_call_sites(src):
				for i, given in list(enumerate(args))[1:]:
					if params[i] == "method":
						with self.subTest(screen=screen, call=given):
							self.assertRegex(given, r'^"wm_[a-z_]+"$')

	def test_a_screen_never_passes_more_arguments_than_call_takes(self):
		for screen in self.SCREENS:
			src = read(os.path.join(JS, screen))
			params = js_call_params(src)
			for args in js_call_sites(src):
				with self.subTest(screen=screen, n=len(args)):
					self.assertLessEqual(len(args), len(params),
						"%s declares call(%s)" % (screen, ", ".join(params)))

	def test_the_two_conventions_are_still_the_two_this_expects(self):
		"""If a third appears, everything above is checking the wrong positions."""
		self.assertEqual(
			{screen: js_call_params(read(os.path.join(JS, screen)))
				for screen in self.SCREENS},
			{
				"work-planner.js": ["args", "method"],
				"work-assigner.js": ["args", "method"],
				"work-actuals.js": ["args", "method"],
				# the odd one out, and the one the bug was copied from
				"work-payment.js": ["args", "isWrite", "method"],
				"work-management-dashboard.js": ["args"],
			})


class TestAWriteIsNotAnsweredAndThenThrownAway(unittest.TestCase):
	"""frappe/app.py:sync_database() commits on POST and rolls back otherwise.

	So a write action missing from a screen's `writes` map is not a slow path or
	a style problem: the server does the work, answers 200 with the success
	payload, and then discards it. Measured on kentrout.local against the real
	wsgi app -- GET wm_planner?action=approve_bulk answered
	`{"ok": [...], "summary": "1 approved."}` and left the plan at Pending
	Approval; the same request as POST advanced it.

	That is also why in-process verification cannot see this class of bug.
	Calling `wm_planner()` with form_dict swapped never reaches sync_database(),
	so a screen that sends the right payload by the wrong verb passes.
	"""

	BULK_BRANCH = {
		"work-planner.js": ("planner.py", "approve_bulk"),
		"work-assigner.js": ("assigner.py", "a_approve_bulk"),
		"work-actuals.js": ("actuals.py", "act_approve_bulk"),
	}

	#: Write actions that travel by GET today and survive it only because their
	#: server branch calls frappe.db.commit() itself. They work, but on a crutch:
	#: remove the commit and they become silent no-ops with a success toast. The
	#: test below is the alarm on that. Left as they are rather than switched to
	#: POST because the master plan tab is the working reference this round.
	COMMIT_THEIR_OWN = {
		"masterplan.py": ("plans_bulk", "decide_bulk", "send_to_gm", "gm_approve"),
		"rates.py": ("new_rate", "correct_apply", "unit_change_apply"),
	}

	def test_no_bulk_branch_commits_for_itself(self):
		"""The three bulk branches rely on the verb, so the verb must be right."""
		for screen, (module, action) in self.BULK_BRANCH.items():
			with self.subTest(screen=screen):
				branch = py_branch(read(os.path.join(API, module)), action)
				self.assertNotIn("frappe.db.commit()", branch)

	def test_so_every_bulk_action_is_declared_a_write(self):
		for screen, (_module, _action) in self.BULK_BRANCH.items():
			with self.subTest(screen=screen):
				src = read(os.path.join(JS, screen))
				declared = js_writes_map(src)
				for sent in js_bulk_actions(src):
					self.assertIn(sent, declared,
						"%s sends %s by GET, and a GET is rolled back" % (screen, sent))

	def test_the_actions_that_lean_on_their_own_commit_still_have_one(self):
		"""If this fails, that action needs adding to the screen's writes map."""
		for module, actions in self.COMMIT_THEIR_OWN.items():
			src = read(os.path.join(API, module))
			for action in actions:
				with self.subTest(module=module, action=action):
					self.assertIn("frappe.db.commit()", py_branch(src, action),
						"%s:%s no longer commits for itself, and the screen still "
						"sends it by GET -- declare it in the writes map"
						% (module, action))


class TestOnlyActionableRowsAreOffered(unittest.TestCase):
	"""A queue only ever lists what the viewer may act on, so the select-all is
	safe by construction rather than by a second filter in the screen."""

	def test_the_planner_queue_is_already_limited_to_the_viewer_s_steps(self):
		src = read(os.path.join(API, "planner.py"))
		at = src.index('elif action == "pending":')
		block = src[at:at + 3000]
		self.assertIn("if not p_may:", block)
		self.assertIn("continue", block)

	def test_the_assigner_and_actuals_tabs_offer_only_the_viewer_s_stages(self):
		for screen, flag in (("work-assigner.js", "is_farm_manager"),
				("work-actuals.js", "is_farm_manager")):
			with self.subTest(screen=screen):
				self.assertIn(flag, read(os.path.join(JS, screen)))


if __name__ == "__main__":
	unittest.main()
