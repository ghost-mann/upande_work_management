"""The five screens must not serve a stale script, or swallow their own jinja.

TWO BUGS, ONE PAGE LOAD.

1. Frappe Cloud's nginx serves /assets with `cache-control: max-age=31536000,
   immutable`, and every screen injected its script from a URL that never
   changed. `immutable` means the browser does not revalidate -- not on a
   refresh, not on a revisit -- so a reader who had opened a screen before a
   deploy kept running the script from before it, while the page around it
   (no-store) arrived fresh. New markup, old code. Every fix looked undeployed:
   the split-hours box, the crew controls and the release button all "failed to
   appear" on a site whose files were right and whose setting was ticked. Only a
   hard reload showed them. A dev bench sends no such header, so it never
   reproduced locally.

   The src now carries ?v=<mtime>, so the URL changes exactly when the file
   does: one fetch per deploy, and the year-long cache still works in between.

2. work-management.html wrapped its whole body in {% raw %} -- from the app's
   first commit, c0fb42a -- with nothing inside needing it except the two
   expressions it was silencing. `<img src="{{ header_logo }}">` had therefore
   never rendered on the dashboard: the attribute was the literal text. The
   cache-busting src landed inside the same block and was silenced with it,
   which is how the block was found.

So: no template may hardcode its own asset path, and none may leave a jinja
expression inside a {% raw %} block.
"""

import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
WWW = os.path.join(APP, "www")

# route template -> the script it must inject
SCREENS = {
	"work-management.html": "work-management-dashboard.js",
	"work-planner.html": "work-planner.js",
	"work-assigner.html": "work-assigner.js",
	"work-actuals.html": "work-actuals.js",
	"work-payment.html": "work-payment.js",
}


def read(path):
	with open(path) as handle:
		return handle.read()


class TestNoScreenHardcodesItsAssetPath(unittest.TestCase):
	def test_every_screen_injects_a_busted_src(self):
		for tpl in SCREENS:
			with self.subTest(template=tpl):
				src = read(os.path.join(WWW, tpl))
				self.assertIn('s.src = "{{ screen_js }}";', src,
					tpl + " must inject the version its controller computes")

	def test_no_screen_still_names_the_bare_path(self):
		"""A bare /assets/... src is the cached-forever shape."""
		for tpl, js in SCREENS.items():
			with self.subTest(template=tpl):
				src = read(os.path.join(WWW, tpl))
				self.assertNotIn('"/assets/work_management/js/' + js + '"', src,
					tpl + " hardcodes its script path, so a deploy cannot bust it")

	def test_every_controller_computes_one(self):
		for tpl, js in SCREENS.items():
			with self.subTest(template=tpl):
				ctl = os.path.join(WWW, tpl[:-5].replace("-", "_") + ".py")
				self.assertTrue(os.path.exists(ctl), ctl + " missing")
				src = read(ctl)
				self.assertIn("screen_js", src, ctl + " never sets context.screen_js")
				self.assertIn(repr(js).replace('"', "'"), src.replace('"', "'"),
					ctl + " must name " + js)

	def test_the_token_changes_with_the_file(self):
		"""mtime, not a constant: a constant is the bug with extra steps."""
		src = read(os.path.join(APP, "assets.py"))
		self.assertIn("getmtime", src)


class TestNoTemplateSilencesItsOwnJinja(unittest.TestCase):
	"""A {% raw %} block that contains a {{ ... }} renders it as literal text,
	with no error anywhere -- see the dashboard's logo, wrong since c0fb42a."""

	def templates(self):
		return [f for f in sorted(os.listdir(WWW)) if f.endswith(".html")]

	def test_there_are_templates_to_check(self):
		self.assertGreaterEqual(len(self.templates()), 5)

	def test_no_jinja_expression_sits_inside_a_raw_block(self):
		for tpl in self.templates():
			with self.subTest(template=tpl):
				lines = read(os.path.join(WWW, tpl)).split("\n")
				inside, trapped = False, []
				for n, line in enumerate(lines, 1):
					if "{% raw %}" in line:
						inside = True
						continue
					if "{% endraw %}" in line:
						inside = False
						continue
					if inside and re.search(r"\{\{.*?\}\}", line):
						trapped.append("%s:%d %s" % (tpl, n, line.strip()[:70]))
				self.assertEqual(trapped, [],
					"these render as literal text, not values:\n  " + "\n  ".join(trapped))

	def test_the_dashboard_logo_is_a_value_again(self):
		src = read(os.path.join(WWW, "work-management.html"))
		self.assertIn('src="{{ header_logo }}"', src)
		self.assertNotIn("{% raw %}", src,
			"the block held nothing that needed escaping and silenced two expressions")


if __name__ == "__main__":
	unittest.main()
