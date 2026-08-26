# Copyright (c) 2026, Upande Ltd and contributors
# For license information, please see license.txt

"""Guards on how the www page scripts decide to boot.

The five pages authenticate with the session cookie (``credentials:"same-origin"``)
and every page module refuses Guests in ``get_context``. A page script must
therefore never gate its rendering on the ``frappe`` browser global: when that
global is absent the page is still perfectly usable, and blanking the body
turns a working dashboard into "Open inside Frappe (logged in).".

No site and no database needed::

    ./env/bin/python -m unittest work_management.tests.test_page_bootstrap -v
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


def without_comments(src):
	"""Strip // and /* */ comments.

	A comment mentioning `frappe.csrf_token` is not the script reading the
	global, and the guard below is about reads.
	"""
	src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
	return re.sub(r"(?<![:\\])//[^\n]*", "", src)


class TestDashboardBootstrap(unittest.TestCase):
	def setUp(self):
		self.src = read(os.path.join(JS, "work-management-dashboard.js"))

	def test_reads_nothing_off_the_frappe_global(self):
		"""The premise of any `frappe` guard: the script would need the global."""
		self.assertEqual(
			re.findall(r"\bfrappe\s*\.", without_comments(self.src)),
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
		self.assertIn("/assets/work_management/js/work-management-dashboard.js", html)


if __name__ == "__main__":
	unittest.main()


class TestEveryPageHasAControllerFrappeCanFind(unittest.TestCase):
	"""A www template's controller must be named the way Frappe looks for it.

	frappe/website/page_renderers/template_page.py's set_pymodule() derives the
	controller path from the template's, replacing hyphens with underscores::

	    os.path.basename(template_basepath.replace("-", "_")) + ".py"

	so `work-planner.html` is served by `work_planner.py`. A controller named
	`work-planner.py` is never found, never imported, and never run -- silently.
	Nothing raises: the page still renders, just with no context. That cost this
	app its Guest check, its no_cache flag and its taxonomy on all five screens
	before anyone noticed, because the failure looks exactly like success.
	"""

	def test_every_template_has_its_controller(self):
		missing = []
		for name in sorted(os.listdir(WWW)):
			if not name.endswith(".html"):
				continue
			wanted = name[: -len(".html")].replace("-", "_") + ".py"
			if not os.path.exists(os.path.join(WWW, wanted)):
				missing.append(f"{name} -> {wanted}")
		self.assertEqual(missing, [], f"templates whose controller Frappe cannot find: {missing}")

	def test_no_controller_is_named_with_a_hyphen(self):
		"""The reverse: a hyphenated .py here is dead weight Frappe will skip."""
		hyphenated = sorted(
			n for n in os.listdir(WWW) if n.endswith(".py") and "-" in n
		)
		self.assertEqual(hyphenated, [], f"controllers Frappe will never import: {hyphenated}")


class TestEveryTemplateCompiles(unittest.TestCase):
	"""Every www template must survive Jinja, which Frappe renders them with.

	CSS written as `@media(max-width:820px){#wpp .grid2{...}}` puts `{#` right
	after the brace, and Jinja reads `{#` as the start of a comment it then
	never finds the end of. The page dies with "Missing end of comment tag"
	before a single line of it reaches the browser. A space after the brace is
	all it takes, so the guard is here rather than in a style rule nobody runs.
	"""

	def test_templates_parse_as_jinja(self):
		import jinja2

		env = jinja2.Environment()
		broken = []
		for name in sorted(os.listdir(WWW)):
			if not name.endswith(".html"):
				continue
			try:
				env.parse(read(os.path.join(WWW, name)))
			except jinja2.TemplateSyntaxError as exc:
				broken.append(f"{name}:{exc.lineno} {exc.message}")
		self.assertEqual(broken, [], f"templates Jinja cannot compile: {broken}")


class TestPagesThatWriteCarryACsrfToken(unittest.TestCase):
	"""A page that POSTs has to be handed the session's CSRF token by its controller.

	Frappe emits `frappe.csrf_token` from the `<!-- csrf_token -->` marker in
	frappe/templates/base.html -- and these templates never reach base.html.
	They carry no `{% extends %}`, and template_page.py decides the wrap against
	`context.base_template`, which is still unset at that point (it is filled in
	afterwards, by post_process_context). So each page renders as a bare
	fragment: no base template, no marker, no token, and every write comes back
	`CSRFTokenError: Invalid Request`. The controller has to supply it.
	"""

	def js_files(self, html):
		return re.findall(r"/assets/work_management/js/([\w-]+\.js)", html)

	def test_writing_pages_emit_and_set_the_token(self):
		for name in sorted(os.listdir(WWW)):
			if not name.endswith(".html"):
				continue
			html = read(os.path.join(WWW, name))
			scripts = [read(os.path.join(JS, js)) for js in self.js_files(html)]
			if not any("X-Frappe-CSRF-Token" in s for s in scripts):
				continue
			with self.subTest(page=name):
				self.assertIn(
					'window.frappe.csrf_token = "{{ csrf_token }}"',
					html,
					f"{name} POSTs but never puts the token on the frappe global",
				)
				controller = name[: -len(".html")].replace("-", "_") + ".py"
				self.assertIn(
					"context.csrf_token = frappe.sessions.get_csrf_token()",
					read(os.path.join(WWW, controller)),
					f"{controller} leaves csrf_token undefined, so the template renders it empty",
				)
