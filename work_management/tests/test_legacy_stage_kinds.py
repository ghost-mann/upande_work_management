"""A stage row whose `kind` the doctype no longer offers takes down any save.

The deploy to alturablooms.upande.com died in Migrate Site on 2026-09-15::

    work_management.patches.v1_0.move_farms_to_upande_core
      ...move_farms_to_upande_core.py, line 139, in execute
        settings.save(ignore_permissions=True)
    frappe.exceptions.ValidationError: Row #6: Kind cannot be "Gate".
      It should be one of "Submit", "Approval"

`kind` used to offer `Gate` -- "not a workflow transition, a screen-level check"
-- which nothing ever read and which was dropped from the catalogue and from the
Select. Rows already written kept the value, because `seed_stages()` carries a
row the catalogue does not know **verbatim, `kind` included**; that is the point
of a configurable chain and is right. What is wrong is that no site with such a
row could save Work Management Settings again, and three separate things do:
`move_farms_to_upande_core`, `merge_farms_in_use_into_farms`, and
`approvals.after_migrate` by way of `seed_stages()` -- the last on every migrate.

kentrout.local never carried the row, which is why 1,600 local tests and a local
migrate were green while the live deploy was not. So it is fixtured here.

Reproduced and fixed on kentrout.local by inserting the row the old build left::

    a clean site saves                 saved
    with kind='Gate' at row #16        ValidationError: Row #16: Kind cannot be
                                       "Gate". It should be one of "Submit",
                                       "Approval"
    after the patch                    kind='Approval' enabled=0, saved
    run again                          unchanged
    planner chain                      planner_weekly_consultant Approval on=0

That last line is why converted rows are switched off. A Gate was INERT --
`chain_for()` filtered it out by kind -- and an enabled Approval is a live step.
Left enabled, the row above reads `on=1` and a hotfix deploy quietly adds an
approval to somebody's planner chain.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_legacy_stage_kinds -v
"""

import os
import unittest

from work_management.patches.v1_0 import normalize_legacy_stage_kinds as patch

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATCHES = os.path.join(APP, "patches.txt")
SENTINEL = "WMTESTGATEROW01"

#: Columns that carry meaning. Child-row `name`s churn on every seed_stages(),
#: so restoring compares these and not the primary keys.
COLS = ["stage", "stage_label", "document_type", "kind", "state", "action",
	"scoped", "required", "enabled", "role", "idx"]


def read(path):
	with open(path) as handle:
		return handle.read()


class TestTheDecision(unittest.TestCase):
	"""Pure: what a value becomes. No site."""

	def test_a_value_the_doctype_still_offers_is_left_alone(self):
		for kind in ("Submit", "Approval"):
			with self.subTest(kind=kind):
				self.assertIsNone(patch.replacement(kind))

	def test_gate_becomes_an_approval(self):
		self.assertEqual(patch.replacement("Gate"), "Approval")

	def test_so_does_anything_else_unexpected(self):
		for kind in ("Check", "gate", "", None, "Review"):
			with self.subTest(kind=kind):
				self.assertEqual(patch.replacement(kind), "Approval")

	def test_nothing_ever_becomes_a_submit(self):
		"""Submit is the step that moves a draft into the chain and there is one
		per document type. A second would be a second beginning."""
		self.assertNotEqual(patch.FALLBACK, "Submit")


class TestWhichRowsAreTouched(unittest.TestCase):
	"""Pure: which rows the patch would rewrite, given what the Select offers."""

	OPTIONS = ["Submit", "Approval"]

	def rows(self, *kinds):
		return [{"name": "r%d" % i, "kind": k} for i, k in enumerate(kinds)]

	def test_a_legacy_value_is_found(self):
		found = patch.failing_values(self.rows("Submit", "Gate", "Approval"), self.OPTIONS)
		self.assertEqual([r["name"] for r in found], ["r1"])

	def test_a_clean_table_yields_nothing(self):
		self.assertEqual(patch.failing_values(self.rows("Submit", "Approval"), self.OPTIONS), [])

	def test_an_empty_value_is_not_a_failure(self):
		"""Frappe only checks a Select that has a value, and `kind` is not reqd.
		Rewriting a blank would be this patch inventing a step."""
		self.assertEqual(patch.failing_values(self.rows("", None), self.OPTIONS), [])

	def test_it_reads_the_options_it_is_given(self):
		"""So a site whose Select was widened by a Property Setter is judged by
		its own doctype rather than by this file's idea of one."""
		self.assertEqual(
			patch.failing_values(self.rows("Gate"), ["Submit", "Approval", "Gate"]), [])


class TestItRunsBeforeAnythingThatSavesSettings(unittest.TestCase):
	def setUp(self):
		self.lines = [line.strip() for line in read(PATCHES).splitlines()
			if line.strip() and not line.strip().startswith(("#", "["))]

	def test_it_is_registered(self):
		self.assertIn("work_management.patches.v1_0.normalize_legacy_stage_kinds", self.lines)

	def test_it_precedes_the_patch_that_failed(self):
		self.assertLess(
			self.lines.index("work_management.patches.v1_0.normalize_legacy_stage_kinds"),
			self.lines.index("work_management.patches.v1_0.move_farms_to_upande_core"))

	def test_it_precedes_every_other_patch_that_full_saves_settings(self):
		"""move_farms_to_upande_core is the one that fell over; it is not the only
		one that could. A patch added later that saves Settings and sits above
		this line fails the same way, and this is where that gets noticed."""
		savers = []
		for line in self.lines:
			module = line.rsplit(".", 1)[-1]
			path = os.path.join(APP, "patches", "v1_0", module + ".py")
			if not os.path.exists(path):
				continue
			src = read(path)
			if 'get_doc("Work Management Settings")' in src and ".save(" in src:
				savers.append(line)
		self.assertTrue(savers, "expected to find at least the two known savers")
		mine = self.lines.index("work_management.patches.v1_0.normalize_legacy_stage_kinds")
		for saver in savers:
			with self.subTest(patch=saver):
				self.assertLess(mine, self.lines.index(saver))


class TestItDoesNotGoThroughTheDocumentLayer(unittest.TestCase):
	"""The value is wrong precisely because the schema that judges it has moved
	on, so the fix cannot be a saved document."""

	def setUp(self):
		whole = read(os.path.join(APP, "patches", "v1_0",
			"normalize_legacy_stage_kinds.py"))
		# the code, not the prose. The docstring quotes the live traceback, which
		# contains `settings.save(...)`, and a test that trips on the evidence is
		# one people delete the evidence to satisfy.
		self.src = whole[whole.index('"""', whole.index('"""') + 3) + 3:]

	def test_it_writes_with_set_value(self):
		self.assertIn("frappe.db.set_value(TABLE, row.name,", self.src)

	def test_it_never_loads_or_saves_the_settings_document(self):
		for gone in ('get_doc("Work Management Settings")', "get_single(", ".save("):
			with self.subTest(gone=gone):
				self.assertNotIn(gone, self.src)

	def test_it_leaves_the_modified_stamp_alone(self):
		"""Nobody edited these rows; a migrate did."""
		self.assertIn("update_modified=False", self.src)

	def test_it_is_safe_where_the_table_is_not_there_at_all(self):
		self.assertIn("if not frappe.db.table_exists(TABLE):", self.src)

	def test_it_commits_what_it_wrote(self):
		self.assertIn("frappe.db.commit()", self.src)

	def test_the_audit_only_reads(self):
		at = self.src.index("def audit(")
		block = self.src[at:self.src.index("\ndef execute(")]
		for write in ("set_value", "delete", "insert", ".save("):
			with self.subTest(write=write):
				self.assertNotIn(write, block)


def _site():
	"""The bench test runner gives a site; plain unittest does not."""
	try:
		import frappe
	except ImportError:
		return None
	try:
		if frappe.db is None:
			return None
		frappe.db.sql("select 1")
	except Exception:
		return None
	return frappe


class TestOnARealSettingsTable(unittest.TestCase):
	"""kentrout has no legacy row, so the failure is fixtured and removed again."""

	def setUp(self):
		self.frappe = _site()
		if not self.frappe:
			self.skipTest("no site")
		self.before = self.snapshot()
		self.addCleanup(self.restore)

	def snapshot(self):
		rows = self.frappe.db.get_all(patch.TABLE,
			filters={"parenttype": patch.PARENT}, fields=COLS, order_by="idx asc")
		return [dict(row) for row in rows]

	def restore(self):
		self.frappe.db.delete(patch.TABLE, {"name": SENTINEL})
		self.frappe.db.commit()

	def parent(self):
		return self.frappe.db.get_value(patch.TABLE,
			{"parenttype": patch.PARENT}, "parent") or patch.PARENT

	def add_gate_row(self):
		"""Exactly what the old build left: written without validation, because
		the value was legal when it was written."""
		idx = max([row["idx"] for row in self.before] or [0]) + 1
		self.frappe.db.sql("""
			INSERT INTO `tabWork Management Approval Stage`
			  (name, parent, parenttype, parentfield, idx, stage, stage_label,
			   document_type, kind, state, action, scoped, required, enabled,
			   role, creation, modified, owner, modified_by)
			VALUES (%s, %s, 'Work Management Settings', 'approval_stages', %s,
			        'planner_weekly_consultant', 'Planner: Weekly Consultant',
			        'Work Management Planner', 'Gate', 'Pending Consultant',
			        'Send for Consultant Review', 0, 0, 1, NULL,
			        NOW(), NOW(), 'Administrator', 'Administrator')
		""", (SENTINEL, self.parent(), idx))
		self.frappe.db.commit()
		return idx

	def full_save(self):
		doc = self.frappe.get_doc(patch.PARENT)
		doc.flags.ignore_permissions = True
		doc.flags.skip_approval_sync = True
		doc.save(ignore_permissions=True)

	def kind_of(self, name):
		return self.frappe.db.get_value(patch.TABLE, name, ["kind", "enabled"], as_dict=True)

	def test_the_fixture_reproduces_the_live_failure(self):
		"""If this stops raising, the doctype has widened again and the rest of
		this file is guarding nothing."""
		self.add_gate_row()
		with self.assertRaises(Exception) as caught:
			self.full_save()
		self.assertIn("Gate", str(caught.exception))

	def test_the_patch_makes_the_save_succeed(self):
		self.add_gate_row()
		self.frappe.db.rollback()
		patch.execute()
		self.assertEqual(self.kind_of(SENTINEL).kind, "Approval")
		self.full_save()          # raises if it did not work

	def test_a_converted_row_is_switched_off(self):
		"""A Gate was filtered out of the chain by kind. An enabled Approval is a
		live step, so converting one without disabling it would add an approval
		to a running pipeline during a hotfix."""
		self.add_gate_row()
		self.frappe.db.rollback()
		patch.execute()
		self.assertEqual(self.kind_of(SENTINEL).enabled, 0)

	def test_and_so_does_not_join_the_chain(self):
		"""The chain is read from a FRESH Settings document. effective_chain()
		otherwise takes the cached one, which in a full-suite run predates the
		row this test just inserted -- so the step is missing rather than off,
		and the test passes for the wrong reason or fails for one."""
		from work_management import approvals
		self.add_gate_row()
		self.frappe.db.rollback()
		patch.execute()
		self.frappe.clear_document_cache(patch.PARENT, patch.PARENT)
		settings = self.frappe.get_doc(patch.PARENT)
		steps = {step["key"]: step for step in approvals.effective_chain(
			settings=settings, document_type="Work Management Planner")}
		self.assertIn("planner_weekly_consultant", steps)
		self.assertEqual(steps["planner_weekly_consultant"]["on"], 0)
		self.assertEqual(steps["planner_weekly_consultant"]["kind"], "Approval")

	def test_running_it_twice_changes_nothing_the_second_time(self):
		self.add_gate_row()
		self.frappe.db.rollback()
		patch.execute()
		once = self.kind_of(SENTINEL)
		patch.execute()
		self.assertEqual(dict(self.kind_of(SENTINEL)), dict(once))

	def test_it_is_a_no_op_on_a_site_that_never_had_one(self):
		patch.execute()
		self.assertEqual(self.snapshot(), self.before)

	def test_the_audit_finds_nothing_on_a_clean_site(self):
		self.assertEqual(patch.audit(), 0)

	def test_the_audit_sees_the_legacy_row_before_it_is_fixed(self):
		self.add_gate_row()
		self.assertGreaterEqual(patch.audit(), 1)


if __name__ == "__main__":
	unittest.main()
