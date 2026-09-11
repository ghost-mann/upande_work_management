"""What changed on an approved record, who changed it, and when.

Frappe writes a Version per document save when `track_changes` is on. What it
does not answer is the question anybody actually asks of an approved plan: *has
this moved since I approved it, and to what?*

**Two facts about this app decide how that is answered, and both were measured
rather than assumed.**

*Most workflow writes leave no Version.* This app moves states with
`frappe.db.set_value(..., update_modified=False)` -- deliberately, because the
workflow engine's transition gate would refuse a script taking a step on
somebody's behalf -- and those bypass the document layer entirely. Confirmed on
kentrout.local: approving a request left the Version count at 1. That is the
right outcome. A state moving along the chain it was designed for is not an
amendment. What DOES version is a real `doc.save()` -- the target adjustment and
the post-approval master plan edit -- so the Versions that exist are, near
enough, exactly the amendments.

*Child rows arrive as `removed` + `added`, not `row_changed`.* Both editors
rebuild their child table, so Frappe cannot match a row to its predecessor. A
summary reading only `row_changed` would report nothing for the master plan line
edit, which is the edit most worth reporting.

**And one bug this found.** `approval_date` is a Date; `Version.creation` is a
datetime. Compared as strings, every same-day edit read as post-approval --
including ones made minutes BEFORE the approval. The approve action stamps
`custom_approved_at` now, and a record with only the date excludes that whole day
rather than sweeping it in: under-reporting an amendment is recoverable, claiming
one that never happened is not.

Measured end to end:

    edit while Draft          banner: None
    submit, approve           banner: None
    adjust 25 -> 40           "Edited after approval: Quantity (total) 25 → 40
                               by Administrator on 2026-09-11 11:34"
    adjust 40 -> 30           "... 40 → 30 ... (and 1 earlier edit)"
    trail                     16 entries, notes and versions interleaved,
                               newest first

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_the_audit_trail -v
"""

import json
import os
import unittest

from work_management import audit

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCTYPES = ("work_management_master_plan", "work_management_planner")


def read(path):
	with open(path) as handle:
		return handle.read()


def js_function(src, name):
	"""One JS function body, from its declaration to the next one at column 2.

	Fixed-size slices are how a test ends up asserting against half a function
	and reporting a failure that is really the window's fault -- which is what
	these did the first time.
	"""
	at = src.index("  function %s(" % name)
	nxt = src.find("\n  function ", at + 10)
	return src[at:nxt if nxt > 0 else len(src)]


def py_action(src, header):
	"""One action branch, from its `elif` to the next one at the same indent."""
	at = src.index(header)
	nxt = src.find("\n    elif action ", at + len(header))
	return src[at:nxt if nxt > 0 else len(src)]


def doctype_json(slug):
	return json.loads(read(os.path.join(HERE, "work_management", "doctype",
		slug, slug + ".json")))


class TestBothDoctypesTrackChanges(unittest.TestCase):
	def test_track_changes_is_on(self):
		for slug in DOCTYPES:
			with self.subTest(doctype=slug):
				self.assertEqual(doctype_json(slug).get("track_changes"), 1)

	def test_track_seen_is_on(self):
		"""So a record carries who has looked at it, which is half of "who knew"."""
		for slug in DOCTYPES:
			with self.subTest(doctype=slug):
				self.assertEqual(doctype_json(slug).get("track_seen"), 1)

	def test_both_have_a_child_table_worth_tracking(self):
		self.assertTrue(any(f["fieldtype"] == "Table"
			for f in doctype_json("work_management_master_plan")["fields"]))
		self.assertTrue(any(f["fieldtype"] == "Table"
			for f in doctype_json("work_management_planner")["fields"]))


class TestWhichWritesAreAmendments(unittest.TestCase):
	"""The design decision, written down because it is invisible in the code."""

	def test_the_module_says_which_writes_version(self):
		src = read(os.path.join(HERE, "audit.py"))
		self.assertIn("update_modified=False", src)
		self.assertIn("doc.save()", src)

	def test_approving_still_uses_the_untracked_write(self):
		"""A state moving along its own chain is not an amendment, and making it
		version would fill the trail with the pipeline working correctly."""
		src = read(os.path.join(HERE, "api", "planner.py"))
		block = py_action(src, 'elif action == "approve":')
		self.assertIn("update_modified=False", block)

	def test_the_adjustment_uses_a_real_save(self):
		src = read(os.path.join(HERE, "api", "planner.py"))
		block = py_action(src, 'elif action in ("raise_target", "adjust_target"):')
		self.assertIn("rd.save(ignore_permissions=True)", block)


class TestTheApprovalAnchor(unittest.TestCase):
	"""The bug: a Date compared against a datetime as strings."""

	def test_a_precise_stamp_is_preferred(self):
		fields, _states = audit.APPROVED_AT["Work Management Planner"]
		self.assertEqual(fields[0], "custom_approved_at")

	def test_the_date_is_only_the_fallback(self):
		fields, _states = audit.APPROVED_AT["Work Management Planner"]
		self.assertIn("approval_date", fields)
		self.assertGreater(fields.index("approval_date"), 0)

	def test_approving_stamps_the_precise_one(self):
		src = read(os.path.join(HERE, "api", "planner.py"))
		self.assertIn('"custom_approved_at",\n                    frappe.utils.now()', src)

	def test_a_date_only_anchor_excludes_its_whole_day(self):
		"""Under-reporting an amendment is recoverable; claiming one that never
		happened is not."""
		src = read(os.path.join(HERE, "audit.py"))
		self.assertIn('return value + " 23:59:59"', src)

	def test_an_unapproved_record_has_no_anchor(self):
		self.assertIsNone(audit.approved_on("Work Management Planner", "x",
			doc={"workflow_state": "Draft", "custom_approved_at": "2026-01-01 10:00:00"}))

	def test_an_approved_one_does(self):
		self.assertEqual(
			audit.approved_on("Work Management Planner", "x",
				doc={"workflow_state": "Approved",
					"custom_approved_at": "2026-01-01 10:00:00"}),
			"2026-01-01 10:00:00")

	def test_a_doctype_this_app_does_not_own_has_none(self):
		self.assertIsNone(audit.approved_on("Sales Invoice", "x"))


class TestTheSummary(unittest.TestCase):
	def setUp(self):
		self.src = read(os.path.join(HERE, "audit.py"))

	def test_an_unapproved_record_gets_no_banner(self):
		"""Pre-approval edits are the normal course of drafting a plan."""
		self.assertIsNone(audit.amended_summary("Work Management Planner", "x",
			doc={"workflow_state": "Draft"}))

	def test_it_counts_edits_not_fields(self):
		"""One target adjustment moves quantity, cost, crew and man-days.
		Reporting that as "and 5 other changes" makes one decision sound like
		six, which is the opposite of what a banner is for."""
		self.assertIn('edits = len({str(c["when"]) for c in changes})', self.src)
		self.assertIn("earlier edit", self.src)

	def test_bookkeeping_fields_are_not_reported(self):
		for field in ("modified", "last_post_approval_edit_by", "total_man_days"):
			with self.subTest(field=field):
				self.assertIn(field, audit.NOISE)

	def test_it_falls_back_to_the_snapshot_when_there_is_no_version(self):
		"""Tracking starts when it is switched on and nothing is backfilled --
		but both doctypes already snapshot the approved figure."""
		self.assertIn("def fallback_change(", self.src)
		self.assertIn("original_qty", self.src)

	def test_the_fallback_covers_both_doctypes(self):
		at = self.src.index("def fallback_change(")
		block = self.src[at:self.src.index("def amended_summary(")]
		self.assertIn("Work Management Planner", block)
		self.assertIn("Work Management Master Plan", block)

	def test_it_is_computed_on_the_server(self):
		"""A summary recomputed in JavaScript is a second implementation of one
		question, and the two disagree the first time either moves."""
		self.assertIn("@frappe.whitelist()", self.src)

	def test_the_whitelisted_call_checks_the_doctype_and_the_permission(self):
		"""It reads Versions and Comments -- a caller naming any doctype could
		read the trail of a document this app knows nothing about."""
		at = self.src.index("def amended_summary(")
		block = self.src[at:self.src.index("def change_trail(")]
		self.assertIn("if doctype not in APPROVED_AT:", block)
		self.assertIn("frappe.has_permission(", block)


class TestChildRowsAreReported(unittest.TestCase):
	def setUp(self):
		self.src = read(os.path.join(HERE, "audit.py"))

	def test_all_four_version_buckets_are_read(self):
		at = self.src.index("def version_changes(")
		block = self.src[at:self.src.index("def fallback_change(")]
		for bucket in ("changed", "added", "removed", "row_changed"):
			with self.subTest(bucket=bucket):
				self.assertIn('payload.get("%s")' % bucket, block)

	def test_the_rebuild_behaviour_is_written_down(self):
		"""Measured, not assumed -- and a summary reading only row_changed would
		report nothing for the edit most worth reporting."""
		self.assertIn("removed", self.src)
		self.assertIn("rebuild", self.src.lower())


class TestTheTrail(unittest.TestCase):
	def setUp(self):
		self.src = read(os.path.join(HERE, "audit.py"))

	def test_it_merges_versions_and_comments(self):
		at = self.src.index("def change_trail(")
		block = self.src[at:]
		self.assertIn("version_changes(", block)
		self.assertIn('"Comment"', block)

	def test_notes_are_marked_as_notes(self):
		self.assertIn('"is_note": 1', self.src)

	def test_it_is_newest_first(self):
		self.assertIn("reverse=True", self.src)

	def test_it_is_capped_with_a_count_of_the_rest(self):
		"""An unbounded trail on a busy record is a page nobody scrolls."""
		self.assertIn("TRAIL_LIMIT", self.src)
		self.assertIn('"older":', self.src)
		self.assertEqual(audit.TRAIL_LIMIT, 20)

	def test_comment_html_is_stripped(self):
		self.assertIn("strip_html", self.src)

	def test_both_screens_can_ask_for_it(self):
		for module in ("planner.py", "masterplan.py"):
			with self.subTest(module=module):
				src = read(os.path.join(HERE, "api", module))
				self.assertIn('elif action == "trail":', src)
				self.assertIn("audit.change_trail(", src)
				self.assertIn("audit.amended_summary(", src)

	def test_the_action_refuses_a_record_that_does_not_exist(self):
		for module in ("planner.py", "masterplan.py"):
			with self.subTest(module=module):
				src = read(os.path.join(HERE, "api", module))
				self.assertIn("no such record",
					py_action(src, 'elif action == "trail":'))


class TestTheScreensShowIt(unittest.TestCase):
	def setUp(self):
		self.js = read(os.path.join(HERE, "public", "js", "work-planner.js"))

	def test_there_is_one_renderer_for_both(self):
		self.assertIn("function amendedRibbon(", self.js)
		self.assertIn("function trailHtml(", self.js)

	def test_the_plan_trace_shows_both(self):
		block = js_function(self.js, "openPlanTrace")
		self.assertIn("amendedRibbon(", block)
		self.assertIn("trailHtml(", block)

	def test_the_master_plan_detail_shows_both(self):
		block = js_function(self.js, "openMasterPlan")
		self.assertIn("amendedRibbon(", block)
		self.assertIn("trailHtml(", block)

	def test_the_ribbon_is_the_server_s_sentence(self):
		self.assertIn("esc(summary)", js_function(self.js, "amendedRibbon"))

	def test_the_trail_says_how_many_are_hidden(self):
		self.assertIn("trail.older", js_function(self.js, "trailHtml"))

	def test_nothing_recorded_reads_as_nothing_recorded(self):
		self.assertIn("No recorded changes yet", js_function(self.js, "trailHtml"))


class TestTheDeskBannersDeploy(unittest.TestCase):
	"""A Client Script created in the desk lives on one site and nowhere else,
	and is the first thing lost when a site is rebuilt."""

	def setUp(self):
		self.fixture = json.loads(read(os.path.join(HERE, "fixtures",
			"client_script.json")))

	def test_there_is_one_per_doctype(self):
		dts = {row["dt"] for row in self.fixture}
		self.assertEqual(dts, {"Work Management Master Plan", "Work Management Planner"})

	def test_they_are_form_scripts_and_enabled(self):
		for row in self.fixture:
			with self.subTest(dt=row["dt"]):
				self.assertEqual(row["view"], "Form")
				self.assertEqual(row["enabled"], 1)

	def test_they_call_the_server_rather_than_recompute(self):
		for row in self.fixture:
			with self.subTest(dt=row["dt"]):
				self.assertIn("work_management.audit.amended_summary", row["script"])

	def test_they_render_as_an_intro(self):
		for row in self.fixture:
			with self.subTest(dt=row["dt"]):
				self.assertIn("set_intro", row["script"])
				self.assertIn("orange", row["script"])

	def test_they_say_nothing_when_there_is_nothing_to_say(self):
		for row in self.fixture:
			with self.subTest(dt=row["dt"]):
				self.assertIn("if (r && r.message)", row["script"])

	def test_hooks_ships_them(self):
		hooks = read(os.path.join(HERE, "hooks.py"))
		self.assertIn('"dt": "Client Script"', hooks)
		for row in self.fixture:
			with self.subTest(name=row["name"]):
				self.assertIn(row["name"], hooks)


if __name__ == "__main__":
	unittest.main()
