# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Stage Approver rows name their step by KEY, so renaming a step keeps them.

They stored the step's label. Rename a step and every approver row for it
silently stopped matching: transition_groups() fell back to one unconditional
transition on the stage role, per-farm scoping collapsed -- any holder of the
role approved every farm -- and the next Settings save was refused with a
"Stage cannot be ..." nobody could act on. Altura was armed for it: six approver
rows and a relabelled chain.

And farm_approver_role mapped every farm to the FIRST scoped step's role before
looking at the second, so per-farm rows on a later step were never read.

    bench --site <site> run-tests --app work_management \\
        --module work_management.tests.test_approvers_are_keyed_by_stage
"""

import json
import os
import unittest
from unittest import mock

import frappe

from work_management import approvals
from work_management.api import config

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSIGNER = "Work Management Assigner"
FM = "assigner_farm_manager"


def read(*parts):
	with open(os.path.join(APP, *parts), encoding="utf-8") as handle:
		return handle.read()


def doctype(name):
	return json.loads(read("work_management", "doctype", name, name + ".json"))


def field(name, fieldname):
	return next((f for f in doctype(name)["fields"] if f["fieldname"] == fieldname), None)


def settings(labels=None, approvers=(), enabled=None):
	"""Every shipped step, with `labels` renaming some of them by key."""
	labels = labels or {}
	enabled = enabled or {}
	rows = []
	for idx, stage in enumerate(approvals.CATALOGUE, start=1):
		rows.append(frappe._dict({
			"idx": idx, "stage": stage.key,
			"stage_label": labels.get(stage.key, stage.label),
			"document_type": stage.document_type, "kind": stage.kind,
			"state": stage.state, "action": stage.action,
			"scoped": 1 if stage.scoped else 0,
			"required": 1 if stage.required else 0,
			"enabled": enabled.get(stage.key, 1), "role": stage.role,
		}))
	return frappe._dict({
		"approval_stages": rows,
		"stage_approvers": [frappe._dict(dict(r, idx=i)) for i, r in enumerate(approvers, 1)],
	})


def row(stage, user, scope=None, role=None, stage_label=None):
	return {"stage": stage, "stage_label": stage_label, "user": user, "scope": scope, "role": role}


RENAMED = {FM: "Crew: Manager"}
PER_FARM = [
	row(FM, "sam@example.com", "Saboti", "FM Saboti", "Assigner: Farm Manager"),
	row(FM, "lena@example.com", "Lokitela", "FM Lokitela", "Assigner: Farm Manager"),
]


class TestTheRowCarriesTheKey(unittest.TestCase):
	def test_there_is_a_stage_column(self):
		f = field("work_management_stage_approver", "stage")
		self.assertEqual(f["fieldtype"], "Select")
		self.assertTrue(f.get("reqd"))
		self.assertTrue(f.get("in_list_view"))

	def test_it_offers_the_shipped_keys(self):
		f = field("work_management_stage_approver", "stage")
		self.assertEqual(f["options"].split("\n"), [s.key for s in approvals.CATALOGUE])

	def test_it_comes_first(self):
		self.assertEqual(doctype("work_management_stage_approver")["field_order"][0], "stage")

	def test_the_name_is_no_longer_a_select(self):
		"""A Select on the name is what refused the save after a rename."""
		f = field("work_management_stage_approver", "stage_label")
		self.assertNotEqual(f["fieldtype"], "Select")
		self.assertTrue(f.get("read_only"))
		self.assertFalse(f.get("reqd"))

	def test_the_picker_is_the_key(self):
		self.assertEqual(approvals.PICKER, ("Work Management Stage Approver", "stage"))


class TestARenameKeepsTheApprovers(unittest.TestCase):
	"""The Altura scenario: a relabelled step with per-farm approvers."""

	def test_approvers_for_matches_by_key_after_a_rename(self):
		config_ = settings(RENAMED, PER_FARM)
		self.assertEqual([r.user for r in approvals.approvers_for(FM, config_)],
			["sam@example.com", "lena@example.com"])

	def test_a_name_alone_does_not_match(self):
		"""Strictly the key -- a name is what moves."""
		config_ = settings(RENAMED, [row(None, "sam@example.com", "Saboti",
			stage_label="Crew: Manager")])
		self.assertEqual(approvals.approvers_for(FM, config_), [])

	def test_per_farm_scoping_survives_a_rename(self):
		config_ = settings(RENAMED, PER_FARM)
		plan = approvals.plan_workflow(ASSIGNER, settings=config_)
		fm = [t for t in plan["transitions"]
			if t["state"] == "Pending Farm Manager" and t["action"] == "FM Approve"]
		self.assertEqual(sorted((t["allowed"], t["condition"]) for t in fm), [
			("FM Lokitela", 'doc.farm == "Lokitela"'),
			("FM Saboti", 'doc.farm == "Saboti"'),
		])

	def test_no_unconditional_way_through_after_a_rename(self):
		config_ = settings(RENAMED, PER_FARM)
		plan = approvals.plan_workflow(ASSIGNER, settings=config_)
		self.assertNotIn("", [t["condition"] for t in plan["transitions"]
			if t["state"] == "Pending Farm Manager"])

	def test_roles_are_still_granted_after_a_rename(self):
		grants = approvals._desired_grants(settings(RENAMED, PER_FARM))
		self.assertEqual(grants, {"sam@example.com": {"FM Saboti"},
			"lena@example.com": {"FM Lokitela"}})


class TestSavingKeysAndRenamesTheRows(unittest.TestCase):
	def test_a_row_with_only_a_name_is_keyed_by_it(self):
		"""An older form or an API caller that sends the name."""
		config_ = settings(RENAMED, [row(None, "sam@example.com", stage_label="Crew: Manager")])
		self.assertEqual(approvals.sync_approver_stages(config_), [])
		self.assertEqual(config_.stage_approvers[0].stage, FM)

	def test_the_stored_name_follows_the_rename(self):
		config_ = settings(RENAMED, PER_FARM)
		approvals.sync_approver_stages(config_)
		self.assertEqual({r.stage_label for r in config_.stage_approvers}, {"Crew: Manager"})

	def test_a_row_for_no_step_is_reported(self):
		config_ = settings(RENAMED, [row(None, "sam@example.com", stage_label="Gone")])
		self.assertEqual(approvals.sync_approver_stages(config_), [(1, "Gone")])

	def test_validate_names_the_row_instead_of_stage_cannot_be(self):
		config_ = settings(RENAMED, [row("no_such_step", "sam@example.com")])
		def throw(message, title=None):
			raise frappe.ValidationError(message)

		# the message itself, without needing a site for translation or msgprint
		with mock.patch.object(approvals, "validate_switching_off"), \
				mock.patch.object(approvals, "_", side_effect=lambda text: text), \
				mock.patch.object(approvals.frappe, "throw", side_effect=throw), \
				self.assertRaises(frappe.ValidationError) as caught:
			approvals.validate_configuration(config_)
		self.assertIn("not in the approval chain", str(caught.exception))

	def test_it_runs_before_frappes_own_checks(self):
		"""Settings.validate runs before the mandatory and Select checks, so a
		name-only row is keyed before `stage` is found empty."""
		src = read("work_management", "doctype", "work_management_settings",
			"work_management_settings.py")
		self.assertIn("approvals.validate_configuration(self)", src)
		block = read("approvals.py")
		at = block.index("def validate_configuration(")
		self.assertIn("sync_approver_stages(settings)", block[at:at + 2400])


class TestThePickerShowsTheCurrentName(unittest.TestCase):
	def setUp(self):
		self.js = read("work_management", "doctype", "work_management_settings",
			"work_management_settings.js")

	def test_the_options_are_keys_labelled_with_names(self):
		self.assertIn("names[row.stage] = row.stage_label || row.stage;", self.js)
		self.assertIn('grid.update_docfield_property("stage", "options", options);', self.js)

	def test_the_grid_cell_shows_the_name_not_the_key(self):
		self.assertIn("std.stage.formatter = (value) => names[value] || value;", self.js)

	def test_a_rename_in_the_open_form_relabels_it(self):
		self.assertIn("stage_label: wm_stage_picker,", self.js)

	def test_it_runs_on_refresh(self):
		at = self.js.index("refresh(frm) {")
		self.assertIn("wm_stage_picker(frm);", self.js[at:at + 80])

	def test_the_server_writes_keys_as_options(self):
		src = read("approvals.py")
		at = src.index("def apply_stage_picker_options(")
		block = src[at:at + 2200]
		self.assertIn("keys = stage_keys(settings)", block)
		self.assertIn("stage.key for stage in CATALOGUE", block)


class TestTheBackfill(unittest.TestCase):
	PATCH = "work_management.patches.v1_0.key_stage_approvers_by_stage"

	def run_patch(self, stage_rows, approver_rows):
		from work_management.patches.v1_0 import key_stage_approvers_by_stage as patch

		def get_all(doctype, **kwargs):
			rows = stage_rows if doctype == "Work Management Approval Stage" else approver_rows
			return [frappe._dict(r) for r in rows]

		written = {}
		with mock.patch.object(frappe.db, "table_exists", return_value=True, create=True), \
				mock.patch.object(frappe, "reload_doc"), \
				mock.patch.object(frappe, "get_all", side_effect=get_all), \
				mock.patch.object(frappe.db, "set_value", create=True,
					side_effect=lambda dt, name, f, v, **kw: written.__setitem__(name, v)), \
				mock.patch.object(frappe.db, "delete", create=True) as deleted, \
				mock.patch.object(frappe, "clear_cache"), \
				mock.patch("builtins.print"):
			patch.execute()
		return written, deleted

	def setUp(self):
		# frappe.db is None without a site; give the patch something to patch
		if getattr(frappe.local, "db", None) is None:
			frappe.local.db = mock.MagicMock()
			self.addCleanup(setattr, frappe.local, "db", None)

	def test_it_matches_the_current_name(self):
		written, _ = self.run_patch(
			[{"stage": FM, "stage_label": "Crew: Manager"}],
			[{"name": "r1", "idx": 1, "stage": None, "stage_label": "Crew: Manager", "user": "a"}])
		self.assertEqual(written, {"r1": FM})

	def test_it_falls_back_to_the_shipped_name(self):
		"""A row written before the site renamed its step carries the old name."""
		written, _ = self.run_patch(
			[{"stage": FM, "stage_label": "Crew: Manager"}],
			[{"name": "r1", "idx": 1, "stage": None, "stage_label": "Assigner: Farm Manager",
				"user": "a"}])
		self.assertEqual(written, {"r1": FM})

	def test_an_unmatched_row_is_left_not_deleted(self):
		written, _ = self.run_patch(
			[{"stage": FM, "stage_label": "Crew: Manager"}],
			[{"name": "r1", "idx": 1, "stage": None, "stage_label": "Renamed twice", "user": "a"}])
		self.assertEqual(written, {})

	def test_a_keyed_row_is_left_alone(self):
		written, _ = self.run_patch(
			[{"stage": FM, "stage_label": "Crew: Manager"}],
			[{"name": "r1", "idx": 1, "stage": FM, "stage_label": "Whatever", "user": "a"}])
		self.assertEqual(written, {})

	def test_the_old_label_picker_setter_goes(self):
		_, deleted = self.run_patch([], [])
		deleted.assert_called_once_with("Property Setter", {
			"doc_type": "Work Management Stage Approver", "field_name": "stage_label",
			"property": "options"})

	def test_it_says_it_must_run_before_the_next_rename(self):
		from work_management.patches.v1_0 import key_stage_approvers_by_stage as patch

		self.assertIn("MUST RUN BEFORE ANYBODY RENAMES A STEP AGAIN", patch.__doc__)

	def test_it_is_registered(self):
		self.assertIn(self.PATCH, read("patches.txt"))


class TestEachFarmGetsItsOwnApproverRole(unittest.TestCase):
	"""Two farms, per-farm approvers on the SECOND scoped step only."""

	FARMS = ["Saboti", "Lokitela"]

	def resolve(self, approvers, enabled=None):
		return config._farm_approver_role(settings(approvers=approvers, enabled=enabled), self.FARMS)

	def test_a_later_step_is_read(self):
		mapping = self.resolve([
			row("actuals_farm_manager", "sam@example.com", "Saboti", "FM Saboti"),
			row("actuals_farm_manager", "lena@example.com", "Lokitela", "FM Lokitela"),
		])
		self.assertEqual(mapping, {"Saboti": "FM Saboti", "Lokitela": "FM Lokitela"})

	def test_the_first_step_to_name_a_farm_wins(self):
		mapping = self.resolve([
			row("planner_farm_approval", "sam@example.com", "Saboti", "Planner Saboti"),
			row("actuals_farm_manager", "sam@example.com", "Saboti", "FM Saboti"),
			row("actuals_farm_manager", "lena@example.com", "Lokitela", "FM Lokitela"),
		])
		self.assertEqual(mapping, {"Saboti": "Planner Saboti", "Lokitela": "FM Lokitela"})

	def test_an_unnamed_farm_takes_a_row_that_names_no_farm(self):
		mapping = self.resolve([
			row("actuals_farm_manager", "sam@example.com", "Saboti", "FM Saboti"),
			row("actuals_farm_manager", "gm@example.com", None, "Every Farm"),
		])
		self.assertEqual(mapping, {"Saboti": "FM Saboti", "Lokitela": "Every Farm"})

	def test_with_nobody_named_every_farm_takes_the_first_step_role(self):
		first = next(s for s in approvals.CATALOGUE if s.scoped)
		self.assertEqual(self.resolve([]), {f: first.role for f in self.FARMS})

	def test_a_switched_off_step_decides_nobody(self):
		mapping = self.resolve([
			row("planner_farm_approval", "sam@example.com", "Saboti", "Planner Saboti"),
			row("actuals_farm_manager", "sam@example.com", "Saboti", "FM Saboti"),
		], enabled={"planner_farm_approval": 0})
		self.assertEqual(mapping["Saboti"], "FM Saboti")


if __name__ == "__main__":
	unittest.main()
