"""A doctype that cannot be submitted must not grant submit.

Frappe refuses it -- "Cannot set Assign Submit if not Submittable" -- and it
refuses it when *anything* saves that doctype's permissions, not when the bad
grant is added. So two shipped child tables carrying `submit` for nine roles each
meant every later permission write on them failed, and the failure named an
innocent role in an unrelated row.

That is how it surfaced: `seed.kaitet` adds one Custom DocPerm for Coffee Clerk
on `Work Actuals Employee`, Frappe revalidated the whole doctype, and the seed
died on `Farm Manager`. The seed is what gives each farm its cost project, so the
visible symptom was a farm with no cost project and a Master Plan screen offering
no activities -- three steps from the cause.

`submit` on a child table is meaningless anyway. A child row is submitted by
submitting its parent; the child table has no submit of its own to grant.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_no_submit_on_child_tables -v
"""

import glob
import json
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCTYPES = os.path.join(HERE, "work_management", "doctype")

# The rights Frappe will not accept on a doctype that is not submittable.
SUBMIT_RIGHTS = ("submit", "cancel", "amend")


def shipped_doctypes():
	"""Every doctype JSON the app ships, by name."""
	out = {}
	for path in sorted(glob.glob(os.path.join(DOCTYPES, "*", "*.json"))):
		slug = os.path.basename(os.path.dirname(path))
		if os.path.basename(path) != slug + ".json":
			continue
		with open(path) as handle:
			doc = json.load(handle)
		if isinstance(doc, dict) and doc.get("doctype") == "DocType":
			out[doc.get("name") or slug] = doc
	return out


class TestNothingGrantsSubmitItCannotHave(unittest.TestCase):
	def test_no_non_submittable_doctype_grants_submit(self):
		offenders = []
		for name, doc in shipped_doctypes().items():
			if doc.get("is_submittable"):
				continue
			for perm in doc.get("permissions", []):
				for right in SUBMIT_RIGHTS:
					if perm.get(right):
						offenders.append("%s grants %s to %s and is not submittable"
							% (name, right, perm.get("role")))
		self.assertEqual(offenders, [], "\n".join(offenders))

	def test_child_tables_specifically(self):
		"""Stated separately because a child row is submitted by submitting its
		parent -- the child table has no submit of its own to grant, so this can
		only ever be a copy-paste from the parent's permission block."""
		for name, doc in shipped_doctypes().items():
			if not doc.get("istable"):
				continue
			for perm in doc.get("permissions", []):
				for right in SUBMIT_RIGHTS:
					with self.subTest(doctype=name, role=perm.get("role"), right=right):
						self.assertFalse(perm.get(right))

	def test_the_two_that_were_wrong_are_still_covered(self):
		"""Named, so that deleting them from the app does not quietly remove the
		only doctypes this test had anything to say about."""
		shipped = shipped_doctypes()
		for name in ("Work Actuals Employee", "Work Assignment Employee"):
			with self.subTest(doctype=name):
				self.assertIn(name, shipped)
				self.assertTrue(shipped[name].get("istable"))


class TestTheSeedDoesNotAskForImpossibleRights(unittest.TestCase):
	"""The other half. Even with the JSON fixed, a seed asking for `submit` on a
	child table would put the bad grant straight back as a Custom DocPerm."""

	def test_kaitet_docperms_ask_only_for_rights_the_doctype_can_have(self):
		from work_management.seed import kaitet

		shipped = shipped_doctypes()
		offenders = []
		for doctype, role, rights in kaitet.KAITET_DOCPERMS:
			doc = shipped.get(doctype)
			if doc is None or doc.get("is_submittable"):
				continue
			for right in SUBMIT_RIGHTS:
				if right in rights:
					offenders.append("seed asks for %s on %s (%s), which is not "
						"submittable" % (right, doctype, role))
		self.assertEqual(offenders, [], "\n".join(offenders))


if __name__ == "__main__":
	unittest.main()
