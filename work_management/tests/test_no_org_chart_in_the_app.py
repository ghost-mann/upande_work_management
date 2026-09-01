"""Installing this app must not invent anybody's job titles.

The baseline asked for is that the app be applicable to farm work evaluation --
the domain stays, everything about one customer goes. It very nearly is: on a
site that had never heard of Kaitet, with a made-up company and a farm called
Riverbend, eleven of thirteen screens worked and the Master Plan offered
"Weeding 250" and "Pruning 300" with nothing configured but a farm and a cost
project.

What was not portable was the org chart. Installing created five roles:

    Farm Manager · General Manager · HOD HR · HR Clerk · Production Section Head

all at 22:59:17 on the day it was installed, while `HR Manager`, `HR User`,
`Accounts Manager`, `Accounts User` and `System Manager` dated from July, when
ERPNext and HRMS went on. The app had stopped *shipping* those five as fixtures;
the shipped doctype permissions still *named* them, and Frappe creates a Role it
finds in a DocPerm. So a farm with a Head of People and no "HOD HR" got one
anyway.

The rule now: **a shipped doctype may only grant to a role that already exists on
a stock ERPNext + HRMS site.** A fresh install therefore reaches only System
Manager, which is exactly how the approval chain already seeds -- visible, safe,
and obviously not final. Each site then grants its own roles.

Kaitet loses nothing: all 32 grants move to `seed.kaitet`, which re-adds them as
Custom DocPerms on that site alone. The list below is the record of what moved,
so "nothing was lost" is checkable rather than asserted.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_no_org_chart_in_the_app -v
"""

import glob
import json
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCTYPES = os.path.join(HERE, "work_management", "doctype")

# Verified present on a fresh ERPNext + HRMS site before this app was installed,
# by their creation timestamps. Granting to these invents nothing.
STOCK_ROLES = {
	"System Manager",
	"HR Manager",
	"HR User",
	"Accounts Manager",
	"Accounts User",
	# Frappe's own pseudo-roles, which are never created by an app
	"All",
	"Guest",
	"Desk User",
}

# The five the app used to create. Named so the failure message can say which
# problem this is, rather than only that a rule was broken.
ONCE_CREATED_BY_THIS_APP = {
	"Farm Manager",
	"General Manager",
	"HOD HR",
	"HR Clerk",
	"Production Section Head",
}


def shipped_doctypes():
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


class TestNoDoctypeNamesAnInventedRole(unittest.TestCase):
	def test_every_granted_role_already_exists_on_a_stock_site(self):
		offenders = []
		for name, doc in shipped_doctypes().items():
			for perm in doc.get("permissions", []):
				role = perm.get("role")
				if role and role not in STOCK_ROLES:
					why = ("this app used to create it"
						if role in ONCE_CREATED_BY_THIS_APP
						else "no stock ERPNext or HRMS site has it")
					offenders.append("%s grants to %r -- %s" % (name, role, why))
		self.assertEqual(sorted(offenders), [], "\n".join(sorted(offenders)))

	def test_none_of_the_five_survives(self):
		"""Stated separately so a regression names the actual problem."""
		for name, doc in shipped_doctypes().items():
			for perm in doc.get("permissions", []):
				with self.subTest(doctype=name, role=perm.get("role")):
					self.assertNotIn(perm.get("role"), ONCE_CREATED_BY_THIS_APP)

	def test_something_can_still_reach_the_doctypes(self):
		"""The other direction. Stripping every grant would leave an app nobody
		can open, which passes the rule above and is useless."""
		for name, doc in shipped_doctypes().items():
			if doc.get("istable"):
				continue
			roles = {p.get("role") for p in doc.get("permissions", [])}
			with self.subTest(doctype=name):
				self.assertIn("System Manager", roles)


class TestKaitetKeepsWhatItHad(unittest.TestCase):
	"""The 32 grants removed above, as a record. `seed.kaitet` must re-add every
	one of them, or a site that has been running for a year quietly loses access
	on its next migrate."""

	MOVED = [
		("Work Actuals Employee", "Farm Manager"),
		("Work Actuals Employee", "HR Clerk"),
		("Work Actuals Employee", "Production Section Head"),
		("Work Actuals Employee", "HOD HR"),
		("Work Actuals Employee", "General Manager"),
		("Work Assignment Employee", "Farm Manager"),
		("Work Assignment Employee", "HR Clerk"),
		("Work Assignment Employee", "Production Section Head"),
		("Work Assignment Employee", "HOD HR"),
		("Work Assignment Employee", "General Manager"),
		("Work Management Actuals", "HR Clerk"),
		("Work Management Actuals", "HOD HR"),
		("Work Management Actuals", "General Manager"),
		("Work Management Actuals", "Farm Manager"),
		("Work Management Actuals", "Production Section Head"),
		("Work Management Assigner", "HOD HR"),
		("Work Management Assigner", "General Manager"),
		("Work Management Assigner", "Farm Manager"),
		("Work Management Assigner", "Production Section Head"),
		("Work Management Master Plan", "General Manager"),
		("Work Management Master Plan", "HOD HR"),
		("Work Management Master Plan", "Farm Manager"),
		("Work Management Payment", "HR Clerk"),
		("Work Management Payment", "HOD HR"),
		("Work Management Payment", "General Manager"),
		("Work Management Planner", "Production Section Head"),
		("Work Management Planner", "Farm Manager"),
		("Work Management Planner", "HOD HR"),
		("Work Management Planner", "General Manager"),
		("Work Management Section", "Farm Manager"),
		("Work Management Section", "General Manager"),
		("Work Task Rate", "Farm Manager"),
	]

	# Already in the seed before any of this: roles the seed itself creates, so
	# they were never in a shipped doctype and never reached another farm.
	ALWAYS_SEEDED = [
		("Work Actuals Employee", "Coffee Clerk"),
		("Work Assignment Employee", "Coffee Clerk"),
		("Work Management Planner", "Agriculture Manager"),
	]

	def setUp(self):
		from work_management.seed import kaitet
		self.seeded = {(dt, role) for dt, role, _rights in kaitet.KAITET_DOCPERMS}

	def test_the_seed_restores_every_grant_that_moved(self):
		missing = [p for p in self.MOVED if p not in self.seeded]
		self.assertEqual(missing, [],
			"the Kaitet site would lose these on its next migrate:\n"
			+ "\n".join("%s / %s" % p for p in missing))

	def test_the_seed_does_not_invent_grants_that_never_existed(self):
		"""A seed that granted more than the app used to would widen access on
		the quiet, which is the opposite failure and just as bad."""
		allowed = set(self.MOVED) | set(self.ALWAYS_SEEDED)
		extra = [p for p in self.seeded if p not in allowed]
		self.assertEqual(sorted(extra), [], "\n".join("%s / %s" % p for p in sorted(extra)))

	def test_all_thirty_two_are_accounted_for(self):
		self.assertEqual(len(self.MOVED), 32)

	def test_the_seed_creates_the_five_it_inherited(self):
		"""They used to arrive by accident, created by Frappe from the shipped
		DocPerms. With those gone the seed has to make them itself, or a rebuilt
		Kaitet site gets the grants without the roles and restore_docperms()
		skips every one of them without a word."""
		from work_management.seed import kaitet

		for role in ONCE_CREATED_BY_THIS_APP:
			with self.subTest(role=role):
				self.assertIn(role, kaitet.KAITET_ROLES)

	def test_the_roles_the_seed_grants_to_are_the_ones_it_creates(self):
		"""Every role the seed hands access to must be one it also makes, or the
		grant silently does nothing on a rebuilt site."""
		from work_management.seed import kaitet

		makes = set(kaitet.KAITET_ROLES) | STOCK_ROLES
		for _dt, role, _rights in kaitet.KAITET_DOCPERMS:
			with self.subTest(role=role):
				self.assertIn(role, makes)


class TestTheDependenciesAreDeclared(unittest.TestCase):
	"""The two dashboard screens that died on the clean site did so because HRMS
	was not installed -- `Employee Checkin` is an HRMS doctype and
	`employment_type` an HRMS field. The app installed happily and then failed
	with `Unknown column 'employment_type'`, which tells somebody nothing.

	An undeclared dependency is a portability bug: it works wherever it was
	built and fails obscurely everywhere else.
	"""

	def setUp(self):
		from work_management import hooks
		self.required = list(getattr(hooks, "required_apps", []) or [])

	def test_upande_core_is_required(self):
		"""Farms are its records; nothing works without it."""
		self.assertIn("upande_core", self.required)

	def test_hrms_is_required(self):
		self.assertIn("hrms", self.required)

	def test_the_app_reads_hrms_doctypes(self):
		"""The evidence for the line above, so nobody deletes it as unnecessary."""
		import glob as _glob

		hits = []
		for path in _glob.glob(os.path.join(HERE, "api", "*.py")):
			text = open(path).read()
			if "Employee Checkin" in text or "employment_type" in text:
				hits.append(os.path.basename(path))
		self.assertTrue(hits, "no api module reads an HRMS doctype any more")


if __name__ == "__main__":
	unittest.main()
