"""The five screens work on phones (2026-11-27), and desktop is left alone.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_screens_on_phones -v
"""

import os
import re
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WWW = os.path.join(APP, "www")
SCREENS = ["work-management", "work-planner", "work-assigner", "work-actuals", "work-payment"]


def read(*parts):
	with open(os.path.join(APP, *parts)) as h:
		return h.read()


class TestPhoneLayer(unittest.TestCase):
	def test_every_css_rule_is_phone_only(self):
		css = re.sub(r"/\*.*?\*/", "", read("public", "css", "wm-mobile.css"), flags=re.S).strip()
		self.assertTrue(css.startswith("@media (max-width: 767px) {"), "all rules sit inside the phone query")
		depth, closed_at = 0, None
		for i, ch in enumerate(css):
			if ch == "{":
				depth += 1
			elif ch == "}":
				depth -= 1
				if depth == 0:
					closed_at = i
					break
		self.assertEqual(css[closed_at + 1:].strip(), "", "nothing after the phone query")

	def test_script_does_nothing_on_desktop(self):
		js = read("public", "js", "wm-mobile.js")
		self.assertIn('matchMedia("(max-width: 767px)")', js)
		self.assertLess(js.index("if (!MQ.matches) return;"), js.index("function bar()"))

	def test_bottom_bar_covers_the_five_screens(self):
		js = read("public", "js", "wm-mobile.js")
		for s in SCREENS:
			self.assertIn('"/' + s + '"', js)

	def test_app_detection(self):
		self.assertIn("KaitetWorkApp", read("public", "js", "wm-mobile.js"))


class TestScreensLoadIt(unittest.TestCase):
	def test_viewport_first(self):
		for s in SCREENS:
			with self.subTest(screen=s):
				self.assertTrue(read("www", s + ".html").startswith('<meta name="viewport" content="width=device-width'))

	def test_assets_linked_cache_busted(self):
		for s in SCREENS:
			with self.subTest(screen=s):
				html = read("www", s + ".html")
				self.assertIn('<link rel="stylesheet" href="{{ mobile_css }}">', html)
				self.assertIn('<script src="{{ mobile_js }}" defer></script>', html)
				self.assertIn("mobile_assets(context)", read("www", s.replace("-", "_") + ".py"))

	def test_asset_url_is_versioned(self):
		self.assertIn('return "/assets/%s/%s?v=%s" % (APP, relative, asset_version(relative))', read("assets.py"))


if __name__ == "__main__":
	unittest.main()
