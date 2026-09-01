"""Every mirror script compiles under the same restrictions live imposes.

Written after breaking live twice in two days with faults my tests could not see,
both of the same kind: the Server Script sandbox rejects things ordinary Python
accepts, and the app -- which is ordinary Python -- happily ran the same code.

  a NameError    `wm_masterplan` used `FARMS` without defining it. The port gives
                 every ported module a `FARMS` from get_config(), so the app was
                 fine and only live failed.
  a SyntaxError  a loop variable called `_sr`. RestrictedPython refuses any name
                 starting with an underscore
                 (`RestrictedPython/transformer.py:401`). Four screens returned
                 500 until it was renamed.

Guessing at the rules and writing assertions for each one guesses badly -- I did
not know the underscore rule existed. So this does not approximate the sandbox:
it **is** the sandbox. `frappe.utils.safe_exec.compile_restricted` with Frappe's
own `FrappeTransformer` policy is exactly what the live site runs when it loads a
Server Script, and every mirror script is put through it here.

That covers the compile-time class: names and attributes beginning with an
underscore, dunder access, and whatever RestrictedPython adds next. It does not
cover the runtime restrictions -- `def` and `import` compile happily and are
blocked later, by the guards and by the absence of `__import__` -- so this is not
a complete simulation of the sandbox, only of the half that fails before any
action runs. That half is the half that returned 500 on every request.

The policy is Frappe's own `FrappeTransformer` where it imports, and a faithful
local copy where it does not -- importing `frappe.utils.safe_exec` pulls in enough
of Frappe to want a logs directory relative to the working directory, which the
suite has no business creating. The copy is exact: `FrappeTransformer` differs
from `RestrictingNodeTransformer` in one line, permitting the name `_dict`
(`frappe/utils/safe_exec.py:68`), and a test below pins that difference so a
divergence shows up here.

Skipped when the mirror is not checked out beside the app.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \\
        work_management.tests.test_mirror_compiles_in_the_sandbox -v
"""

import glob
import os
import unittest

MIRROR = "/home/austin/vscodeProjects/kaitet-work-management/server_scripts"


def sandbox_policy():
	"""The transformer live compiles Server Scripts with.

	Frappe's own where it imports, an exact copy otherwise -- see the module
	docstring for why the import may fail and why the copy is faithful.
	"""
	from RestrictedPython.transformer import RestrictingNodeTransformer

	try:
		from frappe.utils.safe_exec import FrappeTransformer

		return FrappeTransformer, True
	except Exception:
		pass

	class LocalFrappeTransformer(RestrictingNodeTransformer):
		def check_name(self, node, name, *args, **kwargs):
			if name == "_dict":
				return
			return super().check_name(node, name, *args, **kwargs)

	return LocalFrappeTransformer, False


def mirror_scripts():
	return sorted(glob.glob(os.path.join(MIRROR, "*.py")))


class TestEveryScriptCompilesUnderTheSandbox(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		if not os.path.isdir(MIRROR):
			raise unittest.SkipTest("mirror not present")
		try:
			from RestrictedPython import compile_restricted
		except Exception as exc:  # pragma: no cover
			raise unittest.SkipTest("RestrictedPython unavailable: %s" % exc)
		cls.compile_restricted = staticmethod(compile_restricted)
		cls.policy, cls.is_frappes_own = sandbox_policy()

	def compiles(self, path):
		"""Compile one script the way the sandbox does, returning any errors.

		`compile_restricted` raises a SyntaxError whose message carries every
		violation it found, which is what live reported: four separate `_sr`
		lines in one message.
		"""
		with open(path) as handle:
			source = handle.read()
		try:
			self.compile_restricted(source, filename=os.path.basename(path),
				policy=self.policy, mode="exec")
		except SyntaxError as exc:
			return str(exc)
		return None

	def test_there_are_scripts_to_check(self):
		"""A glob that matched nothing would make every assertion below vacuous."""
		self.assertTrue(mirror_scripts())

	def test_every_script_compiles(self):
		failures = []
		for path in mirror_scripts():
			error = self.compiles(path)
			if error:
				failures.append("%s\n    %s" % (os.path.basename(path), error[:400]))
		self.assertEqual(failures, [], "\n".join(failures))


class TestTheCheckActuallyCatchesThings(unittest.TestCase):
	"""A test that cannot fail is worse than no test. These prove the compiler
	being used really does reject what live rejected, so a pass above means
	something."""

	@classmethod
	def setUpClass(cls):
		try:
			from RestrictedPython import compile_restricted
		except Exception as exc:  # pragma: no cover
			raise unittest.SkipTest("RestrictedPython unavailable: %s" % exc)
		cls.compile_restricted = staticmethod(compile_restricted)
		cls.policy, cls.is_frappes_own = sandbox_policy()

	def refused(self, source):
		try:
			self.compile_restricted(source, filename="<probe>", policy=self.policy,
				mode="exec")
		except SyntaxError as exc:
			return str(exc)
		return None

	def test_an_underscore_name_is_refused(self):
		"""The fault that took four screens down."""
		error = self.refused("for _sr in [1]:\n    pass\n")
		self.assertIsNotNone(error, "the sandbox accepted an underscore name")
		self.assertIn("_sr", error)

	def test_an_underscore_attribute_is_refused(self):
		self.assertIsNotNone(self.refused("y = x._thing\n"))

	def test_a_dunder_attribute_is_refused(self):
		self.assertIsNotNone(self.refused("y = x.__class__\n"))

	def test_an_underscore_assignment_is_refused(self):
		self.assertIsNotNone(self.refused("_x = 1\n"))

	def test_the_one_name_frappe_permits_is_permitted(self):
		"""`_dict` is the single way FrappeTransformer differs from the default.
		If the local copy drifts from Frappe's, this is where it shows."""
		self.assertIsNone(self.refused("d = _dict\n"))

	def test_ordinary_code_is_accepted(self):
		"""So a failure above is the script's fault and not the harness's."""
		self.assertIsNone(self.refused(
			"out = {}\nrows = [1, 2, 3]\nfor row in rows:\n    out[row] = row * 2\n"))


if __name__ == "__main__":
	unittest.main()
