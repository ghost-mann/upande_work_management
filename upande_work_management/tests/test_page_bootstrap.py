# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Guards on how the www page scripts decide to boot.

The five pages authenticate with the session cookie (``credentials:"same-origin"``)
and every page module refuses Guests in ``get_context``. A page script must
therefore never gate its rendering on the ``frappe`` browser global: when that
global is absent the page is still perfectly usable, and blanking the body
turns a working dashboard into "Open inside Frappe (logged in).".

No site and no database needed::

    ./env/bin/python -m unittest upande_work_management.tests.test_page_bootstrap -v
"""

import os
import re
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(APP, "public", "js")
WWW = os.path.join(APP, "www")


def read(path):
	with open(path, encoding="utf-8") as f:
		return f.read()


class TestDashboardBootstrap(unittest.TestCase):
	def setUp(self):
		self.src = read(os.path.join(JS, "work-management-dashboard.js"))

	def test_reads_nothing_off_the_frappe_global(self):
		"""The premise of any `frappe` guard: the script would need the global."""
		self.assertEqual(
			re.findall(r"\bfrappe\s*\.", self.src),
			[],
			"the dashboard now reads the frappe global — a boot guard may be warranted again",
		)

	def test_does_not_gate_rendering_on_the_frappe_global(self):
		self.assertFalse(
			"typeof frappe" in self.src,
			"the dashboard blanks itself when window.frappe is absent, "
			"though it never uses that global",
		)

	def test_boots_unconditionally(self):
		self.assertIn("if(el(\"wm-body\")) boot();", self.src)


class TestPageScriptInjection(unittest.TestCase):
	def test_dashboard_page_loads_its_script_without_waiting_for_frappe(self):
		"""frappe/templates/base.html defines window.frappe in <head>, synchronously.

		Polling for it cannot succeed where a direct check would fail — it only
		delays the dashboard by the full timeout before failing anyway.
		"""
		html = read(os.path.join(WWW, "work-management.html"))
		code = [ln for ln in html.splitlines() if not ln.lstrip().startswith("//")]
		self.assertFalse(
			[ln for ln in code if "window.frappe" in ln],
			"the page still defers script injection until window.frappe appears",
		)
		self.assertIn("/assets/upande_work_management/js/work-management-dashboard.js", html)


if __name__ == "__main__":
	unittest.main()
